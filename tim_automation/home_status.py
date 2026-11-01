"""The "Početna" page's checks and statistics: is TiM ERP ready, is ePorezi logged in, how did the jobs run.

TiM ERP: on the main thread (Selenium) from the ready prompt's tick (`process_pending`), so never during a job: the
TiM window shows the site's error / the main menu (with the company label) / the login page (session expired).
ePorezi: an item of the PURS queue (purs_queue.check_session: the ePorezi window asks the site again for the page it
shows, without leaving it); not started when the ePorezi browser isn't running (then it is not logged in). The result
also updates the PURS page's login panel (purs_login). Both are published as shared "pocetna" {tim, purs}; a check runs when
the ready prompt opens and when the page asks (`/api/pocetna/check`, at most every MIN_GAP s unless forced).
`/api/pocetna/stats` = the open company's job runs from the saved run reports (data/results/<job>-istorija.json)."""
import threading
import time

from tim_automation import ui

MIN_GAP = 20  # seconds: the page opening again doesn't re-check sooner
LOAD_TIMEOUT = 30

_tim_requested = threading.Event()
_state = {"tim": {"stanje": "", "poruka": "", "provereno": None},
          "purs": {"stanje": "", "poruka": "", "provereno": None, "obveznik": None}}
ready = False  # main.py: the ready prompt is open (a company is open)


def publish() -> None:
    ui.set_shared("pocetna", {k: dict(v) for k, v in _state.items()})


def _set(which: str, **changes) -> None:
    _state[which].update(changes)
    publish()


def reset_tim() -> None:
    _set("tim", stanje="", poruka="", provereno=None)


def handle_api(action: str, body: dict):
    if action == "check":
        force = bool(body.get("force"))
        what = body.get("what") or "all"
        if what in ("all", "tim"):
            request_tim(force)
        if what in ("all", "purs"):
            check_purs(force)
        return None
    if action == "stats":
        return stats(float(body.get("dana") or 7))
    raise ValueError(f"Nepoznata akcija: {action}")


# --- TiM ERP -------------------------------------------------------------------------------------------------------

def request_tim(force: bool = False) -> None:
    checked = _state["tim"]["provereno"]
    if not ready:
        _set("tim", stanje="", poruka="", provereno=None)
        return
    if force or not checked or time.time() - checked > MIN_GAP:
        _set("tim", stanje="provera")
        _tim_requested.set()


def process_pending(driver) -> None:
    """Main thread, from the ready prompt's tick (between jobs)."""
    if not _tim_requested.is_set() or driver is None:
        return
    _tim_requested.clear()
    from tim_automation.pages import purs, site_error
    from tim_automation.pages.home_page import HomePage
    from tim_automation.pages.login_page import LoginPage
    try:
        purs_tab = getattr(driver, purs.TAB_ATTR, None)
        if driver.current_window_handle == purs_tab:  # left on ePorezi: look at the TiM window
            others = [h for h in driver.window_handles if h != purs_tab]
            if others:
                driver.switch_to.window(others[0])
        if site_error.shown(driver):
            state, message = "greska", f"Sajt prikazuje „{site_error.MESSAGE}“ (posao će ponovo pokrenuti pretraživač)."
        elif HomePage(driver).is_open():
            label = HomePage(driver).company_label()
            state, message = "ok", f"Meni je prikazan{f', firma na sajtu: {label}' if label else ''}."
        elif driver.find_elements(*LoginPage.PASSWORD):
            state, message = "odjavljen", "Prikazana je stranica za prijavu (sesija je istekla). Kliknite „Promena firme“."
        else:
            state, message = "nepoznato", f"Na stranici nema glavnog menija ({driver.title or driver.current_url})."
    except Exception as e:
        state, message = "greska", f"Pretraživač ne odgovara: {str(e).splitlines()[0] if str(e) else type(e).__name__}"
    _set("tim", stanje=state, poruka=message, provereno=time.time())


# --- ePorezi -------------------------------------------------------------------------------------------------------

def check_purs(force: bool = False) -> None:
    """Ask the PURS queue whether ePorezi is still logged in (an item like any other: it waits for its turn)."""
    from tim_automation import purs_queue
    checked = _state["purs"]["provereno"]
    if not force and checked and time.time() - checked <= MIN_GAP:
        return
    if purs_queue.driver_if_running() is None:
        _set("purs", stanje="odjavljen", poruka="Niste prijavljeni (pretraživač za ePorezi još nije pokrenut).",
             provereno=time.time(), obveznik=None)
        return
    _set("purs", stanje="provera")
    item = purs_queue.check_session()
    if item is not None:
        previous = item.on_end
        item.on_end = lambda it: (_checked(it), previous and previous(it))


def _checked(item) -> None:
    from tim_automation import purs_login
    if item.status != "gotovo":
        _set("purs", stanje="nepoznato", provereno=time.time(), obveznik=None,
             poruka=f"Provera nije uspela: {item.message or item.status}")
        return
    logged_in, taxpayer = item.result["prijavljen"], item.result["obveznik"]
    if logged_in:
        message = (f"Izabran obveznik: {taxpayer['Naziv']} (PIB {taxpayer['PIB']})." if taxpayer else
                   "Prijavljeni ste; obveznik nije biran u ovom pokretanju (ili je biran ručno).")
    elif logged_in is False:
        message = "Niste prijavljeni (ili je sesija istekla)."
    else:
        message = f"Nepoznata stranica ePoreza: {item.result.get('naslov') or item.result.get('adresa')}"
    _set("purs", stanje="ok" if logged_in else "odjavljen" if logged_in is False else "nepoznato", poruka=message,
         provereno=time.time(), obveznik=taxpayer)
    if logged_in is not None:
        purs_login.note_session(logged_in, taxpayer)


def note_purs(taxpayer: dict | None) -> None:
    """A login / taxpayer choice just succeeded (PURS page or a job's task): logged in, no need to check."""
    from tim_automation import purs_login, purs_queue
    purs_queue.note_session(True, taxpayer)
    message = (f"Izabran obveznik: {taxpayer['Naziv']} (PIB {taxpayer['PIB']})." if taxpayer else
               "Prijavljeni ste; obveznik još nije izabran.")
    _set("purs", stanje="ok", poruka=message, provereno=time.time(), obveznik=taxpayer)
    purs_login.note_session(True, taxpayer)


# --- statistics ----------------------------------------------------------------------------------------------------

def stats(days: float = 7) -> dict:
    """The open company's job runs: totals over the saved reports (newest 20 per job) and over the last `days`."""
    from tim_automation.jobs import store
    jobs = store.snapshot().get("jobs", []) if store.company() else []
    since = time.time() - days * 86400
    runs = []
    for job in jobs:
        for h in store.step_history(job["id"]):
            runs.append({"posao": job.get("name", ""), "id": job["id"], "status": h.get("status", ""),
                         "pocetak": h.get("started_at") or 0, "kraj": h.get("finished_at"), "fajl": h.get("fajl", ""),
                         "koraci": h.get("koraci", 0), "greske": h.get("greske", 0)})
    runs.sort(key=lambda r: -r["pocetak"])
    recent = [r for r in runs if r["pocetak"] >= since]
    by_status: dict[str, int] = {}
    for r in recent:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    durations = [r["kraj"] - r["pocetak"] for r in recent if r["kraj"] and r["pocetak"]]
    today = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    return {"poslova": len(jobs), "dana": days, "pokretanja": len(recent), "danas": sum(r["pocetak"] >= today for r in runs),
            "po_statusu": by_status, "koraka": sum(r["koraci"] for r in recent),
            "prosek": sum(durations) / len(durations) if durations else None,
            "poslednja": runs[:5]}
