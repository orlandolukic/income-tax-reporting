"""Reports ("Izveštaji" page): ready-made reports read from TiM ERP, e.g. "Promet u poslednjih 12 meseci".

Like jobs, a report is asked for by the page (server thread, POST /api/reports/run) and run on the main
thread (`process_pending`, called from the "ready" prompt's tick), because WebDriver must only be used
from there. A report may need another year of the company (TiM ERP keeps each year separately):
`ctx.switch_year(year)` logs in again and opens the same company in that year (main.py); afterwards the
runner always opens the year the user had chosen again.

Each company's results are kept in data/reports.json (newest REPORT_HISTORY per report), with a CSV
copy in data/reports/ served at GET /files/izvestaji/<name>. PDF and Excel copies are made there freshly on
every request (POST /api/reports/export, see export.py; no browser is used).
"""
import csv
import json
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tim_automation import ui
from tim_automation.pages import site_error

DATA_FILE = Path("data") / "reports.json"
FILES_DIR = Path("data") / "reports"
REPORT_HISTORY = 20


class ReportError(Exception):
    """A request the page made that can't be done (shown to the user)."""


class Cancelled(Exception):
    pass


@dataclass
class ReportContext:
    driver: object
    year: str  # the company's year open in the browser right now ("" if not known)
    progress: Callable[[str], None]
    update: Callable[[dict], None]  # publish the partly filled value
    cancelled: Callable[[], bool]
    switch_year: Callable[[str], None] | None  # None: the year can't be changed (company chosen in the browser)
    settings: dict = field(default_factory=dict)  # the report's settings (⚙ on the page), checked by its check_settings

    def check_cancel(self) -> None:
        if self.cancelled():
            raise Cancelled()


@dataclass
class ReportType:
    id: str
    title: str
    description: str
    run: Callable[[ReportContext], dict]
    csv_rows: Callable[[dict], list[list]] | None = None  # rows of the CSV copy (first row = header)
    excel: Callable[[object, dict], None] | None = None  # fills an openpyxl Workbook from a result
    pdf: Callable[[dict], bytes] | None = None  # the result as a PDF (reportlab, see export.py)
    notes: list[str] = field(default_factory=list)  # shown on the page before it is run
    settings: list["Setting"] = field(default_factory=list)  # what the user can set (⚙), with defaults
    # Settings from the page -> the normalized values to store; raises ValueError with a message for the user.
    check_settings: Callable[[dict], dict] | None = None

    def defaults(self) -> dict:
        return {s.name: s.default for s in self.settings}


@dataclass
class Setting:
    name: str
    label: str
    kind: str  # "text" | "number" | "bool" | "select"
    default: object
    options: tuple[str, ...] = ()
    help: str = ""


REPORT_TYPES: dict[str, ReportType] = {}


def report_type(report: ReportType) -> ReportType:
    REPORT_TYPES[report.id] = report
    return report


from tim_automation.reports import turnover  # noqa: E402  (registers its report)


# --- store ---------------------------------------------------------------------------------------

_lock = threading.Lock()


def _read() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"companies": {}}


def _write(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATA_FILE)


def history(company: str | None) -> dict[str, list[dict]]:
    if not company:
        return {}
    with _lock:
        return _read()["companies"].get(company, {}).get("runs", {})


def settings(company: str | None, report: ReportType) -> dict:
    """The report's settings for this company: the saved ones over the defaults."""
    saved = {}
    if company:
        with _lock:
            saved = _read()["companies"].get(company, {}).get("settings", {}).get(report.id, {})
    return {**report.defaults(), **{k: v for k, v in saved.items() if k in report.defaults()}}


def all_settings(company: str | None) -> dict[str, dict]:
    return {r.id: settings(company, r) for r in REPORT_TYPES.values()}


def save_settings(company: str, label: str, report: ReportType, values: dict) -> dict:
    values = {k: values.get(k, v) for k, v in report.defaults().items()}
    if report.check_settings:
        values = report.check_settings(values)
    with _lock:
        data = _read()
        entry = data.setdefault("companies", {}).setdefault(company, {"label": label, "runs": {}})
        entry.setdefault("settings", {})[report.id] = values
        _write(data)
    return values


def save_result(company: str, label: str, result: dict) -> None:
    with _lock:
        data = _read()
        entry = data.setdefault("companies", {}).setdefault(company, {"label": label, "runs": {}})
        entry["label"] = label
        runs = entry.setdefault("runs", {}).setdefault(result["report"], [])
        runs.insert(0, result)
        del runs[REPORT_HISTORY:]
        _write(data)


def file_name(result: dict, ext: str) -> str:
    return f"{result['report']}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(result['started_at']))}.{ext}"


def _save_csv(report: ReportType, result: dict) -> str:
    if not report.csv_rows or not result.get("value"):
        return ""
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    name = file_name(result, "csv")
    with open(FILES_DIR / name, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";").writerows(report.csv_rows(result["value"]))
    return name


# --- runner --------------------------------------------------------------------------------------


class ReportRunner:
    def __init__(self) -> None:
        self.driver = None
        self.company: str | None = None  # key (main.company_key): each company has its own results
        self.label = ""
        self.year = ""  # the year the user opened
        self.switch_year: Callable[[str], None] | None = None  # set by main.py
        self.recover: Callable[[], None] | None = None  # set by main.py: new browser, same company and year
        self.queue: queue.Queue[str] = queue.Queue()
        self.current: dict | None = None
        self.cancel_requested = threading.Event()
        ui.register_api("reports", self.handle_api)
        ui.register_files("izvestaji", FILES_DIR)
        self.publish()

    def publish(self) -> None:
        ui.set_shared("reports", {
            "types": [{"id": r.id, "title": r.title, "description": r.description, "notes": r.notes,
                       "settings": [s.__dict__ | {"options": list(s.options)} for s in r.settings]}
                      for r in REPORT_TYPES.values()],
            "settings": all_settings(self.company),
            "company": {"key": self.company, "label": self.label} if self.company else None,
            "history": history(self.company),
            "current": self.current,
            "runner": {
                "ready": self.driver is not None,
                "running": self.current["report"] if self.current else None,
                "queued": list(self.queue.queue),
            },
        })

    def handle_api(self, action: str, body: dict) -> dict | None:
        if action == "run":
            if body.get("company") != self.company:
                raise ReportError("Firma je u međuvremenu promenjena: osvežite stranicu.")
            if body.get("report") not in REPORT_TYPES:
                raise ReportError(f"Nepoznat izveštaj: {body.get('report')}")
            if self.driver is None:
                raise ReportError("Pretraživač nije spreman: prijavite se i izaberite firmu.")
            if self.current or not self.queue.empty():
                raise ReportError("Izveštaj se već izrađuje.")
            self.queue.put(body["report"])
            self.publish()
            return None
        if action == "settings":
            report = REPORT_TYPES.get(body.get("report"))
            if report is None:
                raise ReportError(f"Nepoznat izveštaj: {body.get('report')}")
            if not self.company or body.get("company") != self.company:
                raise ReportError("Firma je u međuvremenu promenjena: osvežite stranicu.")
            if self.current and self.current["report"] == report.id:
                raise ReportError("Izveštaj se upravo izrađuje; podešavanja promenite posle.")
            try:
                values = save_settings(self.company, self.label, report, body.get("values") or {})
            except ValueError as e:
                raise ReportError(str(e)) from None
            print(f"Settings of {report.title!r} saved: {values}")
            self.publish()
            return {"settings": values}
        if action == "cancel":
            if self.current:
                self.cancel_requested.set()
                self.current["progress"] = "Zaustavljanje..."
                self.publish()
            return None
        if action == "export":
            return {"fajl": self.export(body.get("report", ""), body.get("id", ""), body.get("format", ""))}
        raise ReportError(f"Nepoznata akcija: {action}")

    def export(self, report_id: str, result_id: str, fmt: str) -> str:
        """Make the PDF or Excel copy of a saved result, freshly each time; returns its file name in FILES_DIR.
        The name has the time it was made (a copy still open in Excel can't be overwritten); older copies
        of the same result are deleted when possible."""
        from tim_automation.reports import export

        report = REPORT_TYPES.get(report_id)
        result = next((r for r in history(self.company).get(report_id, []) if r["id"] == result_id), None)
        if report is None or result is None:
            if self.current and self.current["id"] == result_id:
                raise ReportError("Sačekajte da se izveštaj završi.")
            raise ReportError("Izveštaj nije pronađen (možda je otvorena druga firma).")
        if not result.get("value"):
            raise ReportError("Ovaj izveštaj nema podataka.")
        if fmt not in ("pdf", "xlsx") or not (report.pdf if fmt == "pdf" else report.excel):
            raise ReportError(f"Format „{fmt}“ nije podržan.")
        data = export.pdf(report, result) if fmt == "pdf" else export.xlsx(report, result)
        base = file_name(result, fmt).removesuffix(f".{fmt}")
        name = f"{base}-{time.strftime('%H%M%S')}.{fmt}"
        FILES_DIR.mkdir(parents=True, exist_ok=True)
        for old in FILES_DIR.glob(f"{base}-*.{fmt}"):
            try:
                old.unlink()
            except OSError:  # open in another program
                pass
        (FILES_DIR / name).write_bytes(data)
        print(f"Report {result_id}: {fmt.upper()} made ({name}, {len(data) // 1024} KB).")
        return name

    def attach(self, driver, label: str, company: str | None, year: str) -> None:
        self.driver, self.label, self.company, self.year = driver, label, company, year
        self.publish()

    def detach(self) -> None:
        self.driver = None
        self.company = None
        while not self.queue.empty():
            self.queue.get_nowait()
        self.publish()

    def busy(self) -> bool:
        return self.current is not None or not self.queue.empty()

    def process_pending(self) -> None:
        """Run the reports the page asked for. Call this regularly from the main thread."""
        while self.driver is not None:
            try:
                report_id = self.queue.get_nowait()
            except queue.Empty:
                return
            self.run(REPORT_TYPES[report_id])

    def run(self, report: ReportType) -> dict:
        company, label, original_year = self.company, self.label, self.year
        result = {
            "id": f"{int(time.time() * 1000):x}", "report": report.id, "title": report.title,
            "status": "running", "started_at": time.time(), "finished_at": None,
            "progress": "Pokretanje...", "error": "", "value": None, "fajl": "", "firma": label,
            "pib": company.split("	")[1] if company and "	" in company else "",
        }
        self.current = result
        self.cancel_requested.clear()
        state = {"year": original_year, "last_publish": 0.0}
        print(f"Report {report.title!r} for {label}...")
        ui.status(f"Izveštaj: {report.title}")
        self.publish()

        def progress(text: str) -> None:
            result["progress"] = text
            print(f"  {text}")
            self.publish()

        def update(value: dict) -> None:
            result["value"] = json.loads(json.dumps(value))
            self.publish()

        def switch(year: str) -> None:
            if year == state["year"]:
                return
            progress(f"Otvaranje godine {year}...")
            state["year"] = ""  # unknown until it worked
            self.switch_year(year)
            state["year"] = year

        ctx = ReportContext(self.driver, original_year, progress, update, self.cancel_requested.is_set,
                            switch if self.switch_year else None, settings(company, report))
        result["podesavanja"] = ctx.settings
        print(f"  Settings: {ctx.settings}")
        try:
            result["value"] = report.run(ctx)
            result["status"] = "done"
        except Cancelled:
            result["status"] = "cancelled"
            result["error"] = "Zaustavljeno."
            print("  Report cancelled.")
        except Exception as e:
            traceback.print_exc()
            result["status"] = "failed"
            result["error"] = f"{type(e).__name__}: {e}".splitlines()[0]
        self._restore(result, original_year, state["year"])
        result["finished_at"] = time.time()
        result["progress"] = ""
        try:
            result["fajl"] = _save_csv(report, result)
        except OSError as e:
            print(f"  Could not save the CSV copy: {e}")
        if company:
            save_result(company, label, result)
        self.current = None
        ui.status("Spremno")
        print(f"Report {report.title!r}: {result['status']} in {result['finished_at'] - result['started_at']:.1f} s.")
        self.publish()
        return result

    def _restore(self, result: dict, original_year: str, year: str) -> None:
        """Leave the browser as the user had it: their year of the company (also after a site error)."""
        try:
            if site_error.shown(self.driver):
                print(f"The site shows „{site_error.MESSAGE}“: restarting the browser.")
                result["error"] = (result["error"] + " " if result["error"] else "") + f"Sajt je prikazao „{site_error.MESSAGE}“."
                if self.recover:
                    result["progress"] = "Ponovno pokretanje pretraživača..."
                    self.publish()
                    self.recover()
                return
            if original_year and year != original_year and self.switch_year:
                result["progress"] = f"Vraćanje na godinu {original_year}..."
                self.publish()
                print(f"  Opening year {original_year} again...")
                self.switch_year(original_year)
        except Exception as e:
            traceback.print_exc()
            note = f"Vraćanje na godinu {original_year} nije uspelo ({type(e).__name__}: {e}); izaberite firmu ponovo."
            result["error"] = (result["error"] + " " if result["error"] else "") + note
