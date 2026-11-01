"""One ePorezi session for the whole program, and a queue in front of it.

ePorezi allows one session, and in it one chosen taxpayer at a time, so everything that uses it is scheduled here and
runs one after another on a single worker thread:
- the PURS page's "Prijavi se" / "Izaberi obveznika" / "Zatraži sintetiku | analitiku" (purs_login),
- the jobs' PURS tasks (the job waits for its turn; "Zaustavi" takes it out of the queue),
- the check of the Početna page,
- the checks of the reports still waited for (purs_reports): one "time quantum" per taxpayer = choose that taxpayer if
  another one is chosen, load "Упит стања" once and look at all its waiting requests; then the next taxpayer. A
  taxpayer's next check is queued POLL s after its last one ended, at the end of the queue, so the checks of several
  taxpayers and the other items take turns.

The session lives in a browser of its own (`PursBrowser`), started on first use and kept when TiM ERP logs in again,
changes the company or restarts its browser (a site error): the login (SmartBox + PIN) is done once for the program.
Only the worker thread uses that browser (Selenium for the ePorezi window, DevTools for the hidden tab of the checks).

The page sees shared "purs_red" = {trenutno, red, istorija, sesija}."""
import collections
import threading
import time
import traceback
import uuid

from tim_automation import ui

POLL = 5  # seconds from the end of a taxpayer's check to its next check (the user: every 5 s)
KEPT = 60  # finished items kept for the page
SCHEDULED, RUNNING, DONE, FAILED, CANCELLED = "zakazano", "radi", "gotovo", "greska", "otkazano"
# What an item is (shown on the page): login, taxpayer, request, report check, session check, a job's other step.
KINDS = ("prijava", "obveznik", "zahtev", "provera", "sesija")


class Cancelled(Exception):
    """The item was taken out of the queue, or stopped while it ran."""


class Item:
    def __init__(self, kind: str, title: str, run, pib: str = "", source: str = "", firma: str | None = None,
                 firma_naziv: str = "", detail: str = "") -> None:
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title, self.run, self.pib, self.source = kind, title, run, pib or "", source
        self.firma, self.firma_naziv, self.detail = firma, firma_naziv, detail
        self.added = time.time()
        self.started = self.finished = None
        self.status = SCHEDULED
        self.message = self.progress_text = ""
        self.result = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.cancel = threading.Event()
        self.extra_cancelled = lambda: False  # a job's "Zaustavi"
        self.choose = True  # the queue chooses the item's taxpayer (pib) before it runs (else the item does it)
        self.on_end = None  # called with the item when it ended (also when taken out of the queue)

    def cancelled(self) -> bool:
        return self.cancel.is_set() or self.extra_cancelled()

    def check_cancel(self) -> None:
        if self.cancelled():
            raise Cancelled("Prekinuto.")

    def progress(self, text: str) -> None:
        self.progress_text = text
        _publish()

    def log(self, message: str) -> None:
        print(f"    {message}")

    def public(self) -> dict:
        return {"id": self.id, "vrsta": self.kind, "naziv": self.title, "pib": self.pib, "izvor": self.source,
                "firma": self.firma_naziv, "opis": self.detail, "dodato": self.added, "pocetak": self.started,
                "kraj": self.finished, "status": self.status, "poruka": self.message, "napredak": self.progress_text}


_cond = threading.Condition()
_queue: list[Item] = []
_current: Item | None = None
_history: collections.deque[Item] = collections.deque(maxlen=KEPT)
_session = {"pregledac": False, "prijavljen": None, "obveznik": None, "provereno": None}
_last_check: dict[str, float] = {}  # taxpayer PIB ("" = whichever is chosen) -> when its last check ended
_worker: threading.Thread | None = None
_stopping = threading.Event()


# --- the browser --------------------------------------------------------------------------------------------------

class PursBrowser:
    """The ePorezi browser: started on first use, started again when it was closed. Worker thread only."""

    def __init__(self) -> None:
        self.driver = None

    def alive(self) -> bool:
        if self.driver is None:
            return False
        try:
            self.driver.window_handles
            return True
        except Exception:
            return False

    def get(self):
        if self.alive():
            return self.driver
        from tim_automation import purs_login
        from tim_automation.driver import create_driver
        from tim_automation.pages import purs
        if self.driver is not None:
            print("PURS: the ePorezi browser is gone; starting it again (the ePorezi login is needed again).")
            self.quit()
        print("PURS: starting the ePorezi browser...")
        self.driver = create_driver()
        setattr(self.driver, purs.OWN_ATTR, True)
        ui.set_browser(self.driver, "purs")
        _session.update(pregledac=True, prijavljen=False, obveznik=None, provereno=time.time())
        purs_login.browser_changed()
        _publish()
        return self.driver

    def quit(self) -> None:
        ui.set_browser(None, "purs")
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = None
        _session.update(pregledac=False, prijavljen=None, obveznik=None)


browser = PursBrowser()


def driver_if_running():
    """The ePorezi browser if it is running (never starts it)."""
    return browser.driver if browser.driver is not None else None


def debugger_address() -> str:
    from tim_automation import purs_reports
    return purs_reports.debugger_address(browser.driver) if browser.driver is not None else ""


# --- session state ------------------------------------------------------------------------------------------------

def note_session(logged_in: bool | None, taxpayer: dict | None = None) -> None:
    """What a login / taxpayer choice / check found out about the session."""
    was = _session["prijavljen"]
    _session.update(prijavljen=logged_in, provereno=time.time())
    if logged_in is False:
        _session["obveznik"] = None
        if was is not False:  # the Početna card and the PURS page's panel
            from tim_automation import home_status, purs_login
            purs_login.note_session(False, None)
            home_status._set("purs", stanje="odjavljen", poruka="Niste prijavljeni (ili je sesija istekla).",
                             provereno=time.time(), obveznik=None)
    elif taxpayer is not None:
        _session["obveznik"] = {k: taxpayer.get(k, "") for k in ("PIB", "Naziv")}
    _publish()


def session() -> dict:
    return dict(_session)


# --- publishing ---------------------------------------------------------------------------------------------------

def publish() -> None:
    _publish()


def _publish() -> None:
    from tim_automation import purs_reports
    waiting = [{"pib": pib, "naziv": info["naziv"], "zahtevi": info["zahtevi"], "poslednja": _last_check.get(pib)}
               for pib, info in purs_reports.due_checks().items()]
    with _cond:
        state = {"trenutno": _current.public() if _current else None, "red": [i.public() for i in _queue],
                 "istorija": [i.public() for i in reversed(_history)], "sesija": dict(_session), "obveznici": waiting, "sada": time.time(),
                 "poll": POLL}
    ui.set_shared("purs_red", state)


# --- submitting ---------------------------------------------------------------------------------------------------

def submit(item: Item) -> Item:
    """Put an item at the end of the queue. Starts the worker if needed."""
    _start()
    with _cond:
        _queue.append(item)
        _cond.notify_all()
    print(f"PURS queue: scheduled „{item.title}“ ({item.source or item.kind}), {position(item.id)}. in line")
    _publish()
    return item


def position(item_id: str) -> int:
    """1 = next; 0 = running or not in the queue."""
    with _cond:
        return next((n for n, i in enumerate(_queue, 1) if i.id == item_id), 0)


def cancel(item_id: str) -> None:
    """Take a scheduled item out of the queue, or stop the running one (at its next check)."""
    with _cond:
        item = next((i for i in _queue if i.id == item_id), None)
        if item is not None:
            _queue.remove(item)
            _end(item, CANCELLED, "Otkazano pre izvršavanja.", Cancelled("Otkazano pre izvršavanja."))
        elif _current is not None and _current.id == item_id:
            _current.cancel.set()
            _current.message = "Prekida se..."
        else:
            raise ValueError("Ova stavka više nije u redu.")
    _publish()


def call(item: Item, cancelled=lambda: False, progress=lambda text: None):
    """For a job's task: schedule the item, wait for its turn and its end, return its result or raise its error
    (Cancelled when the job is stopped)."""
    item.extra_cancelled = cancelled
    submit(item)
    shown = None
    while not item.done.wait(0.25):
        if cancelled() and item.status == SCHEDULED:
            try:
                cancel(item.id)
            except ValueError:
                pass
        if item.status == SCHEDULED:
            with _cond:
                ahead = [i for i in _queue if i.id != item.id][:position(item.id) - 1]
                running = _current.title if _current else ""
            text = (f"U redu za ePorezi: {len(ahead) + 1}. na redu" + (f" (sada: {running})" if running else "")
                    if ahead or running else "U redu za ePorezi: sledeći")
            if text != shown:
                progress(text)
                shown = text
        elif item.progress_text and item.progress_text != shown:
            progress(item.progress_text)
            shown = item.progress_text
    if item.error is not None:
        raise item.error
    return item.result


def _end(item: Item, status: str, message: str = "", error: BaseException | None = None) -> None:
    item.status, item.finished = status, time.time()
    item.message = message or item.message
    item.error = error
    with _cond:
        _history.append(item)
    if item.on_end is not None:
        try:
            item.on_end(item)
        except Exception:
            traceback.print_exc()
    item.done.set()


# --- the worker ---------------------------------------------------------------------------------------------------

def _start() -> None:
    global _worker
    with _cond:
        if _worker is None or not _worker.is_alive():
            _stopping.clear()
            _worker = threading.Thread(target=_work, daemon=True, name="purs-queue")
            _worker.start()


def wake() -> None:
    """Something to check was added (purs_reports.watch): look at once."""
    _start()
    with _cond:
        _cond.notify_all()


def _schedule_checks() -> None:
    """Queue a check for every taxpayer with reports waited for whose last check ended POLL s ago and that has no
    check in the queue yet (at the end of the queue: round robin with everything else)."""
    from tim_automation import purs_reports
    if _session["prijavljen"] is False and browser.driver is not None:
        return  # logged out: the checks wait for a login (none is done by itself: the PIN is typed by a person)
    due = purs_reports.due_checks()
    now = time.time()
    with _cond:
        queued = {i.pib for i in _queue if i.kind == "provera"} | (
            {_current.pib} if _current is not None and _current.kind == "provera" else set())
        for pib, info in due.items():
            if pib in queued or now - _last_check.get(pib, 0) < POLL:
                continue
            _queue.append(Item("provera", f"Provera izveštaja · {info['naziv'] or pib or 'izabrani obveznik'}",
                               lambda d, it, pib=pib: purs_reports.check_round(d, pib, it), pib=pib,
                               source="Čekanje izveštaja", detail=f"{len(info['zahtevi'])} zahtev(a): "
                               + ", ".join(info["zahtevi"][:6])))


def _next_wakeup() -> float:
    from tim_automation import purs_reports
    due = purs_reports.due_checks()
    if not due or (_session["prijavljen"] is False and browser.driver is not None):
        return 2.0
    now = time.time()
    return max(0.2, min(POLL - (now - _last_check.get(pib, 0)) for pib in due))


def _work() -> None:
    global _current
    while not _stopping.is_set():
        _schedule_checks()
        with _cond:
            if not _queue:
                _cond.wait(_next_wakeup())
                continue
            item = _queue.pop(0)
            _current = item
            item.status, item.started = RUNNING, time.time()
        _publish()
        _run(item)
        with _cond:
            _current = None
        if item.kind == "provera":
            _last_check[item.pib] = time.time()
        _publish()


def _run(item: Item) -> None:
    from tim_automation.pages import purs
    print(f"PURS queue: running „{item.title}“" + (f" for {item.pib}" if item.pib else ""))
    try:
        item.check_cancel()
        driver = browser.get()
        if item.pib and item.choose and item.kind not in ("prijava", "obveznik", "sesija", "provera"):
            ensure_taxpayer(driver, item.pib, item, show=item.kind != "provera")
        item.result = item.run(driver, item)
        _end(item, DONE, item.message or "")
    except Cancelled as e:
        print(f"PURS queue: „{item.title}“ stopped")
        _end(item, CANCELLED, str(e) or "Prekinuto.", e)
    except Exception as e:
        message = str(e).splitlines()[0] if str(e) else type(e).__name__
        print(f"PURS queue: „{item.title}“ failed: {message}")
        if not isinstance(e, (purs.PursError, ValueError, RuntimeError, TimeoutError)):
            traceback.print_exc()
        _end(item, FAILED, message, e)
    finally:
        if item.kind != "provera":
            ui.show_browser("tim")  # the live view goes back to TiM ERP (when it follows the program)


def ensure_taxpayer(driver, pib: str, item: Item, show: bool = True) -> dict:
    """Make sure this taxpayer is chosen in the session (another item may have chosen another one since)."""
    from tim_automation.pages import purs
    chosen = getattr(driver, purs.TAXPAYER_ATTR, None) or {}
    if chosen.get("PIB") == pib and _session["prijavljen"]:
        return chosen
    purs.open_tab(driver, show=show)
    item.progress(f"Odabir poreskog obveznika {pib}")
    row = purs.choose_taxpayer(driver, pib, log=item.log, progress=item.progress)
    note_session(True, row)
    return row


def check_session(source: str = "Početna") -> Item | None:
    """Queue a check whether ePorezi is still logged in (None when the ePorezi browser isn't running: then it is
    not)."""
    if browser.driver is None:
        return None
    with _cond:
        for i in ([_current] if _current else []) + _queue:
            if i.kind == "sesija":
                return i
    return submit(Item("sesija", "Provera prijave na ePorezi", _probe, source=source))


def _probe(driver, item: Item) -> dict:
    from tim_automation.pages import purs
    purs.open_tab(driver, show=False)
    alive = purs.session_alive(driver)
    if alive is None and not driver.current_url.startswith("http"):
        alive = False  # the ePorezi window never opened ePorezi
    taxpayer = getattr(driver, purs.TAXPAYER_ATTR, None) if alive else None
    note_session(alive, taxpayer)
    item.message = {True: "Prijavljen", False: "Nije prijavljen", None: "Ne zna se"}[alive]
    return {"prijavljen": alive, "obveznik": taxpayer, "adresa": driver.current_url, "naslov": driver.title}


def handle_api(action: str, body: dict):
    if action == "cancel":
        cancel(str(body.get("id") or ""))
        return None
    if action == "session":
        check_session("Stranica PURS")
        return None
    raise ValueError(f"Nepoznata akcija: {action}")


def shutdown() -> None:
    """At program end: stop the worker, close the ePorezi browser."""
    _stopping.set()
    with _cond:
        for item in list(_queue):
            _end(item, CANCELLED, "Program je zatvoren.", Cancelled("Program je zatvoren."))
        _queue.clear()
        if _current is not None:
            _current.cancel.set()
        _cond.notify_all()
    if _worker is not None:
        _worker.join(timeout=10)
    browser.quit()
