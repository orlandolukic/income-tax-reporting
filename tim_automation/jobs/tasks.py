"""Task types: the building blocks of a job. Each type has a title, the settings (params) the user
fills in on the job page, and a run function that does the work in the TiM ERP browser and returns a
value (anything JSON-serializable, or None).

To add a type, write a function and decorate it with @task_type. A run function that raises
NotImplementedError shows as "nije implementirano" and the job continues with the next task.

Values that list rows use one shape, so later tasks can take data from them (see runner.resolve_params):
{"kolone": [...], "redovi": [{kolona: tekst}, ...], "broj": len(redovi), ...}.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver

from tim_automation import home_status, menu, purs_pdf, purs_queue, purs_reports, ui
from tim_automation import purs_balance as purs_balance_mod
from tim_automation.jobs import conditions, pages
from tim_automation.pages import app_page, dexpress, fiscal, item_form, items_page, order_form, podvrste, purs
from tim_automation.pages.wd_table import main_table


@dataclass(frozen=True)
class Param:
    """One setting of a task, shown as a form field on the job page."""
    name: str
    label: str
    # "text", "number", "select" (one of `options`), "menu" (a menu item path), "column" (a column of
    # the page opened by an earlier task), "filters" (a list of advanced filters, see app_page), "bool"
    # (a checkbox: True / False), "conditions" (checks of a "Uslov" task), "task" (the id of a later
    # task, where "Nastavi" jumps to), "dataset" (an earlier task whose whole value is used:
    # {"ref": task id, "pick": "value"}), "date" (DD/MM/YYYY, typed with a mask), "textarea" (several lines) or
    # "secret" (e.g. a PIN: a password field, kept in the credential store, see secret_params.py)
    kind: str = "text"
    options: tuple[str, ...] = ()
    default: str = ""
    help: str = ""
    required: bool = False
    # Whether the value can come from an earlier task's result instead of being typed in.
    allow_ref: bool = True
    # Show the field only when another param has this value, e.g. ("rows", "Ograničeno").
    show_if: tuple[str, str] | None = None
    # In a subtask, an empty value means this column of the row the subtask runs for.
    row_column: str = ""
    # kind "filters": the fields to offer (same shape as pages.KNOWN[...]["filteri"]); empty = the
    # "Napredni filteri" fields of the page opened by an earlier "Otvori stranicu".
    fields: tuple[dict, ...] = ()
    # kind "choice": options the program loads for the value of param `depends` (e.g. Podvrsta for a Vrsta),
    # from BUILTIN_CHOICES[choices][that value].
    depends: str = ""
    choices: str = ""
    # Section of the task's form the field is shown in (e.g. "Iznosi"); fields of one group are shown together under
    # its title, in the order of their first field. Empty = above the sections.
    group: str = ""


@dataclass
class TaskContext:
    """What a running task can use."""
    driver: WebDriver
    job: dict
    # Values returned by the job's earlier tasks, by task id.
    outputs: dict[str, Any] = field(default_factory=dict)
    # Set by the runner: shows a short progress text under the running task on the job page.
    progress: Callable[[str], None] = lambda text: None
    # Set by the runner: True once the user clicked "Zaustavi". A task that waits long checks it (check_cancel / sleep).
    cancelled: Callable[[], bool] = lambda: False
    # This run's ePorezi state, e.g. "pib" = the taxpayer its "Odabir poreskog obveznika" chose (purs_queue: other
    # items may choose another taxpayer between this job's PURS tasks; its next PURS task gets this one back).
    purs: dict = field(default_factory=dict)

    def log(self, message: str) -> None:
        print(f"    {message}")

    def check_cancel(self) -> None:
        if self.cancelled():
            raise TaskCancelled()

    def sleep(self, seconds: float) -> None:
        """Wait, but stop at once (TaskCancelled) when the user stops the job."""
        deadline = time.monotonic() + seconds
        while True:
            self.check_cancel()
            left = deadline - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.25))


class TaskCancelled(Exception):
    """The user stopped the job while this task was running."""

    def __init__(self, message: str = "Zaustavljeno.") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class TaskType:
    id: str
    title: str
    description: str
    params: tuple[Param, ...]
    run: Callable[[TaskContext, dict], Any]
    implemented: bool = True
    # Columns of the rows this type returns, when known in advance (offered to later tasks before a run).
    output_columns: tuple[str, ...] = ()
    # Whether it returns rows (then it can have subtasks that run for each row).
    returns_rows: bool = False
    # Names of the totals it returns ("ukupno"), when known in advance.
    totals: tuple[str, ...] = ()
    # If set, the task can be a "prekidač" (breaker): it returns {"uslov": bool, ...} and when "uslov"
    # is False a subtask skips the rest of its row, a task stops the job. The text says when that is.
    breaker_when: str = ""
    # Subtasks that run once after this task (e.g. on the page it opened) when param `name` == value.
    # Without it, a type that returns rows has subtasks that run for each row.
    subtasks_when: tuple[str, Any] | None = None
    # Its subtasks always run once after it (it opens a page; the runner goes back afterwards).
    subtasks_once: bool = False
    # Kind of each known output column: "number" / "date" (others are text). The job page warns when a column of
    # another kind goes into a number or date field; the runner checks the values (runner._check_kind).
    column_kinds: dict = field(default_factory=dict)
    # Group of task types in the page's lists (e.g. "PURS – Poreska uprava").
    group: str = ""


GROUP_TIM = "TiM ERP"
GROUP_FLOW = "Tok posla"
GROUP_PURS = "PURS – Poreska uprava (ePorezi)"
GROUP_DEXPRESS = "D Express"

TASK_TYPES: dict[str, TaskType] = {}
# Types that only steer the job (not tied to a site).
FLOW_TYPES = ("empty", "loop", "condition", "continue", "break", "stop")


def task_type(id: str, title: str, description: str, params: tuple[Param, ...] = (), implemented: bool = True,
              output_columns: tuple[str, ...] = (), returns_rows: bool | None = None, totals: tuple[str, ...] = (),
              breaker_when: str = "", subtasks_when: tuple[str, Any] | None = None, subtasks_once: bool = False,
              column_kinds: dict | None = None, group: str = GROUP_TIM):
    """Register the decorated function as a task type."""
    def register(run: Callable[[TaskContext, dict], Any]):
        rows = bool(output_columns) if returns_rows is None else returns_rows
        kind = GROUP_FLOW if id in FLOW_TYPES else group
        TASK_TYPES[id] = TaskType(id, title, description, params, run, implemented, output_columns, rows, totals,
                                  breaker_when, subtasks_when, subtasks_once, dict(column_kinds or {}), kind)
        return run
    return register


# Options of "choice" params, read once from the program and kept in the code (they don't change).
BUILTIN_CHOICES: dict[str, dict[str, list[str]]] = {"podvrste": podvrste.PODVRSTE}


def describe() -> list[dict]:
    """Task types for the web page (the run functions stay here)."""
    menu_paths = tuple(item.path for item in menu.MENU)
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "implemented": t.implemented,
            "outputColumns": list(t.output_columns),
            "returnsRows": t.returns_rows,
            "totals": list(t.totals),
            "breakerWhen": t.breaker_when,
            "subtasksWhen": list(t.subtasks_when) if t.subtasks_when else None,
            "subtasksOnce": t.subtasks_once,
            "columnKinds": t.column_kinds,
            "group": t.group,
            "params": [
                {**p.__dict__, "options": list(menu_paths if p.kind == "menu" else p.options)} for p in t.params
            ],
        }
        for t in TASK_TYPES.values()
    ]


# --- Task types -----------------------------------------------------------------------------------

@task_type("empty", "Prazan zadatak", "Ne radi ništa i ne vraća vrednost. Služi za probu toka posla.")
def empty(ctx: TaskContext, params: dict) -> None:
    return None


@task_type(
    "open_menu", "Otvori stranicu",
    "Otvara stranicu iz glavnog menija i vraća šta je na njoj: naslov, tabele sa kolonama i broj redova.",
    (Param("item", "Stranica", "menu", required=True, allow_ref=False),),
)
def open_menu(ctx: TaskContext, params: dict) -> dict:
    item = menu.find(params["item"])
    ctx.log(f"Opening {item.path} ({item.js})")
    info = app_page.open_menu_item(ctx.driver, item)
    pages.save(item.path, info)
    return {"stranica": item.path, **info}


QUICK, ADVANCED = "Brza pretraga", "Napredni filteri"


@task_type(
    "search", "Pretraga",
    "Pretražuje listu otvorene stranice i vraća sve pronađene redove glavne tabele (sa svim kolonama). "
    "Brza pretraga koristi polje „Filter…“, a napredni filteri prozor „Napredni filteri“ (polje, operator, "
    "vrednost). Zadatak „Otvori stranicu“ treba da bude pre ovog.",
    (
        Param("mode", "Način pretrage", "select", (QUICK, ADVANCED), default=QUICK, allow_ref=False),
        Param("value", "Tekst za pretragu", required=True, show_if=("mode", QUICK)),
        Param("column", "Kolona", "column", default="Naziv", show_if=("mode", QUICK),
              help="Zadržava samo redove čija ova kolona sadrži tekst. Prazno = svi redovi koje sajt vrati."),
        Param("filters", "Filteri", "filters", allow_ref=False, show_if=("mode", ADVANCED),
              help="Uključuju se samo ovi filteri; ostali filteri u prozoru se isključuju."),
        Param("rows", "Broj redova", "select", ("Svi redovi", "Ograničeno"), default="Svi redovi", allow_ref=False,
              help="Svi redovi: čita celu listu (duge liste se čitaju skrolovanjem i traju duže)."),
        Param("limit", "Najviše redova", "number", default="200", allow_ref=False, show_if=("rows", "Ograničeno")),
    ),
    returns_rows=True,
)
def search(ctx: TaskContext, params: dict) -> dict:
    limit = int(params.get("limit") or 0) if params.get("rows") == "Ograničeno" else 0
    last = [0.0]

    def progress(read: int, expected: int) -> None:
        if time.monotonic() - last[0] > 1 or read >= expected:
            last[0] = time.monotonic()
            ctx.progress(f"Pročitano {read} / {expected} redova")
            if read % 500 < 15:
                ctx.log(f"Read {read} of {expected} rows")

    if params.get("mode") == ADVANCED:
        filters = params.get("filters") or []
        if not filters:
            raise ValueError("Dodajte bar jedan filter.")
        ctx.log(f"Advanced filters: {filters} (limit {limit or 'all rows'})")
        return app_page.search_advanced(ctx.driver, filters, limit, progress)
    ctx.log(f"Searching for {params['value']!r} (column {params.get('column') or 'any'}, limit {limit or 'all rows'})")
    return app_page.search_rows(ctx.driver, str(params["value"]), params.get("column") or "", limit, progress)


@task_type(
    "loop", "Petlja",
    "Prolazi kroz redove izabranog ranijeg zadatka ili podzadatka (npr. rezultat „Pretrage“, fiskalni računi "
    "dokumenta) i za svaki red izvršava svoje podzadatke. U podzadacima je dostupan „Trenutni red“ sa kolonama "
    "tog skupa podataka.",
    (
        Param("izvor", "Skup podataka", "dataset", required=True, allow_ref=False,
              help="Zadatak čije redove petlja obrađuje, jedan po jedan."),
        Param("rows", "Broj redova", "select", ("Svi redovi", "Ograničeno"), default="Svi redovi", allow_ref=False),
        Param("limit", "Najviše redova", "number", default="10", allow_ref=False, show_if=("rows", "Ograničeno")),
    ),
    returns_rows=True,
)
def loop(ctx: TaskContext, params: dict) -> dict:
    source = params.get("izvor")
    rows = source.get("redovi") if isinstance(source, dict) else source if isinstance(source, list) else None
    if not isinstance(rows, list):
        raise ValueError("Izabrani skup podataka nema redove; izaberite zadatak koji vraća redove (npr. „Pretraga“).")
    limit = int(params.get("limit") or 0) if params.get("rows") == "Ograničeno" else 0
    picked = [r if isinstance(r, dict) else {"Vrednost": r} for r in (rows[:limit] if limit else rows)]
    columns = (source.get("kolone") if isinstance(source, dict) else None) or (list(picked[0]) if picked else [])
    ctx.log(f"Loop over {len(picked)} of {len(rows)} rows")
    return {"kolone": columns, "redovi": picked, "broj": len(picked), "ukupno_u_izvoru": len(rows)}


@task_type(
    "fiscal_receipts", "Fiskalni računi",
    "Na stranici Maloprodaja › Izlazi označi dokument, otvori Opcije › Fiskalni računi i vrati sve fiskalne "
    "račune (način plaćanja po računu) i ukupne iznose, pa zatvori prozor.",
    (
        Param("document", "Dokument", row_column="Dokument",
              help="Broj dokumenta iz kolone „Dokument“ (npr. PD26-0011). Prazno = u podzadatku Dokument "
                   "trenutnog reda, inače dokument koji je trenutno označen."),
    ),
    totals=("Kartica", "Ček", "Virman", "Vaučer", "Mobilni", "Drugo", "Gotovina", "Ukupno"),
    output_columns=("Dokument", "Broj računa", "Vreme", "Kartica", "Ček", "Virman", "Vaučer", "Mobilni", "Drugo",
                    "Gotovina", "Ukupno"),
    column_kinds={c: "number" for c in ("Kartica", "Ček", "Virman", "Vaučer", "Mobilni", "Drugo", "Gotovina", "Ukupno")},
)
def fiscal_receipts(ctx: TaskContext, params: dict) -> dict:
    if not fiscal.available(ctx.driver):
        raise LookupError(fiscal.NOT_AVAILABLE)
    document = _select_document(ctx, params)
    ctx.log("Opening Opcije > Fiskalni računi")
    result = fiscal.read_fiscal_receipts(ctx.driver)
    ctx.log(f"{result['broj']} receipts, totals {result['ukupno']}")
    for problem in result["razlike"]:
        ctx.log(f"Totals check: {problem}")
    # Each row says which document it belongs to (useful when the task runs for several documents).
    result["dokument"] = document
    result["kolone"] = ["Dokument", *result["kolone"]]
    result["redovi"] = [{"Dokument": document, **row} for row in result["redovi"]]
    return result


def _select_document(ctx: TaskContext, params: dict) -> str:
    """Select the document given in params["document"] (or use the selected one); returns its number."""
    document = str(params.get("document") or "").strip()
    if document:
        ctx.log(f"Selecting document {document}")
        app_page.select_row(ctx.driver, "Dokument", document)
        return document
    selected = app_page.selected_row(ctx.driver)
    if not selected:
        raise LookupError("Nijedan dokument nije označen. Upišite broj dokumenta u polje „Dokument“.")
    ctx.log(f"Using the selected document {selected.get('Dokument', '')}")
    return selected.get("Dokument", "")


@task_type(
    "financial_order", "Finansijski nalog",
    "Na stranici Maloprodaja › Izlazi označi dokument i proveri da li ima finansijski nalog (link „Finansijski "
    "nalog: …“ ispod liste). Vraća broj naloga i ostale veze dokumenta (KIR redni broj, PDV obračun, …). "
    "Može i da otvori nalog: tada se njegovi podzadaci izvršavaju na stranici naloga, a posle njih se program "
    "vraća na listu.",
    (
        Param("document", "Dokument", row_column="Dokument",
              help="Broj dokumenta iz kolone „Dokument“. Prazno = u podzadatku Dokument trenutnog reda, "
                   "inače dokument koji je trenutno označen."),
        Param("open", "Klikni na finansijski nalog", "bool", default=False, allow_ref=False,
              help="Otvara stranicu naloga; podzadaci ovog zadatka se izvršavaju na njoj. Posle njih program sam "
                   "klikne „Nazad“ ako to nije uradio zadatak „Nazad“."),
    ),
    output_columns=("Dokument", "Finansijski nalog", "Postoji"),
    returns_rows=False,
    breaker_when="finansijski nalog ne postoji",
    subtasks_when=("open", True),
)
def financial_order(ctx: TaskContext, params: dict) -> dict:
    document = _select_document(ctx, params)
    if document and not app_page.wait_details(ctx.driver, document):
        ctx.log(f"The details of {document} did not appear in time; reading what is shown.")
    links = app_page.linked_documents(ctx.driver)
    order = links.get("Finansijski nalog", "")
    ctx.log(f"{document}: financial order {order or 'none'}; links {links}")
    opened = {}
    if params.get("open") is True and order:
        before = app_page.view_name(ctx.driver)
        ctx.log(f"Opening financial order {order}")
        after = app_page.open_link(ctx.driver, "Finansijski nalog")
        # "prikaz_pre": the runner goes back to this page after the subtasks (see runner._descend).
        opened = {"prikaz_pre": before, "otvoreno": app_page.describe_page(ctx.driver)["naslov"], "prikaz": after}
    return {
        **opened,
        "dokument": document,
        "postoji": bool(order),
        "nalog": order,
        "povezano": links,
        "uslov": bool(order),
        "kolone": ["Dokument", "Finansijski nalog", "Postoji"],
        "redovi": [{"Dokument": document, "Finansijski nalog": order, "Postoji": "da" if order else "ne"}],
    }


@task_type(
    "create_financial_order", "Pravljenje finansijskog naloga",
    "Na stranici Finansije › Finansijski nalozi (otvara je ako nije otvorena) klikne „Unos“, popuni nalog (vrsta, "
    "podvrsta, datum, broj dokumenta, opis) i klikne „Sačuvaj“. Broj naloga (npr. „OK“ 36) program sajta dodeljuje "
    "sam; zadatak ga vraća. Uz „Obriši nalog ako postoji“ prvo obriše postojeći nalog iste vrste i broja dokumenta.",
    (
        Param("obrisi", "Obriši nalog ako postoji", "bool", default=False, allow_ref=False,
              help="Pre unosa traži nalog iste vrste sa istim brojem dokumenta i briše ga (potvrdi pitanje sajta). "
                   "Briše se samo nalog „u pripremi“; nalog u drugom stanju (ili više takvih naloga) je greška i "
                   "ništa se ne briše. Traži broj dokumenta."),
        Param("vrsta", "Vrsta", "select", order_form.VRSTE, default="Ostala knjiženja", allow_ref=False, required=True,
              group="Nalog"),
        Param("podvrsta", "Podvrsta", "choice", depends="vrsta", choices="podvrste", group="Nalog",
              help="Program je puni kad se izabere vrsta. Prazno = kako program postavi (npr. „Nema“)."),
        Param("datum", "Datum", "date", required=True, group="Nalog",
              help="DD/MM/GGGG. Iz zadatka može i npr. „31.10.2026.“: pretvara se u 31/10/2026."),
        Param("dokument", "Broj dokumenta", group="Nalog", help=f"Najviše {order_form.DOCUMENT_MAX} znakova."),
        Param("opis", "Opis", "textarea", group="Nalog"),
    ),
    output_columns=("Vrsta", "Podvrsta", "Tip naloga", "Broj naloga", "Datum", "Broj dokumenta", "Opis", "Obrisan nalog"),
    column_kinds={"Broj naloga": "number", "Datum": "date"},
    returns_rows=False,
)
def create_financial_order(ctx: TaskContext, params: dict) -> dict:
    vrsta, podvrsta = str(params.get("vrsta") or ""), str(params.get("podvrsta") or "")
    options = podvrste.PODVRSTE.get(vrsta)
    if podvrsta and options and podvrsta not in options:
        raise ValueError(f"Podvrsta „{podvrsta}“ ne postoji za vrstu „{vrsta}“; postoje: {', '.join(options)}.")
    if app_page.view_name(ctx.driver) != order_form.VIEW:
        item = menu.find(order_form.MENU_PATH)
        ctx.log(f"Opening {item.path} ({item.js})")
        app_page.open_menu_item(ctx.driver, item)
    dokument = str(params.get("dokument") or "").strip()
    deleted: list[str] = []
    if params.get("obrisi") is True:
        order_form.normalize_date(params.get("datum"))  # a bad date fails before anything is deleted
        deleted = order_form.delete_existing(ctx.driver, vrsta, dokument, log=ctx.log)
    result = order_form.create(
        ctx.driver, vrsta, params.get("datum"), podvrsta=podvrsta,
        dokument=dokument, opis=str(params.get("opis") or ""), log=ctx.log)
    filled, after = result["popunjeno"], result["posle"]
    row = dict(filled)
    # The saved order as the page shows it now (its type and number).
    row.update({k: after.get(k) or filled.get(k, "") for k in ("Tip naloga", "Broj naloga")})
    row["Obrisan nalog"] = ", ".join(deleted)
    ctx.log(f"Financial order saved: {row}")
    return {
        "nalog": f"{row.get('Tip naloga', '')} {row.get('Broj naloga', '')}".strip(),
        "kolone": list(row),
        "redovi": [row],
        "broj": 1,
    }


# Params of "Pravljenje stavke" -> field of the item form (pages/item_form.py).
ITEM_PARAMS = {
    "konto": "Konto", "analitika": "Analitička šifra", "datum": "Datum", "datum_placanja": "Datum plaćanja",
    "dokument": "Dokument", "duguje": "Duguje", "potrazuje": "Potražuje", "opis": "Opis", "org_jed": "Org. jed.",
    "mpt": "MPT", "devizna_klauzula": "Devizna klauzula", "devizna_valuta": "Devizna valuta", "dev_dug": "Dev. dug.",
    "dev_pot": "Dev. pot.", "vrsta_kursa": "Vrsta kursa", "kurs": "Kurs",
}
FOREIGN = ("devizna_klauzula", "devizna_valuta", "dev_dug", "dev_pot", "vrsta_kursa", "kurs")
AS_PROGRAM = "Kako program ponudi"


@task_type(
    "create_order_item", "Pravljenje stavke",
    "Na stranici stavki finansijskog naloga klikne „Unos“, popuni stavku i klikne „Sačuvaj“. Ako je otvoren sam "
    "finansijski nalog, prvo klikne „Stavke“. Popunjava samo zadata polja; ostala ostaju kako ih program ponudi "
    "(npr. sa prethodne stavke). Ako je zadat samo Duguje ili samo Potražuje, druga strana je 0. Vraća upisanu "
    "stavku i nove zbirove naloga.",
    (
        Param("nalog", "Nalog (provera)", group="Nalog",
              help="Npr. „OK 36“ ili vrednost „nalog“ zadatka „Pravljenje finansijskog naloga“ ($3.nalog$). Ako su "
                   "otvorene stavke drugog naloga, zadatak javlja grešku. Prazno = bez provere."),
        Param("konto", "Konto", required=True, group="Konto i šifre",
              help="Šifra konta, npr. 2410. Program upiše naziv konta."),
        Param("analitika", "Analitička šifra", group="Konto i šifre", help="Npr. šifra komitenta, za konta sa analitikom."),
        Param("org_jed", "Org. jed.", group="Konto i šifre", help="Šifra organizacione jedinice."),
        Param("mpt", "MPT", group="Konto i šifre", help="Šifra mesta troška."),
        Param("datum", "Datum", "date", group="Datumi i dokument", help="DD/MM/GGGG. Prazno = kako program ponudi."),
        Param("datum_placanja", "Datum plaćanja", "date", group="Datumi i dokument"),
        Param("dokument", "Dokument", group="Datumi i dokument", help=f"Najviše {item_form.DOCUMENT_MAX} znakova."),
        Param("duguje", "Duguje", "number", group="Iznosi",
              help="Npr. 1234,56 ili -1234,56; iz zadatka i sa minusom: -$3.1.ukupno.Virman$."),
        Param("potrazuje", "Potražuje", "number", group="Iznosi"),
        Param("opis", "Opis", "textarea", group="Opis"),
        Param("devizno", "Devizni podaci", "select", ("Ne", "Da"), default="Ne", allow_ref=False, group="Devizno",
              help="„Da“ prikazuje devizna polja (klauzula, valuta, iznosi, kurs)."),
        Param("devizna_klauzula", "Devizna klauzula", "bool", default=False, allow_ref=False, show_if=("devizno", "Da"),
              group="Devizno"),
        Param("devizna_valuta", "Devizna valuta", show_if=("devizno", "Da"), group="Devizno", help="Npr. EUR."),
        Param("vrsta_kursa", "Vrsta kursa", "select", (AS_PROGRAM, *item_form.RATES), default=AS_PROGRAM,
              allow_ref=False, show_if=("devizno", "Da"), group="Devizno"),
        Param("dev_dug", "Dev. dug.", "number", show_if=("devizno", "Da"), group="Devizni iznosi"),
        Param("dev_pot", "Dev. pot.", "number", show_if=("devizno", "Da"), group="Devizni iznosi"),
        Param("kurs", "Kurs", "number", show_if=("devizno", "Da"), group="Devizni iznosi"),
    ),
    output_columns=tuple(n for n, *_ in item_form.FIELDS) + ("Nalog", "Nalog: duguje", "Nalog: potražuje", "Nalog: saldo"),
    column_kinds={**{n: k for n, _, k, _ in item_form.FIELDS if k in ("number", "date")},
                  "Nalog: duguje": "number", "Nalog: potražuje": "number", "Nalog: saldo": "number"},
    returns_rows=False,
)
def create_order_item(ctx: TaskContext, params: dict) -> dict:
    values = {}
    for param, name in ITEM_PARAMS.items():
        value = params.get(param)
        if param in FOREIGN and params.get("devizno") != "Da":
            continue
        if param == "vrsta_kursa" and value == AS_PROGRAM:
            continue
        if param == "devizna_klauzula":
            values[name] = value is True
        elif value not in (None, ""):
            values[name] = value if isinstance(value, (int, float)) else str(value)
    if not str(values.get("Konto") or "").strip():
        raise ValueError("Konto nije zadat.")
    view = app_page.view_name(ctx.driver)
    if view == order_form.VIEW:
        ctx.log("Opening Stavke of the selected order")
        view = app_page.open_link(ctx.driver, "Stavke", exact=True)
    if view != item_form.VIEW:
        raise RuntimeError(f"Nisu otvorene stavke finansijskog naloga (otvoreno je „{view or '?'}“). Pre ovog zadatka "
                           "otvorite nalog i njegove stavke, npr. zadatkom „Ulaz u stavke“.")
    shown = item_form.order_number(ctx.driver)
    wanted = str(params.get("nalog") or "").strip()
    if wanted and not item_form.same_order(shown, wanted):
        raise RuntimeError(f"Otvorene su stavke naloga „{shown}“, a zadat je nalog „{wanted}“.")
    result = item_form.create(ctx.driver, values, log=ctx.log)
    order = result["nalog"]
    row = dict(result["popunjeno"])
    row.update({"Nalog": order.get("Nalog: broj") or shown, "Nalog: duguje": order.get("Nalog: duguje", ""),
                "Nalog: potražuje": order.get("Nalog: potražuje", ""), "Nalog: saldo": order.get("Nalog: saldo", "")})
    ctx.log(f"Item saved: {row}")
    return {"nalog": row["Nalog"], "kolone": list(row), "redovi": [row], "broj": 1}


@task_type(
    "open_items", "Ulaz u stavke",
    "Klikne „Stavke“ na otvorenoj stranici (npr. na finansijskom nalogu) i sačeka stranicu stavki. Njegovi "
    "podzadaci se izvršavaju na toj stranici, a posle njih program sam klikne „Nazad“ ako to nije uradio "
    "zadatak „Nazad“. Vraća naslov i tabele stranice stavki.",
    subtasks_once=True,
)
def open_items(ctx: TaskContext, params: dict) -> dict:
    before = app_page.view_name(ctx.driver)
    ctx.log("Opening Stavke")
    after = app_page.open_link(ctx.driver, "Stavke", exact=True)
    info = app_page.describe_page(ctx.driver)
    ctx.log(f"Stavke: {before} -> {after} ({info['naslov']})")
    # "prikaz_pre": the runner goes back to this page after the subtasks (see runner._descend).
    return {"prikaz_pre": before, "prikaz": after, "otvoreno": info["naslov"], **info}


# Columns of the financial order's items page (FINNALSTAVVIEW, HTML pasted 2026-10-07) and how to compare them.
ITEM_KINDS = {"R.b.": "number", "Datum": "date", "Konto": "text", "Dokument": "text", "Ana. Šif.": "text",
              "Analitika": "text", "Duguje": "number", "Potražuje": "number"}
# Fields of the selected item's form and of the order (pages/items_page.py): reading them clicks every item.
DETAIL_KINDS = {name: kind for name, _, kind, _ in items_page.FORM_FIELDS + items_page.ORDER_FIELDS}


def _item_field(name: str, kind: str, group: str = "") -> dict:
    field = {"id": name, "naziv": f"{group}{name}", "vrsta": kind, "operatori": pages.TEXT_OPS}
    if kind in ("number", "date"):
        field["operatori"] = pages.RANGE_OPS
    elif kind == "bool":
        field.update(operatori=["Jednako", "Različito od"], opcije=["Ne", "Da"])
    elif kind == "list":
        field.update(operatori=pages.LIST_OPS, opcije=list(items_page.LIST_OPTIONS.get(name, ())))
    elif kind == "link":
        field["vrsta"] = "text"
    return field


ITEM_FIELDS = (
    {"id": conditions.ANY_COLUMN, "naziv": "Bilo koja kolona", "vrsta": "text", "operatori": pages.TEXT_OPS},
    *(_item_field(column, kind) for column, kind in ITEM_KINDS.items()),
    *(_item_field(name, kind, "Forma: ") for name, _, kind, _ in items_page.FORM_FIELDS),
    *(_item_field(name, kind) for name, _, kind, _ in items_page.ORDER_FIELDS),
)
# How conditions compare each field (bool / list / link values are compared as text).
COMPARE_KINDS = {**ITEM_KINDS, **{k: (v if v in ("number", "date") else "text") for k, v in DETAIL_KINDS.items()}}


@task_type(
    "search_items", "Pretraga stavki",
    "Na stranici stavki finansijskog naloga (posle zadatka „Ulaz u stavke“) pročita sve stavke i zadrži one koje "
    "ispunjavaju sve uslove (R.b., Datum, Konto, Dokument, Ana. Šif., Analitika, Duguje, Potražuje). Vrednost "
    "uslova se upisuje ili uzima iz ranijih zadataka i podzadataka; ako je to lista vrednosti (svi redovi), "
    "uslov važi kad važi za bilo koju od njih. Uslovi mogu da koriste i polja forme ispod tabele (Datum plaćanja, "
    "Opis, Org. jed., Kurs, …) i polja naloga (Status, Saldo, …): tada program klikne svaku stavku i pročita "
    "formu (sporije). Vraća pronađene stavke i zbir Duguje / Potražuje.",
    (
        Param("filters", "Uslovi", "filters", allow_ref=False, fields=ITEM_FIELDS,
              help="Stavka mora da ispuni sve uslove. Bez uslova vraća sve stavke. Iznosi se porede kao brojevi "
                   "(794,16), datumi kao DD/MM/YYYY, tekst bez obzira na velika slova i kvačice. Polja „Forma: …“ "
                   "se čitaju klikom na svaku stavku."),
        Param("details", "Pročitaj sva polja forme", "bool", default=False, allow_ref=False,
              help="Rezultat sadrži i sva polja forme i naloga za svaku stavku (klik na svaku stavku). Uključuje "
                   "se samo od sebe kad neki uslov koristi ta polja."),
    ),
    output_columns=tuple(ITEM_KINDS),
    totals=("Duguje", "Potražuje"),
    column_kinds={k: v for k, v in COMPARE_KINDS.items() if v in ("number", "date")},
)
def search_items(ctx: TaskContext, params: dict) -> dict:
    driver = ctx.driver
    driver.switch_to.default_content()
    table = main_table(driver)
    columns = [c for c in table.columns if c]
    missing = [c for c in ("Konto", "Duguje", "Potražuje") if c not in columns]
    if missing:
        raise LookupError(f"Ovo nije stranica stavki naloga (nema kolona {', '.join(missing)}; kolone: "
                          f"{', '.join(columns)}). Dodajte „Ulaz u stavke“ pre ovog zadatka.")
    # A text left in the page's "Filter..." field would hide items.
    if any(e.get_attribute("value") for e in driver.find_elements(*app_page.FILTER) if e.is_displayed()):
        ctx.log("Clearing the page's Filter field")
        app_page.apply_filter(driver, table, "")
    all_rows = table.read(0)
    item_count = len(all_rows)
    wanted = [c for c in (params.get("filters") or []) if c.get("polje")]
    ctx.log(f"{len(all_rows)} items; conditions: {'; '.join(map(conditions.describe, wanted)) or 'none'}")
    read_all = params.get("details") is True
    if read_all or any(c["polje"] in DETAIL_KINDS for c in wanted):
        # Form fields are shown only for the selected item: click each one. Unless all fields were asked
        # for, only the items that pass the conditions on the table's own columns are clicked.
        table_only = [c for c in wanted if c["polje"] not in DETAIL_KINDS and c["polje"] != conditions.ANY_COLUMN]
        candidates = all_rows if read_all else [
            r for r in all_rows if all(conditions.matches(r, c, COMPARE_KINDS) for c in table_only)]
        order = items_page.read_order(driver)
        ctx.log(f"Reading the form of {len(candidates)} items (order: {order})")
        for i, row in enumerate(candidates, 1):
            ctx.progress(f"Čitanje forme stavke {i} / {len(candidates)}")
            form, ok = items_page.read_item(driver, row)
            if not ok:
                ctx.log(f"Item R.b. {row.get('R.b.')}: the form did not show this item in time; read what is shown")
            row.update(form)
            row.update(order)
        all_rows = candidates
        columns = [*columns, *(n for n, *_ in items_page.FORM_FIELDS), *(n for n, *_ in items_page.ORDER_FIELDS)]
    rows = [r for r in all_rows if all(conditions.matches(r, c, COMPARE_KINDS) for c in wanted)]

    def total(column: str) -> str:
        return app_page.format_amount(sum(conditions.number(r.get(column, "")) or 0 for r in rows))

    totals = {"Duguje": total("Duguje"), "Potražuje": total("Potražuje")}
    ctx.log(f"{len(rows)} of {len(all_rows)} items match; Duguje {totals['Duguje']}, Potražuje {totals['Potražuje']}")
    return {
        "kolone": columns,
        "redovi": rows,
        "broj": len(rows),
        "ukupno_stavki": item_count,
        "ukupno": totals,
        "uslovi": [conditions.describe(c) for c in wanted],
    }


ALL_CHECKS, ANY_CHECK = "Sve provere moraju da važe", "Dovoljna je jedna provera"
CHECK_KINDS = {"Automatski": "auto", "Tekst": "text", "Broj": "number", "Datum": "date"}
CHECK_OPERATORS = ("Jednako", "Različito od", "Veće od", "Veće ili jednako", "Manje od", "Manje ili jednako", "Između",
                   "Sadrži", "Ne sadrži", "Počinje sa", "Ne počinje sa", "Završava se na", "Ne završava se na",
                   conditions.EMPTY, conditions.NOT_EMPTY)


@task_type(
    "condition", "Uslov",
    "Ako (AKO): proverava vrednosti iz ranijih zadataka i podzadataka (bilo koje polje, kolonu, broj redova ili "
    "ukupan iznos; u podzadatku i trenutni red) operatorima kao u naprednim filterima. Ako je uslov ispunjen, "
    "izvršavaju se zadaci grane „AKO“; ako nije, prva grana „INAČE AKO“ čiji je uslov ispunjen, a ako nijedna "
    "nije, grana „INAČE“. Posle toga posao ide dalje, na zadatak posle uslova.",
    (
        Param("checks", "Provere", "conditions", CHECK_OPERATORS, allow_ref=False,
              help="Leva strana je vrednost iz ranijeg zadatka; „Svi redovi“ = važi ako važi za bilo koji red. "
                   "Desna strana se upisuje ili uzima iz zadatka (lista = bilo koja od vrednosti)."),
        Param("combine", "Kombinovanje", "select", (ALL_CHECKS, ANY_CHECK), default=ALL_CHECKS, allow_ref=False),
    ),
    output_columns=("Grana", "Provera", "Leva vrednost", "Ispunjeno"),
    returns_rows=False,
)
def condition(ctx: TaskContext, params: dict) -> dict:
    checks = [c for c in (params.get("checks") or []) if c.get("operator")]
    if not checks:
        raise ValueError("Dodajte bar jednu proveru.")
    results = []
    for i, check in enumerate(checks, 1):
        operator = check["operator"]
        kind = CHECK_KINDS.get(check.get("vrsta") or "Automatski", "auto")
        how = conditions.explain(check.get("levo"), operator, check.get("vrednost"), check.get("do"), kind)
        ok = how["ok"]
        no_value = operator in (conditions.EMPTY, conditions.NOT_EMPTY)
        text = f"{i}. {conditions.show(check.get('levo'))} {operator}"
        right = ""
        if not no_value:
            right = conditions.show(check.get("vrednost"))
            if operator == "Između":
                right += f" i {conditions.show(check.get('do'))}"
            text += f" {right}"
        results.append({
            "Provera": text,
            "Leva vrednost": conditions.show(check.get("levo")),
            "Ispunjeno": "da" if ok else "ne",
            "Operator": operator,
            "Desna vrednost": right,
            "Poređenje": CHECK_KIND_NAMES.get(how["kind"], "") if not no_value else "",
            "Objašnjenje": _explain_check(how, operator, check.get("do")),
        })
        ctx.log(f"Check {text}: {'met' if ok else 'not met'} ({results[-1]['Objašnjenje']})")
    met = [r["Ispunjeno"] == "da" for r in results]
    ok = any(met) if params.get("combine") == ANY_CHECK else all(met)
    ctx.log(f"Condition {'met' if ok else 'NOT met'}")
    return {
        "uslov": ok,
        "ispunjen": "da" if ok else "ne",
        "kombinovanje": params.get("combine") or ALL_CHECKS,
        "kolone": ["Provera", "Leva vrednost", "Ispunjeno", "Operator", "Desna vrednost", "Poređenje", "Objašnjenje"],
        "redovi": results,
        "broj": len(results),
    }


CHECK_KIND_NAMES = {"number": "kao brojevi", "date": "kao datumi", "text": "kao tekst"}


def _explain_check(how: dict, operator: str, upto=None) -> str:
    """Why a check was (not) met, e.g. "ispunjeno za: '1.578,40' ↔ '1000' · 5 parova, dovoljno je da važi za jedan par"."""
    between = f" i {conditions.show(upto[0] if isinstance(upto, list) and upto else upto)}" if operator == "Između" else ""

    def pairs(items: list) -> str:
        shown = [f"{conditions.show(a)} ↔ {conditions.show(b)}{between}" if b != "" else conditions.show(a) for a, b in items[:3]]
        return "; ".join(shown) + (" …" if len(items) > 3 else "")

    def count(n: int) -> str:
        return f"{n} {'par' if n % 10 == 1 and n % 100 != 11 else 'para' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'parova'}"

    if operator in (conditions.EMPTY, conditions.NOT_EMPTY):
        return how["rule"] + (f" (npr. {pairs(how['matched'])})" if how["matched"] else "")
    negative = operator in conditions.NEGATIVE
    if how["ok"]:
        text = f"važi za sve parove ({count(how['pairs'])})" if negative and how["pairs"] > 1 else f"ispunjeno za: {pairs(how['matched'])}"
    elif negative and how["matched"]:
        text = f"ne važi za: {pairs(how['failed'])}"
    else:
        text = f"nije ispunjeno ni za jedan par: {pairs(how['failed'])}" if how["pairs"] > 1 else f"nije ispunjeno: {pairs(how['failed'])}"
    if how["pairs"] > 1:
        text += f" · {count(how['pairs'])}, {how['rule']}"
    return text


# Where "Nastavi" goes on (the runner acts on it, see runner._continue_signal). EXIT_LOOP is no longer offered
# ("Prekini" does that); old tasks with it are turned into "Prekini" when read (store._migrate).
NEXT_ROW = "Sledeći red"
EXIT_LOOP = "Izađi iz petlje (sledeći zadatak posle petlje)"
JUMP_TO = "Skoči na zadatak…"


# The runner acts on these two by their type (see runner._run_group / runner._run_task).
@task_type(
    "continue", "Nastavi",
    "Kao „continue“: preskače ostatak trenutnog reda petlje i prelazi na sledeći red. Može i da skoči na izabrani "
    "kasniji zadatak u istom redu (zadaci između se preskaču). Obično se stavlja u granu zadatka „Uslov“.",
    (
        Param("mode", "Nastavi sa", "select", (NEXT_ROW, JUMP_TO), default=NEXT_ROW, allow_ref=False),
        Param("target", "Zadatak", "task", allow_ref=False, required=True, show_if=("mode", JUMP_TO),
              help="Jedan od sledećih zadataka (u istoj listi ili posle uslova / stranice u kojoj je ovaj); "
                   "zadaci između se za ovaj red preskaču."),
    ),
)
def continue_(ctx: TaskContext, params: dict) -> None:
    return None


@task_type(
    "break", "Prekini",
    "Kao „break“: izlazi iz petlje u kojoj je (ostali redovi se ne obrađuju) i posao ide dalje, na zadatak posle "
    "petlje. Obično se stavlja u granu zadatka „Uslov“.",
)
def break_(ctx: TaskContext, params: dict) -> None:
    return None


@task_type(
    "stop", "Prekini posao",
    "Prekida ceo posao: sledeći zadaci i redovi se ne izvršavaju. Obično se stavlja u granu zadatka „Uslov“.",
)
def stop(ctx: TaskContext, params: dict) -> None:
    return None


@task_type(
    "back", "Nazad",
    "Klikne dugme „Nazad“ na trenutnoj stranici (npr. sa finansijskog naloga nazad na listu Izlaza) i sačeka "
    "stranicu na koju se vraća.",
)
def back(ctx: TaskContext, params: dict) -> dict:
    before = app_page.view_name(ctx.driver)
    after = app_page.click_back(ctx.driver)
    ctx.log(f"Back: {before} -> {after}")
    return {"sa": before, "na": after, "stranica": app_page.describe_page(ctx.driver)["naslov"]}


@task_type(
    "read_value", "Pročitaj vrednost", "Čita vrednost sa otvorene stranice i vraća je kao rezultat.",
    (Param("label", "Naziv polja ili kolone", required=True),),
    implemented=False,
)
def read_value(ctx: TaskContext, params: dict) -> None:
    raise NotImplementedError


# --- PURS (Poreska uprava, ePorezi) ----------------------------------------------------------------------

@task_type(
    "purs_login", "Prijava na ePorezi",
    "Otvara portal ePorezi Poreske uprave u posebnom pretraživaču za ePorezi i prijavljuje se kvalifikovanim "
    "elektronskim sertifikatom preko programa SmartBox: izabere izdavaoca sertifikata (npr. MUP), klikne „Учитај“, "
    "upiše PIN i klikne „Пријави се“. Na ovom računaru moraju biti pokrenut SmartBox i kartica u čitaču. ePorezi ima "
    "jednu prijavu za ceo program: svi PURS zadaci, stranica PURS i provere izveštaja idu kroz isti red (stranica "
    "PURS, „Red za ePorezi“), pa zadatak čeka svoj red. Dozvolu sajtu da pristupi programu SmartBox program daje sam. "
    "Ako je ePorezi još prijavljen, prijava se preskače (PIN se ne unosi).",
    (
        Param("pin", "PIN kartice", "secret", required=True, allow_ref=False,
              help="Čuva se u Windows Credential Manager-u ovog računara, ne u fajlu poslova i ne u rezultatima. "
                   "Unosi se najviše jednom po pokretanju: pogrešan PIN unet više puta zaključava karticu."),
        Param("izdavalac", "Izdavalac sertifikata", default="Ministarstvo unutrašnjih poslova", allow_ref=False,
              help="Stavka liste izdavalaca („Halcom CA“, „Sertifikaciono telo Pošte“, „Ministarstvo unutrašnjih "
                   "poslova CA“, „Privredna komora Srbije CA“): deo naziva (latinica ili ćirilica), skraćenica (MUP) "
                   "ili redni broj (3)."),
        Param("citac", "Čitač kartice", allow_ref=False,
              help="Samo ako sajt ponudi više čitača: deo naziva. Prazno = jedini čitač."),
    ),
    group=GROUP_PURS,
)
def _purs_call(ctx: TaskContext, kind: str, title: str, run, pib: str = "", firma=None):
    """Run `run(driver, item)` as an item of the PURS queue (one ePorezi session for the whole program, its own
    browser) and wait for it: the job waits for its turn; "Zaustavi" takes it out of the queue or stops it."""
    firma = firma or purs_reports.current_company()
    item = purs_queue.Item(kind, title, run, pib=pib, source=f"Posao „{ctx.job.get('name', '')}“", firma=firma[0],
                           firma_naziv=firma[1])
    try:
        return purs_queue.call(item, cancelled=ctx.cancelled, progress=ctx.progress)
    except purs_queue.Cancelled:
        raise TaskCancelled() from None


def purs_login(ctx: TaskContext, params: dict) -> dict:
    def run(driver, item):
        purs.open_tab(driver)
        value = purs.login(driver, str(params.get("pin") or ""), provider=str(params.get("izdavalac") or ""),
                           terminal=str(params.get("citac") or ""), log=ctx.log, progress=item.progress,
                           check_cancel=item.check_cancel)
        home_status.note_purs(getattr(driver, purs.TAXPAYER_ATTR, None))  # Početna / PURS page
        item.message = "Već prijavljen" if value.get("preskoceno") else "Prijavljen"
        return value
    return _purs_call(ctx, "prijava", "Prijava na ePorezi", run)


@task_type(
    "purs_taxpayer", "Odabir poreskog obveznika",
    "Na portalu ePorezi (posle zadatka „Prijava na ePorezi“) otvori početnu stranicu „/“ (ako već nije na njoj), upiše PIB u pretragu, klikne "
    "„Претрага“ i klikne „Изабери“ kod pronađenog obveznika (red sa tim PIB-om, inače prvi red). Posle toga su "
    "prijave na portalu za tog obveznika. Ako je taj isti PIB već izabran (a sesija je još prijavljena), izbor se "
    "preskače; drugi PIB se uvek bira. Između PURS zadataka ovog posla red za ePorezi može da izabere drugog obveznika "
    "(npr. za proveru tuđih izveštaja): sledeći PURS zadatak ovog posla tada ponovo bira ovog.",
    (
        Param("pib", "PIB",
              help="PIB poreskog obveznika (ili JMBG). Prazno = PIB firme otvorene u TiM ERP-u."),
    ),
    output_columns=("PIB", "Naziv", "Ovlašćenje"),
    returns_rows=False,
    group=GROUP_PURS,
)
def purs_taxpayer(ctx: TaskContext, params: dict) -> dict:
    pib = str(params.get("pib") or "").strip()
    if not pib:
        company = (ui.get_shared("session") or {}).get("company") or {}
        pib = str(company.get("pib") or "").strip()
        if not pib:
            raise ValueError("PIB nije upisan, a PIB firme otvorene u TiM ERP-u nije poznat (firma je izabrana u "
                             "pretraživaču). Upišite PIB u zadatku.")
        ctx.log(f"PIB of the open company {company.get('name', '')}: {pib}")

    def run(driver, item):
        purs.open_tab(driver)
        row = purs.choose_taxpayer(driver, pib, log=ctx.log, progress=item.progress)
        home_status.note_purs({"PIB": row["PIB"], "Naziv": row["Naziv"]})  # Početna / PURS page
        item.message = f"{row['Naziv']} ({row['PIB']})"
        return row
    row = _purs_call(ctx, "obveznik", f"Odabir poreskog obveznika {pib}", run, pib=pib)
    ctx.purs["pib"] = row["PIB"]  # this job's later PURS tasks get this taxpayer back
    return {**row, "kolone": ["PIB", "Naziv", "Ovlašćenje"], "redovi": [{k: row[k] for k in ("PIB", "Naziv", "Ovlašćenje")}],
            "broj": 1}


@task_type(
    "purs_balance", "Upit stanja",
    "Na portalu ePorezi (posle „Prijava na ePorezi“ i „Odabir poreskog obveznika“) otvori „Упит стања“, izabere tip "
    "zahteva (i grupu za analitiku), upiše e-poštu i klikne „Пошаљи захтев за проверу стања“. Vraća ID zahteva sa "
    "sajta (prva kolona tabele, npr. 36445597) za zadatke „Sačekaj izveštaj“ i „Čitanje PDF izveštaja“. Izveštaj se čeka u "
    "pozadini (posao ide dalje): kad se u prvom redu tabele pojavi link „Извештај“, program preuzme dokument; vidi se "
    "na stranici „PURS“ (i obaveštenje kad stigne). Zahtev se šalje za obveznika izabranog u ovom poslu (inače za PIB "
    "firme otvorene u TiM ERP-u).",
    (
        Param("vrsta", "Tip zahteva", "select", tuple(purs.BALANCE_TYPES), default="Sintetika u PDF formatu",
              allow_ref=False, required=True),
        Param("grupa", "Grupa", "select", tuple(purs.BALANCE_GROUPS), default="PDV – Porez na dodatu vrednost",
              allow_ref=False, show_if=("vrsta", purs.ANALYTICAL)),
        Param("email", "Elektronska pošta",
              help="Sajt je traži. Prazno = kako sajt ponudi (ako je polje na sajtu prazno, zadatak javlja grešku)."),
        Param("cekaj", "Sačekaj izveštaj u poslu", "bool", default=False, allow_ref=False,
              help="Da: posao čeka da izveštaj stigne (npr. kad ga sledeći zadaci koriste). Ne: posao odmah ide dalje, "
                   "izveštaj stiže u pozadini."),
    ),
    output_columns=("ID zahteva", "Tip zahteva", "Grupa", "PIB", "Status", "Fajl"),
    returns_rows=False,
    group=GROUP_PURS,
)
def purs_balance(ctx: TaskContext, params: dict) -> dict:
    kind = str(params.get("vrsta") or "")
    group = str(params.get("grupa") or "") if kind == purs.ANALYTICAL else ""
    # The taxpayer: the one this job chose, else the open company's (another item may have chosen another one).
    pib = ctx.purs.get("pib") or str(((ui.get_shared("session") or {}).get("company") or {}).get("pib") or "")
    if pib:
        ctx.log(f"ePorezi taxpayer for this request: {pib}")
    firma = purs_reports.current_company()

    def run(driver, item):
        out = purs_balance_mod.request(driver, kind, group, str(params.get("email") or ""), log=ctx.log,
                                       progress=item.progress, check_cancel=item.check_cancel,
                                       job_name=ctx.job.get("name", ""), firma=firma)
        item.message = (f"Današnji izveštaj ID {out['request'].get('sajt_id')} već postoji" if out["reused"]
                        else f"Poslat, ID {out['request'].get('sajt_id') or '—'}")
        return out
    title = f"Upit stanja: {kind}" + (f" · {group.split(' – ')[0]}" if group else "")
    out = _purs_call(ctx, "zahtev", title, run, pib=pib, firma=firma)
    request, done, sent, reused, today = out["request"], out["done"], out["sent"], out["reused"], out["today"]
    if params.get("cekaj") is True and done is not None:
        while not done.wait(1):
            if ctx.cancelled():
                raise TaskCancelled("Zaustavljeno; izveštaj se i dalje čeka u pozadini (stranica PURS).")
            entry = purs_reports.get(request["id"])
            ctx.progress(f"Čeka se izveštaj ({entry.get('provera_broj', 0)}. provera)")
    entry = purs_reports.get(request["id"])
    if entry.get("status") == purs_reports.FAILED:
        raise RuntimeError(f"Izveštaj nije preuzet: {entry.get('greska')}")
    status = {purs_reports.WAITING: "čeka se (u pozadini)", purs_reports.DONE: "preuzet"}.get(entry["status"],
                                                                                              entry["status"])
    if reused:
        status += " (današnji, već postojao)"
    row = {"ID zahteva": entry.get("sajt_id") or sent["id"], "Tip zahteva": kind, "Grupa": group, "PIB": entry.get("PIB", ""),
           "Status": status, "Fajl": f"/files/purs/{entry['fajl']}" if entry.get("fajl") else ""}
    return {**row, "zahtev": request["id"], "red_na_sajtu": sent["red"] or (today or {}).get("red", {}),
            "kolone": list(row), "redovi": [row], "broj": 1, "vec_postojao": reused,
            **({"poruka_sajta": sent["poruka"]} if sent.get("poruka") else {})}


def _purs_request(ctx: TaskContext, given: str) -> dict:
    """The "Upit stanja" request for a task: the given ID (of the site, e.g. 36445597), else the one sent last in this
    job, else the newest one."""
    given = str(given or "").strip()
    if given:
        entry = purs_reports.find(given)
        return entry or {"sajt_id": given}
    for value in reversed(list(ctx.outputs.values())):
        if isinstance(value, dict) and value.get("zahtev") and "ID zahteva" in value:
            entry = purs_reports.get(value["zahtev"])
            if entry:
                ctx.log(f"Request of this job's Upit stanja: {entry.get('sajt_id') or entry['id']}")
                return entry
    requests = purs_reports.company_requests()
    if not requests:
        raise ValueError("Ova firma nema poslatih zahteva „Upit stanja“: upišite ID zahteva.")
    ctx.log(f"Newest request: {requests[0].get('sajt_id') or requests[0]['id']}")
    return requests[0]


def _purs_value(entry: dict) -> dict:
    row = {"ID zahteva": entry.get("sajt_id", ""), "Tip zahteva": entry.get("Tip zahteva", ""), "Grupa": entry.get("Grupa", ""),
           "PIB": entry.get("PIB", ""), "Status": entry.get("status", ""),
           "Fajl": f"/files/purs/{entry['fajl']}" if entry.get("fajl") else ""}
    return {**row, "zahtev": entry.get("id", ""), "kolone": list(row), "redovi": [row], "broj": 1}


ID_HELP = ("ID zahteva sa ePoreza (prva kolona tabele „Упит стања“, npr. 36445597), npr. „ID zahteva“ iz zadatka „Upit "
           "stanja“. Prazno = zahtev poslat poslednjim „Upit stanja“ u ovom poslu, inače najnoviji zahtev ove firme.")


@task_type(
    "purs_wait", "Sačekaj izveštaj",
    "Čeka da stigne izveštaj zahteva „Upit stanja“ (sa datim ID-jem) i da ga program preuzme. Ako je već preuzet, odmah "
    "ide dalje. Ako se zahtev više ne prati (npr. program je u međuvremenu ponovo pokrenut, ili je zahtev poslat ručno na "
    "ePorezima), ponovo ga prati po ID-ju u tabeli „Упит стања“ (treba da je izabran isti poreski obveznik).",
    (
        Param("zahtev", "ID zahteva", help=ID_HELP),
        Param("minuta", "Najduže čekanje (minuta)", "number", default="120",
              help="Posle toga zadatak javlja grešku (izveštaj može da stigne i kasnije; vidi stranicu PURS)."),
    ),
    output_columns=("ID zahteva", "Tip zahteva", "Grupa", "PIB", "Status", "Fajl"),
    returns_rows=False,
    group=GROUP_PURS,
)
def purs_wait(ctx: TaskContext, params: dict) -> dict:
    entry = _purs_request(ctx, params.get("zahtev"))
    try:
        minutes = float(str(params.get("minuta") or "120").replace(",", "."))
    except ValueError:
        raise ValueError("„Najduže čekanje“ nije broj.") from None
    if entry.get("status") == purs_reports.DONE and entry.get("fajl"):
        ctx.log(f"Report {entry.get('sajt_id')} already downloaded: {entry['fajl']}")
        return _purs_value(entry)
    event = purs_reports.waiting(entry["id"]) if entry.get("id") else None
    if event is None:  # not watched (any more): watch it again, by its ID in the table
        site_id = entry.get("sajt_id", "")
        if not site_id:
            raise ValueError("Zahtev nema ID sa sajta, pa se ne može ponovo pratiti.")
        if not entry.get("id"):  # sent by hand: the taxpayer this job chose, else the open company's
            company = (ui.get_shared("session") or {}).get("company") or {}
            pib = ctx.purs.get("pib") or str(company.get("pib") or "")
            entry = purs_reports.add({"Tip zahteva": "", "Grupa": "", "kod": f"zahtev-{site_id}", "sajt_id": site_id,
                                      "PIB": pib, "Naziv": company.get("name", "") if pib == company.get("pib") else "",
                                      "posao": ctx.job.get("name", "")})
        else:
            purs_reports._update(entry["id"], status=purs_reports.WAITING, greska="")
        ctx.log(f"Watching request {site_id} again (checked in the PURS queue)")
        event = purs_reports.watch(entry["id"], site_id=site_id)
    deadline = time.monotonic() + minutes * 60
    while not event.wait(1):
        if ctx.cancelled():
            raise TaskCancelled("Zaustavljeno; izveštaj se i dalje čeka u pozadini (stranica PURS, „Prekini čekanje“).")
        current = purs_reports.get(entry["id"])
        ctx.progress(f"Čeka se izveštaj {current.get('sajt_id', '')} ({current.get('provera_broj', 0)}. provera)")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Izveštaj nije stigao za {minutes:g} min (i dalje se čeka u pozadini; vidi stranicu PURS).")
    entry = purs_reports.get(entry["id"])
    if entry.get("status") != purs_reports.DONE:
        raise RuntimeError(f"Izveštaj nije preuzet: {entry.get('greska') or entry.get('status')}")
    ctx.log(f"Report {entry.get('sajt_id')} downloaded: {entry['fajl']}")
    return _purs_value(entry)


@task_type(
    "purs_read_pdf", "Čitanje PDF izveštaja",
    "Čita ceo preuzeti PDF izveštaj zahteva „Upit stanja“ (sa datim ID-jem): tekst svake strane, redove teksta i tabele "
    "koje se u PDF-u prepoznaju. Izveštaj mora već da bude preuzet (stavite pre ovoga „Sačekaj izveštaj“). Redovi "
    "rezultata su redovi teksta (Strana, Red, Tekst); tabele su u vrednosti „tabele“.",
    (
        Param("zahtev", "ID zahteva", help=ID_HELP),
    ),
    output_columns=("Strana", "Red", "Tekst"),
    column_kinds={"Strana": "number", "Red": "number"},
    group=GROUP_PURS,
)
def purs_read_pdf(ctx: TaskContext, params: dict) -> dict:
    entry = _purs_request(ctx, params.get("zahtev"))
    if not entry.get("fajl"):
        state = {purs_reports.WAITING: "još se čeka"}.get(entry.get("status", ""), entry.get("status") or "nepoznat")
        raise ValueError(f"Izveštaj zahteva {entry.get('sajt_id') or entry.get('id', '')} nije preuzet ({state}). "
                         "Stavite pre ovog zadatka „Sačekaj izveštaj“.")
    path = purs_reports.FILES_DIR / entry["fajl"]
    if not path.is_file():
        raise ValueError(f"Fajl {entry['fajl']} više ne postoji.")
    ctx.log(f"Reading {path}")
    value = purs_pdf.read(path)
    ctx.log(f"PDF: {value['broj_strana']} pages, {value['broj']} lines, {len(value['tabele'])} tables")
    return {**value, "ID zahteva": entry.get("sajt_id", ""), "Tip zahteva": entry.get("Tip zahteva", ""),
            "PIB": entry.get("PIB", ""), "Fajl": f"/files/purs/{entry['fajl']}"}


# --- D Express ----------------------------------------------------------------------------------------------------

@task_type(
    "dexpress_grouped_payment", "Grupisana uplata (D Express)",
    "Otvara stranicu „Grupisana uplata“ kurirske službe D Express (usersupport.dexpress.rs/ExternalApi/GP) u posebnom "
    "prozoru, upiše broj računa i poziv na broj sa primljene uplate, klikne „Pogledaj“ i vrati sve pošiljke te uplate: "
    "datum uplate, šifru pošiljke, otkupninu (BuyOut) i primaoca. Redove i ukupnu otkupninu mogu da koriste sledeći "
    "zadaci (npr. Petlja, Pravljenje stavke). Posle toga se vraća na prozor TiM ERP-a.",
    (
        Param("poziv", "Poziv na broj", required=True, row_column="Poziv na broj",
              help="Poziv na broj sa primljene uplate. Može da se uzme iz ranijeg zadatka („Iz zadatka“, ili vrednost "
                   "npr. $2.Poziv na broj$); u petlji ili podzadatku prazno = kolona „Poziv na broj“ trenutnog reda."),
        Param("racun", "Broj računa", default=dexpress.ACCOUNT, help="Vaš broj računa kod D Express-a."),
    ),
    output_columns=dexpress.COLUMNS,
    totals=("BuyOut",),
    column_kinds={"PaymentDate": "date", "BuyOut": "number"},
    group=GROUP_DEXPRESS,
)
def dexpress_grouped_payment(ctx: TaskContext, params: dict) -> dict:
    value = dexpress.grouped_payment(ctx.driver, params.get("poziv"), params.get("racun") or dexpress.ACCOUNT, ctx.log)
    ctx.log(f"D Express: {value['broj']} parcels, BuyOut total {value['ukupno']['BuyOut']}")
    return value
