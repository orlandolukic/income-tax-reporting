"""ePorezi portal of the Tax Administration (PURS, https://eporezi.purs.gov.rs), in its own browser tab.

Login page (HTML pasted 2026-10-12, Cyrillic): `/user/login.html`. Three ways in: eID (`.firstBtn`), the qualified
certificate through the local SmartBox application (`.secondBtn a`, `onclick="startWebSocket()"`; the user's way)
and the ePorezi application (`.smartBoxButton`). SmartBox: the page opens a WebSocket to the SmartBox program on this
computer (ws://localhost:17165 / 20806 / 65097) and fills its steps into containers by AJAX:
- `#providers`: select `#selectProvider` (certificate issuers; the user picks "MUP", the 3rd option) + "Учитај"
  `#js-submit-provider`; skipped by the page when there is only one;
- `#terminals`: select `#selectTerminal` (card readers) + `#js-submit-terminal`; skipped when there is only one;
- `#pin`: `#inputPin` + "Пријави се" `#js-submit-pin`;
- `#certificates`: hidden `#choosenCertAlias` / `#choosenCertName` + `#js-submit-certificates`; skipped when the card
  has one certificate.
Then the page signs the login XML and goes to "/" (logged in). Errors show in `#smartboxConnectionError` (no SmartBox:
"Конекција са читачем картице није успостављена") or `#smartboxError`; `#preloader` is the busy overlay.
Chrome asks before a public site talks to a program on this computer (Local Network Access: "… wants to access
other apps and services on this device"); `grant_permissions` allows it for ePorezi in advance (the user said to
always allow). Issuers on the live site (2026-10-12): "Halcom CA", "Sertifikaciono telo Pošte", "Ministarstvo
unutrašnjih poslova CA" (the user's, 3rd), "Privredna komora Srbije CA".
Choosing the taxpayer (HTML pasted 2026-10-12): the start page "/" (also the logo's `h1.logo a[href="/"]`; the user:
no need to click the logo, just be on "/"; opened with driver.get when not there) has the
search `input#pibNo` (name "pib") + "Претрага" `button.filterButton` (submit); the results are a table in
`.taxForm` (columns: No., ПИБ/ЈМБГ, Назив пореског обвезника, Овлашћење, button "Изабери" `button.pobchoose[authid]`).
What the page shows after "Изабери" was not pasted.
"Упит стања" (HTML pasted 2026-10-12): menu link `a[href="/upit-stanja.html"]` (4th in the menu). Form: "Тип
захтева" `select#selectUpstaType` (synthetic_account_all_pdf "Синтетика у PDF формату", analytical_account_group_pdf
"Аналитика за фискалну групу у PDF формату", synthetic_account_all_xml "Налог - упит стања синтетички"); for the
analytical one `#upstaGroups` shows "Група" `select#upstaGroupsSelect` (AKC, OST, PDP, PDV, PID, PNP, PPAP, PPFL, PPSD,
PRO, SPID); "Конто" `#kontoInput` (hidden, disabled); "Електронска пошта" `#upstaEmail` (required:
`#mailNotEmptyLabel` "Е-пошта је обавезно поље"); send `button.blueButton[value="Пошаљи захтев за проверу стања"]`.
The requests table below it (not pasted): the first row gets the report link in its last visible column when ready,
e.g. `<a href="/sw4i/upstaGetOld484/90721622" class="tax-button left" target="_blank">Извештај</a>`.
The contents of the providers / terminals / PIN / certificates steps (loginProviders.jsp etc.) were not pasted: the ids
come from the page's script. The logged-in page was not pasted either."""
import time
from urllib.parse import urlsplit

from selenium.webdriver.remote.webdriver import WebDriver

from tim_automation import config, ui

LOGIN_URL = config.PURS_URL
LOGIN_PATH = "/user/login"
STEP_TIMEOUT = 60  # SmartBox + the card reader can be slow
TAB_ATTR = "_tim_purs_tab"  # the ePorezi window's handle, kept on the driver
TAXPAYER_ATTR = "_tim_purs_taxpayer"  # the taxpayer chosen last ({"PIB", "Naziv"}), kept on the driver
OWN_ATTR = "_tim_purs_own"  # set on the ePorezi browser (purs_queue), which is used for nothing else
# Chrome's permissions for a site that connects to a program on this computer (SmartBox on ws://localhost).
LOCAL_PERMISSIONS = ("local-network-access", "local-network", "loopback-network")

_CYRILLIC = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџш",
                     ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p",
                      "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š"]))


def latin(text: str) -> str:
    """Lower-case Latin form of Serbian Cyrillic or Latin text, for matching ("МУП" -> "mup")."""
    return "".join(_CYRILLIC.get(ch, ch) for ch in (text or "").lower())


def initials(text: str) -> str:
    """First letters of the words ("Ministarstvo unutrašnjih poslova CA" -> "mupc")."""
    return "".join(word[0] for word in latin(text).split() if word[0].isalpha())


class PursError(Exception):
    pass


# State of the login page in one script: which step is shown, its options and any error.
STATE_JS = r"""
const shown = (el) => !!el && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
const text = (el) => (el ? el.innerText || el.textContent || '' : '').trim();
const opts = (sel) => sel ? [...sel.options].map((o, i) => ({i, value: o.value, text: o.text.trim()})) : [];
const errors = ['#smartboxConnectionError', '#smartboxError', '.login-error']
  .map((s) => [...document.querySelectorAll(s)]).flat().filter(shown).map(text).filter(Boolean);
const q = (s) => document.querySelector(s);
return {
  path: location.pathname, host: location.host, ready: document.readyState,
  login: !!q('#login') || !!q('form[name=loginForm]'),
  smartbox: !!q('.secondBtn a, a[onclick*="startWebSocket"]'),
  busy: shown(q('#preloader')),
  error: [...new Set(errors)].join(' | '),
  provider: shown(q('#selectProvider')) ? opts(q('#selectProvider')) : null,
  terminal: shown(q('#selectTerminal')) ? opts(q('#selectTerminal')) : null,
  pin: shown(q('#inputPin')),
  certificates: shown(q('#js-submit-certificates')) ?
    {alias: (q('#choosenCertAlias') || {}).value || '', text: text(q('#certificates')).slice(0, 500)} : null,
  title: document.title,
};
"""


def _host(url: str) -> str:
    return urlsplit(url).netloc


def grant_permissions(driver: WebDriver, log=print) -> None:
    """Allow ePorezi to reach SmartBox on this computer without Chrome asking (the user: always allow)."""
    parts = urlsplit(LOGIN_URL)
    origin = f"{parts.scheme}://{parts.netloc}"
    granted = []
    for name in LOCAL_PERMISSIONS:
        try:
            driver.execute_cdp_cmd("Browser.setPermission",
                                   {"permission": {"name": name}, "setting": "granted", "origin": origin})
            granted.append(name)
        except Exception:  # not known to this browser version (or not Chrome)
            pass
    log(f"ePorezi: permissions granted for {origin}: {', '.join(granted) or 'none (not supported)'}")


def open_tab(driver: WebDriver, show: bool = True) -> str:
    """Switch to the ePorezi window and (show) show it in the live view. Returns its handle. ePorezi has a browser of
    its own (purs_queue.PursBrowser, marked with OWN_ATTR): its first window is the ePorezi window; another window is
    opened only when that one was closed."""
    handle = getattr(driver, TAB_ATTR, None)
    handles = driver.window_handles
    if handle not in handles:
        from tim_automation import screen
        own = [h for h in handles if h not in screen.HIDDEN]
        if getattr(driver, OWN_ATTR, False) and own:
            driver.switch_to.window(own[0])
        else:
            driver.switch_to.new_window("window")
        handle = driver.current_window_handle
        setattr(driver, TAB_ATTR, handle)
    elif driver.current_window_handle != handle:
        driver.switch_to.window(handle)
    if show:
        try:  # a background tab isn't painted (live view) and may be throttled
            driver.execute_cdp_cmd("Page.bringToFront", {})
        except Exception:
            pass
        ui.show_window(handle, "purs")
    return handle


def state(driver: WebDriver) -> dict:
    return driver.execute_script(STATE_JS)


def logged_in(st: dict) -> bool:
    return (st["host"] == _host(LOGIN_URL) and st["ready"] == "complete" and not st["login"]
            and not st["path"].startswith(LOGIN_PATH))


def _choose(options: list[dict], wanted: str, what: str) -> dict:
    real = [o for o in options if o["text"] and o["value"] not in ("", "-1")] or options  # no "— izaberite —"
    if wanted.strip().isdigit():  # position in the list, from 1
        n = int(wanted)
        if 1 <= n <= len(real):
            return real[n - 1]
        raise PursError(f"{what}: nema stavke broj {n}; ponuđeno: " + ", ".join(f"„{o['text']}“" for o in real) + ".")
    if wanted:
        found = [o for o in real if latin(wanted) in latin(o["text"])]
        if not found:  # an abbreviation: "MUP" = "Ministarstvo unutrašnjih poslova CA"
            found = [o for o in real if initials(o["text"]).startswith(latin(wanted).replace(" ", ""))]
        if len(found) == 1:
            return found[0]
        names = ", ".join(f"„{o['text']}“" for o in real)
        if not found:
            raise PursError(f"{what} „{wanted}“ nije u listi; ponuđeno: {names}.")
        raise PursError(f"„{wanted}“ odgovara za više stavki ({what}): {names}. Upišite tačniji naziv.")
    if len(real) == 1:
        return real[0]
    raise PursError(f"Ponuđeno je više stavki ({what}): " + ", ".join(f"„{o['text']}“" for o in real)
                    + ". Upišite deo naziva u zadatku.")


def _select(driver: WebDriver, select_id: str, option: dict) -> None:
    driver.execute_script(
        "const s = document.getElementById(arguments[0]); s.selectedIndex = arguments[1];"
        "s.dispatchEvent(new Event('change', {bubbles: true}));", select_id, option["i"])


def _click(driver: WebDriver, css: str) -> None:
    driver.find_element("css selector", css).click()


# Asks the site again for the page the ePorezi window shows (not "/", where the taxpayer is chosen), in the background:
# the page itself stays. Logged out = the answer ends up on the login page.
SESSION_JS = r"""
const done = arguments[arguments.length - 1];
fetch(location.href, {credentials: 'include', cache: 'no-store'})
  .then((r) => done({url: r.url, status: r.status}))
  .catch((e) => done({url: '', status: 0, error: String(e)}));
"""


def session_alive(driver: WebDriver) -> bool | None:
    """Whether the ePorezi session is logged in, asked from the ePorezi window (current) without leaving its page.
    None when it can't be told (the window isn't on ePorezi yet, or the site didn't answer)."""
    if _host(driver.current_url) != _host(LOGIN_URL):
        return None
    if urlsplit(driver.current_url).path.startswith(LOGIN_PATH) or not logged_in(state(driver)):
        return False
    try:
        driver.set_script_timeout(20)
        answer = driver.execute_async_script(SESSION_JS) or {}
    except Exception:
        return None
    if urlsplit(answer.get("url") or "").path.startswith(LOGIN_PATH):
        return False
    return True if answer.get("status") == 200 else None


def login(driver: WebDriver, pin: str, provider: str = "MUP", terminal: str = "", certificate: str = "",
          log=print, progress=lambda text: None, check_cancel=lambda: None) -> dict:
    """Log in to ePorezi with the qualified certificate through SmartBox (in the ePorezi tab, which stays current).
    Skipped when the ePorezi window is still logged in. The PIN is typed at most once: a wrong PIN typed again and
    again would lock the card."""
    alive = session_alive(driver)
    if alive:
        log(f"ePorezi: already logged in, login skipped ({driver.current_url})")
        return {"prijavljen": True, "vec_prijavljen": True, "preskoceno": True, "adresa": driver.current_url,
                "naslov": driver.title, "poruka": "Već ste prijavljeni: prijava je preskočena."}
    if alive is False:
        log("ePorezi: the session has expired, logging in again")
        setattr(driver, TAXPAYER_ATTR, None)
    if not pin:
        raise PursError("PIN nije upisan.")
    grant_permissions(driver, log)
    driver.get(LOGIN_URL)
    deadline = time.monotonic() + 30
    while True:
        st = state(driver)
        if st["ready"] == "complete" and (st["smartbox"] or logged_in(st)):
            break
        if time.monotonic() > deadline:
            raise PursError(f"Stranica za prijavu na ePorezi se nije otvorila ({driver.current_url}).")
        time.sleep(0.3)
    if logged_in(st):
        log(f"ePorezi: already logged in ({driver.current_url})")
        return {"prijavljen": True, "vec_prijavljen": True, "adresa": driver.current_url, "naslov": st["title"]}

    log("ePorezi: clicking the SmartBox (qualified certificate) login")
    progress("SmartBox: povezivanje sa čitačem kartice")
    _click(driver, ".secondBtn a, a[onclick*='startWebSocket']")
    done: set[str] = set()  # steps already answered (each only once)
    chosen: dict[str, str] = {}
    step_started = time.monotonic()
    last = ""
    while True:
        st = state(driver)
        if logged_in(st):
            break
        if st["error"] and not st["busy"]:
            raise PursError(f"ePorezi: {st['error']}")
        step = ""
        if st["provider"] is not None and "provider" not in done:
            option = _choose(st["provider"], provider, "Izdavalac sertifikata")
            log(f"ePorezi: certificate issuer „{option['text']}“ (of {len(st['provider'])}), clicking Учитај")
            progress(f"Izdavalac sertifikata: {option['text']}")
            _select(driver, "selectProvider", option)
            _click(driver, "#js-submit-provider")
            chosen["Izdavalac sertifikata"] = option["text"]
            step = "provider"
        elif st["terminal"] is not None and "terminal" not in done:
            option = _choose(st["terminal"], terminal, "Čitač kartice")
            log(f"ePorezi: card reader „{option['text']}“")
            progress(f"Čitač kartice: {option['text']}")
            _select(driver, "selectTerminal", option)
            _click(driver, "#js-submit-terminal")
            chosen["Čitač kartice"] = option["text"]
            step = "terminal"
        elif st["pin"] and "pin" not in done:
            log("ePorezi: typing the PIN, clicking Пријави се")
            progress("Unos PIN-a")
            field = driver.find_element("id", "inputPin")
            field.clear()
            field.send_keys(pin)
            _click(driver, "#js-submit-pin")
            step = "pin"
        elif st["pin"] and "pin" in done and not st["busy"] and time.monotonic() - step_started > 15:
            # The PIN step is shown again with no message: never type the PIN a second time.
            raise PursError("ePorezi je ponovo tražio PIN; PIN se ne unosi drugi put (kartica bi se mogla zaključati). "
                            "Proverite PIN u zadatku.")
        elif st["certificates"] is not None and "certificates" not in done:
            if not st["certificates"]["alias"]:
                raise PursError("Na kartici je više sertifikata, a izbor sertifikata još nije podržan: "
                                + st["certificates"]["text"])
            log("ePorezi: confirming the certificate")
            _click(driver, "#js-submit-certificates")
            step = "certificates"
        if step:
            done.add(step)
            step_started = time.monotonic()
        elif time.monotonic() - step_started > STEP_TIMEOUT:
            where = {"provider": "izbor izdavaoca", "terminal": "izbor čitača", "pin": "prijava posle PIN-a",
                     "certificates": "potvrda sertifikata"}
            after = where.get(last, "povezivanje sa programom SmartBox")
            raise PursError(f"ePorezi: nema odgovora {STEP_TIMEOUT} s ({after}). Da li je SmartBox pokrenut i kartica "
                            "u čitaču?")
        last = step or last
        check_cancel()  # "Zaustavi" while waiting for SmartBox / the card
        time.sleep(0.3)
    log(f"ePorezi: logged in ({driver.current_url})")
    setattr(driver, TAXPAYER_ATTR, None)  # a new session: no taxpayer chosen in it yet
    return {"prijavljen": True, "vec_prijavljen": False, "adresa": driver.current_url, "naslov": st["title"], **chosen}


# Rows of the taxpayer search results: the cells of every row with an "Изабери" button.
RESULTS_JS = r"""
return [...document.querySelectorAll('button.pobchoose')].map((b, i) => {
  const cells = [...b.closest('tr').querySelectorAll('td')].map((td) => (td.innerText || td.textContent).trim());
  return {i, pib: (cells[1] || '').replace(/\s+/g, ''), naziv: cells[2] || '', ovlascenje: cells[3] || '',
          authid: b.getAttribute('authid') || ''};
});
"""
MESSAGE_JS = r"""
const shown = (el) => el.offsetParent !== null;
return [...document.querySelectorAll('.error, .errorMessage, .message, .login-error, .alert, .info, .notice')]
  .filter(shown).map((el) => (el.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 300);
"""


def _navigate(driver: WebDriver, action, what: str, timeout: float = 30) -> None:
    """Run `action` (a click that loads a new page) and wait until the new page has loaded."""
    driver.execute_script("window.__timOldPage = true;")
    action()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if driver.execute_script("return !window.__timOldPage && document.readyState === 'complete'"):
                return
        except Exception:  # in the middle of the page change
            pass
        time.sleep(0.2)
    raise PursError(f"ePorezi: stranica se nije učitala posle „{what}“ ({timeout:.0f} s).")


def choose_taxpayer(driver: WebDriver, pib: str, log=print, progress=lambda text: None) -> dict:
    """On ePorezi (logged in, in its window): the start page "/" -> search the PIB -> "Изабери" on its row (the first row if none
    has exactly this PIB)."""
    pib = "".join(str(pib or "").split())
    if not pib:
        raise PursError("PIB nije zadat.")
    chosen = getattr(driver, TAXPAYER_ATTR, None) or {}
    if chosen.get("PIB") == pib:  # the same taxpayer is already chosen: only if the session is still logged in
        if session_alive(driver):
            log(f"ePorezi: taxpayer {pib} {chosen.get('Naziv', '')} is already chosen, skipped")
            return {"PIB": pib, "Naziv": chosen.get("Naziv", ""), "Ovlašćenje": chosen.get("Ovlašćenje", ""),
                    "pronadjeno": 1, "preskoceno": True, "adresa": driver.current_url, "naslov": driver.title,
                    "poruka": "Ovaj obveznik je već izabran: izbor je preskočen."}
        log("ePorezi: the session is not logged in any more, choosing the taxpayer again needs a login")
    elif chosen.get("PIB"):
        log(f"ePorezi: taxpayer {chosen['PIB']} is chosen now, choosing {pib}")
    st = state(driver)
    if _host(driver.current_url) != _host(LOGIN_URL) or not logged_in(st):
        raise PursError("Niste prijavljeni na ePorezi: pre ovog zadatka treba da bude „Prijava na ePorezi“.")
    progress("Početna stranica ePorezi")
    if urlsplit(driver.current_url).path == "/" and driver.find_elements("id", "pibNo"):
        log("ePorezi: already on the start page /")
    else:  # the root page "/" (what the logo links to)
        parts = urlsplit(LOGIN_URL)
        log(f"ePorezi: opening the start page / (was {urlsplit(driver.current_url).path})")
        driver.get(f"{parts.scheme}://{parts.netloc}/")
        if logged_in(state(driver)) is False and urlsplit(driver.current_url).path.startswith(LOGIN_PATH):
            raise PursError("ePorezi je vratio stranicu za prijavu: sesija je istekla. Pokrenite „Prijava na ePorezi“.")
    if not driver.find_elements("id", "pibNo"):
        raise PursError(f"ePorezi: na početnoj stranici nema polja za PIB ({driver.current_url}).")
    log(f"ePorezi: searching taxpayer {pib}")
    progress(f"Pretraga PIB {pib}")
    field = driver.find_element("id", "pibNo")
    field.clear()
    field.send_keys(pib)
    _navigate(driver, lambda: _click(driver, "button.filterButton"), "Претрага")
    rows = driver.execute_script(RESULTS_JS)
    if not rows:
        message = driver.execute_script(MESSAGE_JS)
        raise PursError(f"ePorezi: poreski obveznik sa PIB-om {pib} nije pronađen"
                        + (f" ({message})." if message else "."))
    row = next((r for r in rows if r["pib"] == pib), None)
    if row is None:
        row = rows[0]
        log(f"ePorezi: no row with PIB {pib} exactly; taking the first of {len(rows)}: {row['pib']} {row['naziv']}")
    log(f"ePorezi: choosing {row['pib']} {row['naziv']} ({row['ovlascenje']})")
    progress(f"Izbor: {row['naziv']}")
    button = driver.find_elements("css selector", "button.pobchoose")[row["i"]]
    _navigate(driver, button.click, "Изабери")
    setattr(driver, TAXPAYER_ATTR, {"PIB": row["pib"], "Naziv": row["naziv"], "Ovlašćenje": row["ovlascenje"]})
    message = driver.execute_script(MESSAGE_JS)
    log(f"ePorezi: taxpayer chosen ({driver.current_url})" + (f"; page says: {message}" if message else ""))
    return {"PIB": row["pib"], "Naziv": row["naziv"], "Ovlašćenje": row["ovlascenje"], "pronadjeno": len(rows),
            "adresa": driver.current_url, "naslov": driver.title, "poruka": message}


BALANCE_PAGE = "/upit-stanja.html"
BALANCE_TYPES = {  # label on the job page -> (value of #selectUpstaType, short code for file names)
    "Sintetika u PDF formatu": ("synthetic_account_all_pdf", "sintetika"),
    "Analitika za fiskalnu grupu u PDF formatu": ("analytical_account_group_pdf", "analitika"),
    "Nalog - upit stanja sintetički": ("synthetic_account_all_xml", "nalog-xml"),
}
ANALYTICAL = "Analitika za fiskalnu grupu u PDF formatu"
BALANCE_TYPE_SYNTHETIC = "Sintetika u PDF formatu"
BALANCE_GROUPS = {  # label on the job page -> value of #upstaGroupsSelect
    "AKC – Akcize": "AKC",
    "OST – Ostalo": "OST",
    "PDP – Porez na dobit preduzeća": "PDP",
    "PDV – Porez na dodatu vrednost": "PDV",
    "PID – Objedinjena naplata poreza i doprinosa": "PID",
    "PNP – Porez na nasleđe i poklon": "PNP",
    "PPAP – Porez na prenos apsolutnih prava": "PPAP",
    "PPFL – Porez na prihod fizičkih lica": "PPFL",
    "PPSD – Porez na prihode od samostalne delatnosti": "PPSD",
    "PRO – Porez na registrovano oružje": "PRO",
    "SPID – Računi poreza i doprinosa pre objedinjene naplate": "SPID",
}
SEND_JS = """return [...document.querySelectorAll('button, input[type=submit]')]
  .find((b) => /Пошаљи захтев/.test(b.value || b.textContent || '')) || null;"""


def _site_origin() -> str:
    parts = urlsplit(LOGIN_URL)
    return f"{parts.scheme}://{parts.netloc}"


def first_request_row(driver: WebDriver) -> dict:
    from tim_automation import purs_reports
    return driver.execute_script("return " + purs_reports.FIRST_ROW_JS.strip())


def _row_dict(row: dict) -> dict:
    heads = row["heads"] if len(row["heads"]) == len(row["cells"]) else [f"Kolona {i + 1}" for i in range(len(row["cells"]))]
    return dict(zip(heads, row["cells"]))


STEP_PAUSE = 1.0  # seconds between filling the fields (the site errored when they were filled at once)
REFRESH = 5  # seconds between refreshes while looking for the new request
NEW_ROW_TRIES = 4  # refreshes in the task; then the background watcher goes on looking


def _table_ids(table: dict) -> list[str]:
    return [r["cells"][0].strip() for r in table.get("all", []) if r["cells"] and r["cells"][0].strip().isdigit()]


def _new_request(table: dict, before_ids: list[str]) -> dict | None:
    return next((r for r in table.get("all", []) if r["cells"] and r["cells"][0].strip().isdigit()
                 and r["cells"][0].strip() not in before_ids), None)


def _fold(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _today_texts() -> list[str]:
    """Today's date as the requests table may write it (13.10.2026, 3.10.2026, 2026-10-13, 13/10/2026)."""
    t = time.localtime()
    return list(dict.fromkeys([f"{t.tm_mday:02d}.{t.tm_mon:02d}.{t.tm_year}", f"{t.tm_mday}.{t.tm_mon}.{t.tm_year}",
                               f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}", f"{t.tm_mday:02d}/{t.tm_mon:02d}/{t.tm_year}"]))


def same_today(table: dict, value: str, label: str, group_value: str = "", group_label: str = "") -> list[dict]:
    """Rows of the requests table sent today of this type (its value, e.g. synthetic_account_all_pdf, or the form's
    label, e.g. "Синтетика у PDF формату", in a cell), newest first: {"id", "cells", "href", "grupa"}; "grupa" = True /
    False when the row shows a group (analytical), None when it can't be told from the row."""
    today = _today_texts()
    groups = set(BALANCE_GROUPS.values())
    found = []
    for row in table.get("all", []):
        cells = row.get("cells") or []
        if not cells or not cells[0].strip().isdigit():
            continue
        text = _fold(" ".join(cells))
        if not any(day in text for day in today):
            continue
        if _fold(value) not in text and not (label and _fold(label) in text):
            continue
        group = None
        if group_value:
            words = set(text.replace(",", " ").replace("–", " ").upper().split())
            shown = words & groups
            if shown or (group_label and _fold(group_label) in text):
                group = group_value in shown or bool(group_label and _fold(group_label) in text)
        found.append({"id": cells[0].strip(), "cells": cells, "href": row.get("href", ""), "grupa": group})
    return found


def _alert_text(driver: WebDriver) -> str:
    """Accept a JavaScript alert / confirm the page opened and return its text ("" if none)."""
    try:
        alert = driver.switch_to.alert
        text = alert.text
        alert.accept()
        return text
    except Exception:
        return ""


def _snapshot(driver: WebDriver, name: str) -> str:
    """Save the page's HTML in logs/ (for "check now"); returns the path."""
    from pathlib import Path
    folder = Path("logs")
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.html"
    try:
        path.write_text(driver.page_source, encoding="utf-8")
    except Exception:
        return ""
    return str(path)


def send_balance_request(driver: WebDriver, kind: str, group: str = "", email: str = "", log=print,
                         progress=lambda text: None, check_cancel=lambda: None) -> dict:
    """On ePorezi (logged in, taxpayer chosen): "Упит стања" -> fill in the form slowly -> "Пошаљи захтев за проверу
    стања" (a real mouse click) -> refresh every REFRESH s until a row with a new ID shows in the requests table.
    Returns {"id": the site's request ID ("" if not seen yet), "pre": IDs before sending, "red", "stari_link", "url"}."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import Select

    def pause(seconds: float = STEP_PAUSE) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            check_cancel()
            time.sleep(0.1)

    if kind not in BALANCE_TYPES:
        raise PursError(f"Nepoznat tip zahteva „{kind}“; postoje: {', '.join(BALANCE_TYPES)}.")
    value = BALANCE_TYPES[kind][0]
    group_value = ""
    if kind == ANALYTICAL:
        if group not in BALANCE_GROUPS:
            raise PursError("Za „Analitika za fiskalnu grupu“ izaberite grupu.")
        group_value = BALANCE_GROUPS[group]
    if not logged_in(state(driver)):
        raise PursError("Niste prijavljeni na ePorezi: pre ovog zadatka treba da bude „Prijava na ePorezi“.")
    progress("Упит стања")
    links = driver.find_elements("css selector", f"a[href='{BALANCE_PAGE}'], a.upit-stanja")
    if urlsplit(driver.current_url).path == BALANCE_PAGE:
        log("ePorezi: already on Упит стања, reloading it")
        driver.refresh()
    elif links:
        log("ePorezi: clicking Упит стања in the menu")
        _navigate(driver, links[0].click, "Упит стања")
    else:
        log(f"ePorezi: no Упит стања link on {urlsplit(driver.current_url).path}; opening {BALANCE_PAGE}")
        driver.get(_site_origin() + BALANCE_PAGE)
    if urlsplit(driver.current_url).path.startswith(LOGIN_PATH):
        raise PursError("ePorezi je vratio stranicu za prijavu: sesija je istekla. Pokrenite „Prijava na ePorezi“.")
    if not driver.find_elements("id", "selectUpstaType"):
        raise PursError(f"ePorezi: na stranici nema obrasca za upit stanja ({driver.current_url}). Da li je izabran "
                        "poreski obveznik?")
    pause()

    log(f"ePorezi: request type {value}" + (f", group {group_value}" if group_value else ""))
    progress("Popunjavanje obrasca")
    Select(driver.find_element("id", "selectUpstaType")).select_by_value(value)
    pause()
    if group_value:
        deadline = time.monotonic() + 10
        while not driver.find_element("id", "upstaGroupsSelect").is_displayed():
            if time.monotonic() > deadline:
                raise PursError("ePorezi: posle izbora analitike nije se pojavio izbor grupe.")
            pause(0.2)
        Select(driver.find_element("id", "upstaGroupsSelect")).select_by_value(group_value)
        pause()
    field = driver.find_element("id", "upstaEmail")
    if email:
        field.click()
        field.clear()
        for ch in email:  # key by key, like a person
            field.send_keys(ch)
            time.sleep(0.04)
        field.send_keys(Keys.TAB)  # leave the field (the page may check it on blur)
        pause()
    elif not (field.get_attribute("value") or "").strip():
        raise PursError("ePorezi traži e-poštu („Електронска пошта“), a u zadatku nije upisana.")
    chosen = driver.execute_script(
        "const v = (id) => { const e = document.getElementById(id); return e ? e.value : null; };"
        "const t = (id) => { const e = document.getElementById(id); const o = e && e.options[e.selectedIndex];"
        " return o ? o.text.trim() : ''; };"
        "return {tip: v('selectUpstaType'), grupa: v('upstaGroupsSelect'), email: v('upstaEmail'),"
        " tipTekst: t('selectUpstaType'), grupaTekst: t('upstaGroupsSelect')};")
    log(f"ePorezi: form before sending: {chosen}")
    if chosen["tip"] != value or (group_value and chosen["grupa"] != group_value):
        raise PursError(f"ePorezi: obrazac nije popunjen kako treba ({chosen}).")

    before = first_request_row(driver)
    before_ids = _table_ids(before)
    button = driver.execute_script(SEND_JS)
    if button is None:
        raise PursError("ePorezi: nema dugmeta „Пошаљи захтев за проверу стања“.")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    pause()
    log("ePorezi: clicking Пошаљи захтев за проверу стања")
    progress("Slanje zahteva")
    driver.execute_script("window.__timOldPage = true;")
    ActionChains(driver).move_to_element(button).pause(0.3).click().perform()

    # The page's answer: an alert, a new page or (AJAX) a changed table. Then refresh until the new row shows.
    alerts: list[str] = []
    new = None
    started = time.monotonic()
    while time.monotonic() - started < 10:
        text = _alert_text(driver)
        if text:
            alerts.append(text)
            log(f"ePorezi: the page says (alert): {text}")
        try:
            label = driver.find_elements("id", "mailNotEmptyLabel")
            if label and label[0].is_displayed():
                raise PursError("ePorezi: „Е-пошта је обавезно поље“.")
            table = first_request_row(driver)
            new = _new_request(table, before_ids)
            if not new and alerts and same_today(table, value, chosen.get("tipTekst", ""), group_value,
                                                 chosen.get("grupaTekst", "")):
                break  # refused, and today's request of this type is there: the task uses that one
        except PursError:
            raise
        except Exception:  # in the middle of the page change
            pass
        if new:
            break
        pause(0.5)
    message = ""
    for attempt in range(1, NEW_ROW_TRIES + 1):
        if new or (alerts and time.monotonic() - started < 10):
            break
        try:
            message = driver.execute_script(MESSAGE_JS) or message
            if (alerts or message) and same_today(first_request_row(driver), value, chosen.get("tipTekst", ""),
                                                  group_value, chosen.get("grupaTekst", "")):
                log("ePorezi: the site answered and today's request of this type is in the table: not waiting longer")
                break
        except Exception:
            pass
        progress(f"Čeka se da se zahtev pojavi u tabeli ({attempt}. osvežavanje)")
        pause(REFRESH)
        log(f"ePorezi: refreshing Упит стања ({attempt}/{NEW_ROW_TRIES})")
        driver.get(_site_origin() + BALANCE_PAGE)
        text = _alert_text(driver)
        if text:
            alerts.append(text)
        new = _new_request(first_request_row(driver), before_ids)
    if new:
        site_id = new["cells"][0].strip()
        log(f"ePorezi: request sent, ID {site_id}: {new['cells']}")
        table = first_request_row(driver)
        heads = table["heads"] if len(table["heads"]) == len(new["cells"]) else [f"Kolona {i + 1}" for i in range(len(new["cells"]))]
        row = dict(zip(heads, new["cells"]))
    existing: list[dict] = []
    if not new:
        site_id, row = "", {}
        table = first_request_row(driver)
        # The site makes one report of a type per day: a request of the same type sent today is the answer.
        existing = same_today(table, value, chosen.get("tipTekst", ""), group_value, chosen.get("grupaTekst", ""))
        if existing:
            heads = table["heads"]
            for e in existing:
                e["red"] = dict(zip(heads, e["cells"])) if len(heads) == len(e["cells"]) else {}
            log(f"ePorezi: no new request; today's requests of this type in the table: "
                f"{[(e['id'], e['grupa']) for e in existing]}" + (f"; page message: {message}" if message else "")
                + (f"; alerts: {alerts}" if alerts else ""))
        else:
            saved = _snapshot(driver, "purs-upit-stanja")
            log(f"ePorezi: no new request in the table after {NEW_ROW_TRIES} refreshes; the page is saved in {saved}"
                + (f"; page message: {message}" if message else "") + (f"; alerts: {alerts}" if alerts else ""))
            if alerts or message:
                raise PursError("ePorezi nije prihvatio zahtev: " + " | ".join(alerts + ([message] if message else [])))
    return {"stari_link": before["href"], "red": row, "url": _site_origin() + BALANCE_PAGE, "id": site_id,
            "pre": before_ids, "poruka": " | ".join(alerts + ([message] if message and not new else [])),
            "danasnji": existing}
