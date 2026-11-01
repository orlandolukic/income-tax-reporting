"""ePorezi "Упит стања" requests: waiting for the report and keeping the downloaded files.

The request is sent from the PURS queue (purs_balance, purs_queue), which then calls `watch`. Waiting is no thread of
its own: the queue checks the waiting requests one taxpayer at a time (`due_checks`, `check_round`: the taxpayer is
chosen, "Упит стања" loaded once in a hidden background tab of the ePorezi browser over the DevTools protocol, every
waiting request of that taxpayer looked up in it), POLL s after that taxpayer's last check, taking turns with the
other items of the queue. A ready report is downloaded with fetch() inside that tab and saved in data/purs/. Every
change is published to the page (shared "purs"), which shows a notice when a report is ready; the files are served at
/files/purs/<name>. Logged out: the requests show "čeka se prijava na ePorezi" and are checked again after a login.

The site's request ID is the first column of the table (e.g. 36445597, `sajt_id`): the watcher follows the row with
that ID (else the first row, with a link that wasn't there before sending).

Requests: data/purs/zahtevi.json, newest first, REQUESTS_KEPT kept per company (older files deleted). A request still
waiting when the program stopped is marked "prekinuto" on the next start.

Each company open in TiM (key `main.company_key`, set with `set_company`) has its own requests: a request carries the
company it was sent from (`firma`, `firma_naziv`); the page, the tasks ("Sačekaj izveštaj" / "Čitanje PDF izveštaja"
without an ID = the newest of this company) and deleting only see the open company's. A watcher keeps going after the
company is changed. Requests saved before this belong to the first company opened."""
import base64
import json
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import websocket

from tim_automation import screen, ui

FILES_DIR = Path("data") / "purs"
REQUESTS_FILE = FILES_DIR / "zahtevi.json"
REQUESTS_KEPT = 50
POLL = 5  # seconds between refreshes of the requests table (the user: every 5 s)
NEW_ROW_WAIT = 180  # a request that never shows up in the table: the site did not take it
MAX_WAIT = 3 * 3600  # give up after this long
LOAD_TIMEOUT = 45

WAITING, DONE, FAILED, STOPPED = "ceka", "gotovo", "greska", "prekinuto"

_lock = threading.Lock()
_done_events: dict[str, threading.Event] = {}
_watches: dict[str, dict] = {}  # request id -> what its checks need (see watch)
_company: str | None = None  # key of the company open in TiM (None: none, no requests shown)
_label = ""

# The requests table on "Упит стања": the first table after the send button, its first data row, the visible cells
# and the link in the last visible cell (the report, e.g. <a href="/sw4i/upstaGetOld484/90721622">Извештај</a>).
FIRST_ROW_JS = r"""
(() => {
  const send = [...document.querySelectorAll('button, input[type=submit]')]
    .find((b) => /Пошаљи захтев|Posalji zahtev|Pošalji zahtev/i.test(b.value || b.textContent || ''));
  const after = (el) => !send || (send.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const shown = (el) => el.offsetParent !== null || el.getClientRects().length > 0;
  const tables = [...document.querySelectorAll('table')].filter(after);
  for (const table of tables) {
    const rows = [...table.querySelectorAll('tr')].filter((tr) => tr.querySelector('td'));
    if (!rows.length) continue;
    const heads = [...table.querySelectorAll('tr th')].filter(shown).map((th) => th.innerText.trim());
    const cells = [...rows[0].querySelectorAll('td')].filter(shown);
    const read = (tr) => {
      const cells = [...tr.querySelectorAll('td')].filter(shown);
      const last = cells[cells.length - 1];
      const link = last && last.querySelector('a[href]');
      return {cells: cells.map((td) => td.innerText.trim()), href: link ? link.href : '',
              linkText: link ? link.innerText.trim() : ''};
    };
    const all = rows.map(read);
    return {heads, ...all[0], rows: rows.length, all};
  }
  return {heads: [], cells: [], href: '', linkText: '', rows: 0, all: []};
})()
"""

DOWNLOAD_JS = r"""
(async (href) => {
  const r = await fetch(href, {credentials: 'include'});
  const bytes = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
  return {status: r.status, type: r.headers.get('content-type') || '', disposition:
          r.headers.get('content-disposition') || '', url: r.url, data: btoa(s)};
})(%s)
"""


# --- requests list -------------------------------------------------------------------------------------------------

def _read() -> list[dict]:
    try:
        data = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _unlink_unused(gone: list[dict], kept: list[dict]) -> None:
    """Delete the files of removed requests that no kept request uses (a report reused by a later request is shared)."""
    used = {r.get("fajl") for r in kept}
    for old in gone:
        if old.get("fajl") and old["fajl"] not in used:
            (FILES_DIR / old["fajl"]).unlink(missing_ok=True)


def _write(requests: list[dict]) -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    kept, dropped, counts = [], [], {}
    for r in requests:
        counts[r.get("firma")] = counts.get(r.get("firma"), 0) + 1
        (kept if counts[r.get("firma")] <= REQUESTS_KEPT else dropped).append(r)
    _unlink_unused(dropped, kept)
    REQUESTS_FILE.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")


def _mine(requests: list[dict], firma: str | None = None) -> list[dict]:
    """The requests of the company open now (or of `firma`)."""
    firma = _company if firma is None else firma
    return [r for r in requests if firma is not None and r.get("firma") == firma]


def _publish(requests: list[dict] | None = None) -> None:
    mine = _mine(_read() if requests is None else requests)[:REQUESTS_KEPT]
    ui.set_shared("purs", {"firma": _label if _company is not None else None, "zahtevi": mine})


def set_company(key: str | None, label: str = "") -> None:
    """Show and use the requests of this company from now on (None: no company is open)."""
    global _company, _label
    with _lock:
        _company, _label = key, label
        if key is not None:
            requests = _read()
            old = [r for r in requests if "firma" not in r]
            if old:  # saved before requests were kept per company
                for r in old:
                    r.update(firma=key, firma_naziv=label)
                _write(requests)
                print(f"PURS requests saved before they were kept per company now belong to {label or key}.")
    _publish()


def company_requests(firma: str | None = None) -> list[dict]:
    """The open company's (or `firma`'s) requests, newest first."""
    return [dict(r) for r in _mine(_read(), firma)]


def current_company() -> tuple[str | None, str]:
    """(key, label) of the company open in TiM now: what a request queued now belongs to."""
    return _company, _label


def _update(request_id: str, **changes) -> dict:
    with _lock:
        requests = _read()
        entry = next((r for r in requests if r["id"] == request_id), None)
        if entry is None:
            return {}
        entry.update(changes)
        _write(requests)
    _publish(requests)
    return dict(entry)


def get(request_id: str) -> dict:
    return next((dict(r) for r in _read() if r["id"] == request_id), {})


def find(site_id: str, firma: str | None = None) -> dict:
    """The open company's (or `firma`'s) newest request with this ID of the site (or our own id)."""
    site_id = str(site_id or "").strip()
    return next((r for r in company_requests(firma) if site_id and site_id in (r.get("sajt_id"), r["id"])), {})


def downloaded(site_id: str, exclude: str = "") -> dict:
    """A request of this site ID whose report is already saved here (any company: same ePorezi request = same file)."""
    site_id = str(site_id or "").strip()
    return next((dict(r) for r in _read() if site_id and r.get("sajt_id") == site_id and r["id"] != exclude
                 and r.get("fajl") and (FILES_DIR / r["fajl"]).is_file()), {})


def waiting(request_id: str) -> threading.Event | None:
    """The event of a watcher that is still waiting for this request, if any."""
    return _done_events.get(request_id)


def setup() -> None:
    """At program start: serve the files, mark requests left waiting by an earlier run, publish the list."""
    ui.register_files("purs", FILES_DIR)
    ui.register_api("purs", _api)
    with _lock:
        requests = _read()
        for r in requests:
            if r.get("status") == WAITING and r["id"] not in _done_events:
                r.update(status=STOPPED, greska="Program je zatvoren pre nego što je izveštaj stigao.")
        if requests:
            _write(requests)
    _publish(requests)


def debugger_address(driver) -> str:
    """host:port of the browser's DevTools (Chrome / Edge), "" if there is none."""
    caps = driver.capabilities
    return (caps.get("goog:chromeOptions") or caps.get("ms:edgeOptions") or {}).get("debuggerAddress", "")


def check(request_id: str) -> None:
    """"Proveri sada" on the PURS page: wait for the request again (by its ID): the PURS queue checks it in its
    taxpayer's rounds and downloads the report when its row has the link. For requests no longer waited for, e.g.
    after the program was restarted (ePorezi must be logged in again; the queue chooses the taxpayer)."""
    entry = next((r for r in company_requests() if r["id"] == request_id), None)
    if entry is None:
        raise ValueError("Zahtev nije pronađen među zahtevima ove firme.")
    if request_id in _done_events:
        raise ValueError("Ovaj zahtev se već proverava (svakih 5 s).")
    if not entry.get("sajt_id"):
        raise ValueError("Zahtev nema ID sa ePoreza, pa ne može da se pronađe u tabeli „Упит стања“.")
    _update(request_id, status=WAITING, greska="", status_tekst="zakazano u redu za ePorezi")
    print(f"PURS: checking request {entry['sajt_id']} again (asked on the PURS page)")
    watch(request_id, site_id=entry["sajt_id"])


def use_existing(site_id: str, kind: str, group: str = "") -> dict:
    """A report already made on ePorezi, by its request ID (first column of "Упит стања"), instead of a new request:
    the one saved here if there is one, else it is recorded and downloaded once by the watcher (ePorezi must be logged
    in with this company's taxpayer chosen). Nothing is sent to ePorezi."""
    from tim_automation import ui as _ui
    from tim_automation.pages import purs
    site_id = "".join(str(site_id or "").split())
    if not site_id.isdigit():
        raise ValueError("Upišite ID zahteva sa ePoreza (samo cifre, npr. 36452606).")
    entry = find(site_id)
    if entry:
        if entry.get("status") == DONE and entry.get("fajl"):
            return entry
        if entry["id"] not in _done_events:
            check(entry["id"])
        return get(entry["id"])
    same = downloaded(site_id)  # saved for another company (same ePorezi request)
    company = (_ui.get_shared("session") or {}).get("company") or {}
    group = group if kind == purs.ANALYTICAL else ""
    kod = purs.BALANCE_TYPES[kind][1] + (f"-{purs.BALANCE_GROUPS[group]}" if group else "") if kind in purs.BALANCE_TYPES else ""
    entry = add({"Tip zahteva": kind, "Grupa": group, "kod": kod, "sajt_id": site_id, "PIB": company.get("pib", ""),
                 "Naziv": company.get("name", ""), "posao": "Stranica PURS (postojeći izveštaj)",
                 "napomena": "Dodat po ID-ju postojećeg izveštaja (zahtev nije poslat)."})
    if same:
        return _update(entry["id"], status=DONE, fajl=same["fajl"], velicina=same.get("velicina"),
                       vrsta_fajla=same.get("vrsta_fajla", ""), red=same.get("red") or {}, zavrseno=time.time())
    print(f"PURS: using the existing report {site_id} ({kind}) instead of a new request")
    check(entry["id"])
    return get(entry["id"])


_parsed: dict[tuple, dict] = {}  # (file, mtime) -> parsed analytical report


def _report_file(body: dict) -> tuple[dict, Path]:
    entry = next((r for r in company_requests() if r["id"] == str(body.get("id"))), None)
    if entry is None:
        raise ValueError("Zahtev nije pronađen među zahtevima ove firme.")
    if not entry.get("fajl") or not (FILES_DIR / entry["fajl"]).is_file():
        raise ValueError("Izveštaj ovog zahteva nije preuzet.")
    if not entry["fajl"].lower().endswith(".pdf"):
        raise ValueError(f"Izveštaj nije PDF ({entry['fajl']}).")
    return entry, FILES_DIR / entry["fajl"]


def _cached(module, path: Path) -> dict:
    key = (module.__name__, str(path), path.stat().st_mtime)
    if key not in _parsed:
        _parsed[key] = module.parse(path)
    return _parsed[key]


def site_date(entry: dict) -> str:
    """The day the request was made on ePorezi (YYYY-MM-DD) from its row in the requests table ("Време слања упита"
    2026-10-13 10:53:37.0 / "Датум захтева" 13.10.2026 ...), "" if the row doesn't show it."""
    row = entry.get("red") or {}
    for key, value in row.items():
        k = key.lower()
        if not ("слањ" in k or "датум" in k or "datum" in k or "slanj" in k):
            continue
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value or "")
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value or "")
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


SYNTHETIC_KODS = ("sintetika",)  # "Sintetika u PDF formatu" (the XML order "nalog-xml" is not a PDF)

# A first guess of the fiscal group whose analytical report holds an account (the user can pick another); accounts seen
# in a downloaded analytical report are known exactly.
# Konto "4" = "Objedinjena naplata poreza i doprinosa" (real synthetic report); payroll taxes and contributions are paid
# through it too.
GROUP_GUESS = (("711211", "PDP"), ("4", "PID"), ("7111", "PID"), ("7121", "PID"), ("7211", "PID"), ("7212", "PID"),
               ("7213", "PID"), ("7813", "PID"), ("7112", "PPSD"), ("7141", "PDV"), ("7145", "AKC"), ("7133", "PNP"),
               ("7134", "OST"))


def state() -> dict:
    """The open company's state at the tax office: the newest synthetic report (accounts summed per Račun), a synthetic
    request still waited for, and for every account the analytical values of each downloaded analytical report."""
    from tim_automation import purs_analytics, purs_synthetic
    requests = company_requests()
    synthetic = [r for r in requests if r.get("kod") in SYNTHETIC_KODS or r.get("Tip zahteva") == "Sintetika u PDF formatu"]
    done = next((r for r in synthetic if r.get("status") == DONE and r.get("fajl")
                 and (FILES_DIR / r["fajl"]).is_file()), None)
    waiting_one = next((r for r in synthetic if r.get("status") == WAITING), None)
    out: dict = {"sintetika": None, "ceka": waiting_one, "analitika": {}, "grupe": {}}
    shown_type = " ".join(v for k, v in ((done or {}).get("red") or {}).items() if "тип" in k.lower() or "tip" in k.lower())
    if done and (not done["fajl"].lower().endswith(".pdf") or re.search(r"аналит|analit|analyt", shown_type, re.I)):
        # e.g. an ID typed by hand that is not a synthetic PDF report
        out["sintetika"] = {"zahtev": done, "greska": f"izveštaj ID {done.get('sajt_id')} nije sintetika u PDF formatu"
                            + (f" (na ePorezima: {shown_type})" if shown_type else f" ({done['fajl']})")}
        done = None
    for r in requests:  # analytical reports, newest first
        if r.get("status") != DONE or groupless(r) or not r.get("fajl", "").lower().endswith(".pdf"):
            continue
        path = FILES_DIR / r["fajl"]
        if not path.is_file():
            continue
        try:
            report = _cached(purs_analytics, path)
        except Exception:
            continue
        code = (r.get("Grupa") or "").split(" – ")[0] or (r.get("kod") or "").removeprefix("analitika-")
        for g in report["pozivi"]:
            out["grupe"].setdefault(g["racun"], code)
            per = out["analitika"].setdefault(g["racun"], {})
            entry = per.setdefault(r["id"], {"zahtev": r["id"], "sajt_id": r.get("sajt_id", ""), "grupa": code,
                                             "stanje_na_dan": report["zaglavlje"].get("stanje_na_dan", ""),
                                             "poslato": r.get("poslato"), "pozivi": []})
            entry["pozivi"].append({"poziv_na_broj": g["poziv_na_broj"], "opstina": g["opstina"],
                                    "opis_racuna": g["opis_racuna"], "stavki": len(g["stavke"]), "stanje": g["stanje"],
                                    "slaze": g["provera"]["slaze"]})
    by_poziv: dict[tuple, list] = {}  # (konto, poziv na broj) -> its analytical entries (newest report first)
    for konto, reports in out["analitika"].items():
        for rep_ in reports.values():
            for p in rep_["pozivi"]:
                by_poziv.setdefault((konto, p["poziv_na_broj"]), []).append(
                    {"zahtev": rep_["zahtev"], "sajt_id": rep_["sajt_id"], "grupa": rep_["grupa"],
                     "ukupan_dug": (p["stanje"] or {}).get("ukupan_dug"), "stavki": p["stavki"]})
    if done:
        today = time.strftime("%Y-%m-%d")
        when = done.get("zavrseno") or done.get("poslato") or 0
        try:
            report = _cached(purs_synthetic, FILES_DIR / done["fajl"])
            accounts: dict[str, dict] = {}
            for row in report["racuni"]:  # grouped by konto: its rows are its Pozivi na broj / opštine
                acc = accounts.setdefault(row["konto"], {"racun": row["konto"], "opis": row["opis"], "grupa": row["grupa"],
                                                         "vrednosti": {}, "redova": 0, "pozivi": []})
                acc["redova"] += 1
                for k, v in row["vrednosti"].items():
                    acc["vrednosti"][k] = round((acc["vrednosti"].get(k) or 0) + (v or 0), 2)
                linked = by_poziv.get((row["konto"], row["poziv_na_broj"]), []) if row["poziv_na_broj"] else []
                acc["pozivi"].append({k: row[k] for k in ("poziv_na_broj", "izvor", "sifra_opstine", "opstina",
                                                          "datum_stanja", "vrednosti")} | {"analitika": linked})
            out["sintetika"] = {"zahtev": done, "danas": (site_date(done) or time.strftime("%Y-%m-%d", time.localtime(
                done.get("poslato") or when))) == today, "zaglavlje": report["zaglavlje"], "kolone": report["kolone"],
                "racuni": list(accounts.values()), "ukupno": report["ukupno"],
                "ukupno_izvestaj": report["ukupno_izvestaj"], "provera": report["provera"]}
        except Exception as e:
            out["sintetika"] = {"zahtev": done, "greska": str(e).splitlines()[0] if str(e) else type(e).__name__}
    out["analitika"] = {k: list(v.values()) for k, v in out["analitika"].items()}
    for acc in (out["sintetika"] or {}).get("racuni", []):
        if acc["racun"] not in out["grupe"]:
            shown = (acc.get("grupa") or "").upper()
            out["grupe"][acc["racun"]] = next((c for c in GROUP_CODES if c in shown.split()), "") or next(
                (code for prefix, code in GROUP_GUESS if acc["racun"].startswith(prefix)), "")
    return out


GROUP_CODES = ("AKC", "OST", "PDP", "PDV", "PID", "PNP", "PPAP", "PPFL", "PPSD", "PRO", "SPID")


def groupless(r: dict) -> bool:
    """Not an analytical request."""
    return not (r.get("kod", "").startswith("analitika") or "Analitika" in (r.get("Tip zahteva") or ""))


def _api(action: str, body: dict):
    if action == "stanje":
        return state()
    if action == "postojeci":  # an existing report by its ePorezi ID instead of a new request
        return use_existing(str(body.get("sajt_id") or ""), str(body.get("vrsta") or "Sintetika u PDF formatu"),
                            str(body.get("grupa") or ""))
    if action == "analitika":  # "Knjiženje": the analytical report by Poziv na broj
        from tim_automation import purs_analytics
        entry, path = _report_file(body)
        return {"zahtev": entry, "izvestaj": _cached(purs_analytics, path)}
    if action == "sadrzaj":  # any other PDF (synthetic): text and tables per page
        from tim_automation import purs_pdf
        entry, path = _report_file(body)
        value = purs_pdf.read(path)
        return {"zahtev": entry, "sadrzaj": {k: value[k] for k in ("broj_strana", "strane", "tabele")}}
    if action == "check":
        check(str(body.get("id")))
        return None
    if action == "stop":
        stop(str(body.get("id")))
        return None
    if action == "delete":
        with _lock:
            requests = _read()
            gone = [r for r in _mine(requests) if r["id"] == body.get("id")]
            if not gone:
                raise ValueError("Zahtev nije pronađen među zahtevima ove firme.")
            if any(r.get("status") == WAITING for r in gone):
                raise ValueError("Izveštaj se još čeka.")
            requests = [r for r in requests if r["id"] != body.get("id")]
            _unlink_unused(gone, requests)
            _write(requests)
        _publish(requests)
        return None
    raise ValueError(f"Nepoznata akcija: {action}")


# --- DevTools ------------------------------------------------------------------------------------------------------

class _Cdp:
    def __init__(self, url: str) -> None:
        self.ws = websocket.create_connection(url, timeout=60, suppress_origin=True)
        self.next_id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error'].get('message')}")
                return message.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def evaluate(self, expression: str, timeout: float = 60):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": True}, timeout)
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description")
                               or result["exceptionDetails"].get("text", "JavaScript error"))
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def _browser_ws(debugger: str) -> str:
    with urllib.request.urlopen(f"http://{debugger}/json/version", timeout=15) as response:
        return json.load(response)["webSocketDebuggerUrl"]


# --- watching ------------------------------------------------------------------------------------------------------

def add(request: dict, firma: tuple[str | None, str] | None = None) -> dict:
    """Record a sent request (status "ceka") of the open company (or `firma` = (key, label)). Returns it with its id."""
    key, label = firma or (_company, _label)
    entry = {"id": uuid.uuid4().hex[:12], "status": WAITING, "poslato": time.time(), "fajl": "", "greska": "",
             "firma": key, "firma_naziv": label, **request}
    with _lock:
        requests = _read()
        requests.insert(0, entry)
        _write(requests)
    _publish(requests)
    return entry


def watch(request_id: str, old_href: str = "", site_id: str = "", before_ids: list[str] | None = None,
          pib: str | None = None) -> threading.Event:
    """Wait for the report of this request: from now on the PURS queue checks it in the rounds of its taxpayer (`pib`,
    default the request's PIB). The event is set when waiting ended (done or not)."""
    from tim_automation import purs_queue
    with _lock:
        if request_id in _watches:
            return _watches[request_id]["event"]
        event = threading.Event()
        entry = next((r for r in _read() if r["id"] == request_id), {})
        _watches[request_id] = {"event": event, "stop": False, "old_href": old_href, "site_id": site_id,
                                "before_ids": before_ids, "started": time.monotonic(), "checks": 0, "missing": 0,
                                "pib": entry.get("PIB", "") if pib is None else pib, "naziv": entry.get("Naziv", "")}
        _done_events[request_id] = event
    purs_queue.wake()
    purs_queue.publish()
    return event


def due_checks() -> dict[str, dict]:
    """The requests waited for, per taxpayer PIB: {pib: {"naziv", "zahtevi": [site ID or our id]}}."""
    out: dict[str, dict] = {}
    with _lock:
        for request_id, w in _watches.items():
            if w["stop"]:
                continue
            group = out.setdefault(w["pib"], {"naziv": w["naziv"], "zahtevi": []})
            group["zahtevi"].append(w["site_id"] or request_id)
    return out


def stop(request_id: str) -> None:
    """"Prekini čekanje": no more checks for this request."""
    with _lock:
        w = _watches.get(request_id)
        if w is None:
            raise ValueError("Ovaj izveštaj se više ne čeka.")
        w["stop"] = True
    print("PURS: waiting for the report stopped by the user")
    _finish(request_id, status=STOPPED, greska="Čekanje je prekinuto.", zavrseno=time.time(), status_tekst="")


def _finish(request_id: str, **changes) -> None:
    """Waiting for this request ended: record it and wake whoever waits for it."""
    with _lock:
        w = _watches.pop(request_id, None)
        _done_events.pop(request_id, None)
    if changes:
        _update(request_id, **changes)
    if w is not None:
        w["event"].set()
        from tim_automation import purs_queue
        purs_queue.publish()


class _CheckTab:
    """The hidden background tab of the ePorezi browser in which the checks load "Упит стања" and download reports
    (the ePorezi window keeps its page). Made again when the browser changed or the tab failed."""

    def __init__(self) -> None:
        self.debugger = ""
        self.browser = self.page = None
        self.target = ""

    def get(self, driver) -> _Cdp:
        debugger = debugger_address(driver)
        if not debugger:
            raise RuntimeError("provera izveštaja radi samo u Chrome-u / Edge-u")
        if self.page is not None and debugger == self.debugger:
            return self.page
        self.close()
        self.debugger = debugger
        self.browser = _Cdp(_browser_ws(debugger))
        self.target = self.browser.call("Target.createTarget", {"url": "about:blank", "background": True})["targetId"]
        screen.HIDDEN.add(self.target)
        self.page = _Cdp(f"ws://{debugger}/devtools/page/{self.target}")
        return self.page

    def close(self) -> None:
        if self.page:
            self.page.close()
        if self.browser:
            if self.target:
                try:
                    self.browser.call("Target.closeTarget", {"targetId": self.target}, timeout=10)
                except Exception:
                    pass
            self.browser.close()
        screen.HIDDEN.discard(self.target)
        self.browser = self.page = None
        self.target = ""


_tab = _CheckTab()


class NotLoggedIn(RuntimeError):
    pass


def check_round(driver, pib: str, item) -> dict:
    """One time quantum of the PURS queue for one taxpayer: choose it if another one is chosen, load "Упит стања" once
    and handle every waiting request of this taxpayer: adopt a new row's ID, download a ready report, give up on one
    that isn't in the table / took too long. Worker thread."""
    from tim_automation import purs_queue
    from tim_automation.pages import purs
    with _lock:
        ids = [rid for rid, w in _watches.items() if w["pib"] == pib and not w["stop"]]
    if not ids:
        item.message = "Nema zahteva za proveru."
        return {"provereno": 0}
    try:
        if pib:
            try:
                purs_queue.ensure_taxpayer(driver, pib, item, show=False)
            except purs.PursError as e:
                if purs.session_alive(driver) is not True:
                    raise NotLoggedIn(f"niste prijavljeni na ePorezi ({e}): provera se nastavlja posle „Prijava na "
                                      "ePorezi“") from None
                raise
        item.progress("Učitavanje „Упит стања“")
        page = _tab.get(driver)
        table = _load_first_row(page, purs._site_origin() + purs.BALANCE_PAGE)
    except NotLoggedIn as e:
        purs_queue.note_session(False)
        for rid in ids:
            _update(rid, provera=time.time(), status_tekst="čeka se prijava na ePorezi")
        raise RuntimeError(str(e)) from None
    except Exception:
        _tab.close()  # e.g. the tab was closed: a new one next time
        raise
    purs_queue.note_session(True)
    ready = []
    for rid in ids:
        item.check_cancel()
        try:
            if _check_one(page, table, rid):
                ready.append(rid)
        except Exception as e:
            message = str(e).splitlines()[0] if str(e) else type(e).__name__
            print(f"    PURS: waiting for the report failed: {message}")
            _finish(rid, status=FAILED, greska=message, zavrseno=time.time(), status_tekst="")
    item.message = f"{len(ids)} zahtev(a) provereno" + (f", stiglo: {len(ready)}" if ready else "")
    return {"provereno": len(ids), "stiglo": ready}


def _check_one(page: _Cdp, table: dict, request_id: str) -> bool:
    """Look at one waiting request in the loaded table. True when its report is here now."""
    with _lock:
        w = _watches.get(request_id)
    if w is None or w["stop"]:
        return False
    w["checks"] += 1
    checks = w["checks"]
    site_id = w["site_id"]
    if not site_id and w["before_ids"] is not None:  # the ID wasn't seen after sending: wait for a new row
        new = _new_row(table, w["before_ids"])
        if new is None:
            if time.monotonic() - w["started"] > NEW_ROW_WAIT:
                raise RuntimeError(f"novi zahtev se nije pojavio u tabeli „Упит стања“ za {NEW_ROW_WAIT // 60} "
                                   "min (sajt ga verovatno nije prihvatio)")
            _update(request_id, provera=time.time(), provera_broj=checks,
                    status_tekst="čeka se da se zahtev pojavi u tabeli")
            return False
        site_id = w["site_id"] = new["cells"][0].strip()
        print(f"    PURS: the new request appeared in the table: ID {site_id}")
        _update(request_id, sajt_id=site_id, status_tekst="")
    found = _row_of(table, site_id) if site_id else None
    if site_id and found is None:
        w["missing"] += 1
        if w["missing"] >= 3:
            pib = get(request_id).get("PIB", "")
            raise RuntimeError(f"zahtev {site_id} nije u tabeli „Упит стања“ (na ePorezima je izabran drugi "
                               f"poreski obveznik? Treba {'PIB ' + pib if pib else 'onaj za koga je poslat'}: "
                               "„Odabir poreskog obveznika“, pa „Proveri sada“)")
        _update(request_id, provera=time.time(), provera_broj=checks, status_tekst="zahtev nije u tabeli")
        return False
    w["missing"] = 0
    row = {**table, **(found or {})}
    heads = row["heads"] if len(row["heads"]) == len(row["cells"]) else [
        f"Kolona {i + 1}" for i in range(len(row["cells"]))]
    changes = {"red": dict(zip(heads, row["cells"])), "provera": time.time(), "provera_broj": checks}
    if row["href"] and (site_id or row["href"] != w["old_href"]):
        same = downloaded(site_id, exclude=request_id)
        if same:  # this ePorezi report is saved already: use that file, don't download it again
            print(f"    PURS: report {site_id} is already saved as {same['fajl']}; not downloading it again")
            _finish(request_id, **changes, status=DONE, fajl=same["fajl"], velicina=same.get("velicina"),
                    vrsta_fajla=same.get("vrsta_fajla", ""), link=row["href"], zavrseno=time.time(), status_tekst="")
            return True
        print(f"    PURS: report ready ({row['href']}), downloading")
        _update(request_id, **changes, status_tekst="preuzimanje", status=WAITING)
        name, size, kind = _download(page, row["href"], request_id)
        _finish(request_id, **changes, status=DONE, fajl=name, velicina=size, vrsta_fajla=kind, link=row["href"],
                zavrseno=time.time(), status_tekst="")
        entry = get(request_id)
        print(f"    PURS: report saved as {FILES_DIR / name} ({size} bytes) for {entry.get('Tip zahteva', '')}")
        ui.status(f"PURS izveštaj je stigao: {entry.get('Tip zahteva', '')} ({entry.get('PIB', '')})")
        return True
    _update(request_id, **changes, status_tekst="")
    if time.monotonic() - w["started"] > MAX_WAIT:
        raise TimeoutError(f"izveštaj nije stigao za {MAX_WAIT // 3600} h")
    return False


def _row_of(table: dict, site_id: str) -> dict | None:
    """The row of this request ID (first column), or None when the table doesn't list it."""
    return next((r for r in table.get("all", []) if r["cells"] and r["cells"][0].strip() == site_id), None)


def _new_row(table: dict, before_ids: list[str]) -> dict | None:
    """The first row whose ID (first column) was not in the table before sending."""
    return next((r for r in table.get("all", []) if r["cells"] and r["cells"][0].strip().isdigit()
                 and r["cells"][0].strip() not in before_ids), None)


def _load_first_row(page: _Cdp, page_url: str) -> dict:
    page.call("Page.navigate", {"url": page_url})
    deadline = time.monotonic() + LOAD_TIMEOUT
    time.sleep(0.5)
    while page.evaluate("document.readyState") != "complete":
        if time.monotonic() > deadline:
            raise TimeoutError("stranica „Упит стања“ se nije učitala")
        time.sleep(0.5)
    path = page.evaluate("location.pathname") or ""
    if path.startswith("/user/login"):
        raise NotLoggedIn("niste prijavljeni na ePorezi (sesija je istekla ili je pretraživač ponovo pokrenut): "
                          "provera se nastavlja posle „Prijava na ePorezi“")
    return page.evaluate(FIRST_ROW_JS)


EXTENSIONS = {"application/pdf": "pdf", "text/xml": "xml", "application/xml": "xml", "text/html": "html",
              "application/zip": "zip"}


def _download(page: _Cdp, href: str, request_id: str) -> tuple[str, int, str]:
    result = page.evaluate(DOWNLOAD_JS % json.dumps(href), timeout=180)
    if result["status"] != 200:
        raise RuntimeError(f"preuzimanje izveštaja: HTTP {result['status']}")
    data = base64.b64decode(result["data"])
    kind = result["type"].split(";")[0].strip().lower()
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", result["disposition"])
    original = match.group(1) if match else ""
    ext = original.rsplit(".", 1)[1].lower() if "." in original else EXTENSIONS.get(kind, "bin")
    if data[:4] == b"%PDF":
        ext = "pdf"
    entry = get(request_id)
    stem = "-".join(x for x in ("upit-stanja", entry.get("PIB", ""), entry.get("kod", ""),
                                time.strftime("%Y%m%d-%H%M%S")) if x)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{stem}.{ext}")
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    (FILES_DIR / name).write_bytes(data)
    return name, len(data), kind
