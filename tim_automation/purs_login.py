"""Logging in to ePorezi from the PURS page (no job needed), e.g. before "Proveri sada" after a restart.

"Prijavi se" = the same steps as the tasks "Prijava na ePorezi" (SmartBox, certificate issuer, PIN) and "Odabir poreskog
obveznika" (the open company's PIB unless another is typed); "Izaberi obveznika" = only the second. The page asks over
/api/purs-login/<action>; each one is an item of the PURS queue (purs_queue: one ePorezi session for the whole program,
its own browser and worker thread), so it waits for whatever was scheduled before it. A request ("Zatraži ...") is
for the company open in TiM (its PIB); login works without a company.

The PIN: the one typed on this page (Windows Credential Manager, entry "secret:purs-pin"), else the PIN of a
"Prijava na ePorezi" task in any job (and its issuer / reader). Settings (issuer, reader) in data/purs/prijava.json.
State published as shared "purs_prijava"; it is forgotten when the ePorezi browser is restarted (the session is gone)."""
import json
import time
from pathlib import Path

import keyring
import keyring.errors

from tim_automation import ui
from tim_automation.jobs import secret_params, store

SETTINGS_FILE = Path("data") / "purs" / "prijava.json"
PIN_ENTRY = "secret:purs-pin"
DEFAULT_PROVIDER = "Ministarstvo unutrašnjih poslova"

_state: dict = {"stanje": "", "poruka": "", "napredak": "", "obveznik": None, "vreme": None,
               "akcija": "", "zahtev": None}  # akcija: login / taxpayer / request (the PURS page's own requests)
ready = False  # set by main.py while the ready prompt is open (a company is open: requests can be sent)


def _settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _saved_pin() -> str | None:
    return keyring.get_password(secret_params.SERVICE, PIN_ENTRY)


def _job_login_task() -> tuple[dict, str] | None:
    """The first "Prijava na ePorezi" task with a saved PIN in any company's jobs, with its job's name."""
    def walk(tasks, job_name):
        for task in tasks or []:
            if task.get("type") == "purs_login" and secret_params.is_secret((task.get("params") or {}).get("pin")):
                return task, job_name
            found = walk(store.children(task), job_name)
            if found:
                return found
        return None
    for company in store._read_file().get("companies", {}).values():
        for job in company.get("jobs", []):
            found = walk(job.get("tasks"), job.get("name", ""))
            if found:
                return found
    return None


def _config() -> dict:
    """What the page shows: issuer / reader and where the PIN comes from (never the PIN itself)."""
    settings = _settings()
    job = _job_login_task()
    job_params = (job[0].get("params") or {}) if job else {}
    pin_from = "stranica" if _saved_pin() else (f"posao „{job[1]}“" if job else "")
    return {"izdavalac": settings.get("izdavalac") or job_params.get("izdavalac") or DEFAULT_PROVIDER,
            "citac": settings.get("citac", job_params.get("citac") or ""), "pin": pin_from,
            "email": settings.get("email", "")}


def _pin_if_any() -> str:
    """The PIN if one is saved, else "" (the login is skipped when ePorezi is still logged in; else it says so)."""
    try:
        return _pin()
    except Exception:
        return ""


def _pin() -> str:
    pin = _saved_pin()
    if pin:
        return pin
    job = _job_login_task()
    if job:
        return secret_params.reveal(job[0]["params"]["pin"], "PIN kartice")
    raise ValueError("PIN nije sačuvan: upišite ga.")


def publish() -> None:
    company = (ui.get_shared("session") or {}).get("company") or {}
    ui.set_shared("purs_prijava", {**_state, **_config(), "pib_firme": company.get("pib") or "", "spremno": ready})


def _set(**changes) -> None:
    _state.update(changes)
    publish()


def note_session(logged_in: bool, taxpayer: dict | None) -> None:
    """What a check of the ePorezi session found (home_status) or a job's PURS task did: keep the panel in step."""
    if _state["stanje"] == "radi":
        return
    if not logged_in:
        if _state["stanje"] == "gotovo":
            _set(stanje="", poruka="Sesija na ePorezima je istekla: prijavite se ponovo.", obveznik=None)
    elif taxpayer and (_state["stanje"] != "gotovo" or _state["obveznik"] != taxpayer):
        _set(stanje="gotovo", poruka="", obveznik={"PIB": taxpayer.get("PIB", ""), "Naziv": taxpayer.get("Naziv", "")},
             vreme=_state["vreme"] or time.time())


def browser_changed() -> None:
    """The ePorezi browser was (re)started (purs_queue): no ePorezi session any more."""
    _state.update(stanje="", poruka="", napredak="", obveznik=None, vreme=None)
    publish()


def _same_scheduled(item: dict) -> bool:
    from tim_automation import purs_queue
    with purs_queue._cond:
        items = ([purs_queue._current] if purs_queue._current else []) + purs_queue._queue
        return any(getattr(i, "page_request", None) == item for i in items if i.status in
                   (purs_queue.SCHEDULED, purs_queue.RUNNING))


def handle_api(action: str, body: dict):
    from tim_automation import purs_queue, purs_reports
    if action == "settings":
        settings = {"izdavalac": str(body.get("izdavalac") or "").strip(), "citac": str(body.get("citac") or "").strip(),
                    "email": str(body.get("email") if body.get("email") is not None else _settings().get("email", "")).strip()}
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
        if str(body.get("pin") or ""):
            keyring.set_password(secret_params.SERVICE, PIN_ENTRY, str(body["pin"]))
        publish()
        return None
    if action == "forget_pin":
        try:
            keyring.delete_password(secret_params.SERVICE, PIN_ENTRY)
        except keyring.errors.PasswordDeleteError:
            pass
        publish()
        return None
    if action == "cancel":  # the page's items still scheduled or running
        from tim_automation import purs_queue as q
        with q._cond:
            mine = [i.id for i in ([q._current] if q._current else []) + q._queue if getattr(i, "page_request", None)]
        for item_id in mine:
            try:
                q.cancel(item_id)
            except ValueError:
                pass
        return None
    if action in ("login", "taxpayer", "request"):
        item = {"action": action, "pib": str(body.get("pib") or "").replace(" ", "")}
        company = (ui.get_shared("session") or {}).get("company") or {}
        item["pib"] = item["pib"] or str(company.get("pib") or "")
        firma = purs_reports.current_company()
        if action != "login" and not item["pib"]:
            raise ValueError("Upišite PIB (PIB firme otvorene u TiM ERP-u nije poznat).")
        if action == "request":
            from tim_automation.pages import purs
            if firma[0] is None:
                raise ValueError("Zahtev se šalje za firmu otvorenu u TiM ERP-u: izaberite firmu.")
            kind = str(body.get("vrsta") or "")
            group = next((label for label, code in purs.BALANCE_GROUPS.items() if code == body.get("grupa")
                          or label == body.get("grupa")), "")
            if kind not in purs.BALANCE_TYPES:
                raise ValueError(f"Nepoznat tip zahteva „{kind}“.")
            if kind == purs.ANALYTICAL and not group:
                raise ValueError("Izaberite fiskalnu grupu za analitiku.")
            item.update(vrsta=kind, grupa=group)
        if _same_scheduled(item):
            raise ValueError("Isto je već zakazano u redu za ePorezi.")
        titles = {"login": "Prijava na ePorezi" + (f" i obveznik {item['pib']}" if item["pib"] else ""),
                  "taxpayer": f"Odabir poreskog obveznika {item['pib']}",
                  "request": f"Upit stanja: {item.get('vrsta', '')}" + (f" · {item.get('grupa', '').split(' – ')[0]}"
                                                                        if item.get("grupa") else "")}
        queued = purs_queue.Item({"login": "prijava", "taxpayer": "obveznik", "request": "zahtev"}[action],
                                 titles[action], lambda driver, it, request=item: _run(driver, request, it),
                                 pib=item["pib"] if action != "login" else "", source="Stranica PURS",
                                 firma=firma[0], firma_naziv=firma[1])
        queued.choose = False  # _run logs in first when needed, then chooses the taxpayer
        queued.on_end = _ended
        queued.page_request = item
        queued.firma_pair = firma
        purs_queue.submit(queued)
        place = purs_queue.position(queued.id)
        _set(stanje="radi", poruka="", akcija=action, zahtev=None,
             napredak=f"Zakazano u redu za ePorezi ({place}. na redu)" if place > 1 else "Zakazano u redu za ePorezi")
        return None
    raise ValueError(f"Nepoznata akcija: {action}")


def _ended(item) -> None:
    """Taken out of the queue before it ran: the panel must not keep saying it is in progress."""
    if item.status == "otkazano" and _state["stanje"] == "radi":
        _set(stanje="greska", napredak="", poruka="Otkazano.")


def _run(driver, request: dict, item) -> None:
    """One of the page's items, run by the PURS queue (worker thread, the ePorezi browser)."""
    from tim_automation import home_status, purs_queue
    from tim_automation.pages import purs
    log = item.log

    def progress(text: str) -> None:
        item.progress(text)
        _set(napredak=text)

    print("PURS page: " + {"login": "logging in to ePorezi", "taxpayer": "choosing the taxpayer",
                           "request": f"Upit stanja {request.get('vrsta')} {request.get('grupa', '')}"}[request["action"]])
    try:
        purs.open_tab(driver)
        config = _config()
        if request["action"] == "login":
            progress("Prijava na ePorezi (SmartBox)...")
            purs.login(driver, _pin(), provider=config["izdavalac"], terminal=config["citac"], log=log,
                       progress=progress, check_cancel=item.check_cancel)
            purs_queue.note_session(True, getattr(driver, purs.TAXPAYER_ATTR, None))
        elif request["action"] == "request" and purs.session_alive(driver) is not True:
            # a request logs in first only when needed (the queue chose the taxpayer when it could)
            progress("Prijava na ePorezi (SmartBox)...")
            purs.login(driver, _pin_if_any(), provider=config["izdavalac"], terminal=config["citac"], log=log,
                       progress=progress, check_cancel=item.check_cancel)
            purs_queue.note_session(True)
        item.check_cancel()
        pib = request["pib"]
        row = getattr(driver, purs.TAXPAYER_ATTR, None) or {}
        if pib:
            progress(f"Odabir poreskog obveznika {pib}...")
            row = purs.choose_taxpayer(driver, pib, log=log, progress=progress)
            purs_queue.note_session(True, row)
            if request["action"] == "request" and row.get("PIB") != pib:
                raise ValueError(f"Na ePorezima nije pronađen obveznik sa PIB-om {pib}; zahtev nije poslat.")
        _set(stanje="radi" if request["action"] == "request" else "gotovo", napredak="", vreme=time.time(),
             obveznik={"PIB": row.get("PIB", ""), "Naziv": row.get("Naziv", "")} if row else None,
             poruka="" if not pib or row.get("PIB") == pib else
             f"Nijedan red nema tačno PIB {pib}; izabran je prvi obveznik.")
        if row:
            print(f"PURS page: ePorezi ready for {row.get('Naziv', '')} ({row.get('PIB', '')})")
        home_status.note_purs(_state["obveznik"])
        item.message = f"Obveznik: {row.get('Naziv', '')} ({row.get('PIB', '')})" if row else "Prijavljen"
        if request["action"] == "request":
            from tim_automation import purs_balance
            # E-mail: "1" for the synthetic report (the user's choice), else the page's setting ("1" when empty).
            email = "1" if request["vrsta"] == purs.BALANCE_TYPE_SYNTHETIC else (config.get("email") or "1")
            out = purs_balance.request(driver, request["vrsta"], request.get("grupa", ""), email, log=log,
                                       progress=progress, check_cancel=item.check_cancel, job_name="Stranica PURS",
                                       firma=getattr(item, "firma_pair", None))
            sent = out["request"]
            item.message = (f"Današnji izveštaj ID {sent.get('sajt_id')} već postoji" if out["reused"]
                            else f"Poslat, ID {sent.get('sajt_id') or '—'}")
            _set(stanje="gotovo", napredak="", zahtev=sent["id"],
                 poruka=(f"Današnji izveštaj ovog tipa je već postojao (ID {sent.get('sajt_id')}): koristi se on."
                         if out["reused"] else f"Zahtev je poslat (ID {sent.get('sajt_id') or '—'}); izveštaj se čeka "
                         "u redu za ePorezi."))
            print(f"PURS page: request {sent.get('sajt_id')} " + ("(today's, reused)" if out["reused"] else "sent"))
    except purs_queue.Cancelled:
        _set(stanje="greska", napredak="", poruka="Prekinuto.")
        print("PURS page: stopped by the user")
        raise
    except Exception as e:
        message = str(e).splitlines()[0] if str(e) else type(e).__name__
        _set(stanje="greska", napredak="", poruka=message)
        print(f"PURS page: failed: {message}")
        raise
