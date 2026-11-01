"""Finansije › Izveštaji › "Popis salda analitike (sintetika)" (form SINKARTRPTPAGE; HTML pasted by the user 2026-10-11).

The page has the filter form (`A1`) on the page itself, with the same rows as "Napredni filteri"
(pages/filters.py): konto.sifra, stavka fin.naloga.Analiticka šifra, stavka fin.naloga.Datum,
finansijski nalog.Datum, stavka fin.naloga.Dokument, mpt.sifra, org.jedinica.sifra,
finansijski nalog.Status, pdv obracun.PDV obračun. Each change is sent to the server by AJAX. Konto has
two text fields for "Između" (`zrl_1_I17`, `zrl_1_I21`, autocomplete), dates are `zrl_N_I19` / `zrl_N_I23`
(DD/MM/YYYY).

"Prikaži" (`button#A3`, `_JAEE(_PAGE_,'A3',16,2)`) fills the report table `A4` by AJAX: one group per
konto, header row `td#A4_H_<i>` "Konto: 6142 - Prihod od prodaje usluga", rows per analytic code
(Ana.šifra, Naziv, Duguje PS, Potražuje PS, Duguje, Potražuje, Saldo) and the group's footer `td#A4_B_<j>`
"Ukupno:" with read-only inputs (classes A12 Duguje PS, A22 Potražuje PS, A23 Duguje, A13 Potražuje,
A14 Saldo). The whole report's totals are below the table: A19 Duguje, A20 Potražuje, A21 Saldo.
Like other WebDev tables it may render only part of the rows, so the groups are only used when they add
up to the totals.

The konto header is a link-styled button (`<button onclick="_PAGE_.A4.value=1;_T3(event)" class="… wblien …">Konto:
6142 - …</button>`): clicking it opens the konto's card with the individual entries (`open_konto` / `read_card`; that
page wasn't pasted, its table is found by its "Duguje" / "Potražuje" columns). Its back arrow is
`<button onclick="if(_HOMEROBNOFIN_SUB()){_JSL(_PAGE_,'M28','_self','','')}" id="M28">` (pasted 2026-10-12, no text,
only an image): it returns to this page (`back`).
"""
import re
import time

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from tim_automation import menu
from tim_automation.pages import app_page, filters
from tim_automation.pages.app_page import parse_amount
from tim_automation.pages.wd_table import WDTable, find_tables

VIEW = "SINKARTRPTPAGE"
MENU_PATH = "Finansije > Izveštaji"
LINK_TEXT = "Popis salda analitike (sintetika)"
SHOW_TEXT = "Prikaži"

# Counts the page's XMLHttpRequests (WebDev AJAX), so we can wait until "Prikaži" has got its answer.
XHR_HOOK_JS = """
if (!window.__timXhr) {
  const s = window.__timXhr = {active: 0, done: 0};
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    s.active++;
    let ended = false;
    const end = () => { if (!ended) { ended = true; s.active--; s.done++; } };
    this.addEventListener('loadend', end);
    try { return send.apply(this, args); } catch (e) { end(); throw e; }
  };
}
return window.__timXhr.done;
"""
XHR_STATE_JS = "return window.__timXhr ? [window.__timXhr.active, window.__timXhr.done] : [0, 0];"
IS_REPORT_JS = f"return !!(document.forms.length && document.forms[0].name === '{VIEW}');"
# Clickable things whose text (case, diacritics ignored) is the wanted one; also lists what there is.
FIND_LINK_JS = r"""
const wanted = arguments[0];
const norm = (t) => t.toLowerCase().replace(/đ/g, 'dj').normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/\s+/g, ' ').trim();
const items = [...document.querySelectorAll('a, button, input[type=button], [onclick]')]
  .filter((e) => e.offsetParent || e.getClientRects().length);
const text = (e) => (e.innerText || e.value || e.title || '').trim();
const found = items.find((e) => norm(text(e)) === wanted) || items.find((e) => norm(text(e)).startsWith(wanted));
return {element: found || null, texts: [...new Set(items.map(text).filter(Boolean))].slice(0, 80)};
"""
RESULT_JS = r"""
const value = (name) => { const e = document.getElementsByName(name)[0]; return e ? e.value : null; };
const field = (cell, cls) => { const e = cell.querySelector('input.' + cls); return e ? e.value : null; };
const groups = [];
let header = null;
for (const row of document.querySelectorAll('#A4_TB > tbody > tr')) {
  if (row.style.display === 'none') continue;
  const cell = row.querySelector(':scope > td[id^="A4_H_"], :scope > td[id^="A4_B_"]');
  if (!cell) continue;
  if (cell.id.startsWith('A4_H_')) {
    header = cell.innerText.replace(/\s+/g, ' ').trim() || null;
  } else if (header && cell.querySelector('input')) {
    groups.push({naslov: header, duguje: field(cell, 'A23'), potrazuje: field(cell, 'A13'), saldo: field(cell, 'A14')});
    header = null;
  }
}
const occ = document.getElementsByName('_A4_OCC')[0];
const mask = document.getElementById('A4_MASQUE');
return {
  duguje: value('A19'), potrazuje: value('A20'), saldo: value('A21'), groups,
  redova: occ ? Number(occ.value) : null,
  loading: !!(mask && mask.offsetParent),
};
"""


# The visible konto header buttons of the report table: {konto: button}.
KONTO_BUTTONS_JS = r"""
const out = {};
for (const cell of document.querySelectorAll('#A4_TB td[id^="A4_H_"]')) {
  if (!cell.offsetParent) continue;
  const button = cell.querySelector('button, a') || cell;
  const m = cell.innerText.replace(/\s+/g, ' ').trim().match(/^Konto:\s*(\S+)/);
  if (m && !(m[1] in out)) out[m[1]] = button;
}
return out;
"""
# The card's back arrow (M28, no text): by id, else by the id in its onclick.
BACK_JS = r"""
const visible = (e) => e && (e.offsetParent || e.getClientRects().length);
const byId = document.getElementById(arguments[0]);
if (visible(byId)) return byId;
return [...document.querySelectorAll('button, a')].find((e) => visible(e)
  && (e.getAttribute('onclick') || e.getAttribute('href') || '').includes("'" + arguments[0] + "'")) || null;
"""
BACK_ID = "M28"
DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")


def is_open(driver: WebDriver) -> bool:
    try:
        return bool(driver.execute_script(IS_REPORT_JS))
    except WebDriverException:
        return False


def open_page(driver: WebDriver, timeout: float = 45) -> None:
    """Open Popis salda analitike (sintetika): Finansije › Izveštaji, then the link "Popis salda analitike (sintetika)". If the link opens
    it in an iframe, the driver is left switched into that frame."""
    driver.switch_to.default_content()
    if is_open(driver):
        return
    print(f"Opening {MENU_PATH} > {LINK_TEXT}...")
    app_page.open_menu_item(driver, menu.find(MENU_PATH), timeout)
    if is_open(driver):
        return
    found = driver.execute_script(FIND_LINK_JS, app_page.normalize(LINK_TEXT))
    if not found["element"]:
        raise LookupError(f"Link „{LINK_TEXT}“ nije pronađen na stranici „{MENU_PATH}“. "
                          f"Na stranici su: {', '.join(found['texts'])}.")
    frames = len(driver.find_elements(By.TAG_NAME, "iframe"))
    driver.execute_script("window.__timOldPage = true;")
    found["element"].click()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if app_page._page_replaced(driver) and is_open(driver):
            break
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if len(iframes) > frames:
            driver.switch_to.frame(iframes[-1])
            WebDriverWait(driver, timeout).until(lambda d: is_open(d))
            print("Popis salda analitike (sintetika) opened in a window (iframe).")
            break
        time.sleep(0.2)
    else:
        raise TimeoutError(f"„{LINK_TEXT}“ se nije otvorila za {timeout:g} s (sada: {app_page.view_name(driver)}).")
    app_page.wait_until_idle(driver)


def show(driver: WebDriver, filter_list: list[dict], timeout: float = 120) -> dict:
    """Set the filters (all others off), click "Prikaži" and read the result:
    {"duguje", "potrazuje", "saldo" (floats), "konta": [{konto, naziv, duguje, potrazuje, saldo}],
    "konta_potpuna": the groups add up to the totals (all konta are shown), "redova"}."""
    driver.execute_script(XHR_HOOK_JS)
    filters.set_filters(driver, filter_list)
    buttons = [b for b in driver.find_elements(By.XPATH, f"//button[normalize-space()='{SHOW_TEXT}']") if b.is_displayed()]
    if not buttons:
        raise LookupError(f"Dugme „{SHOW_TEXT}“ nije pronađeno.")
    end = time.monotonic() + 10  # let the filter changes reach the server first
    while time.monotonic() < end and driver.execute_script(XHR_STATE_JS)[0]:
        time.sleep(0.1)
    before = driver.execute_script(XHR_STATE_JS)[1]
    buttons[0].click()
    _wait_answer(driver, before, timeout)
    raw = driver.execute_script(RESULT_JS)
    result = {k: _amount(raw[k], k) for k in ("duguje", "potrazuje", "saldo")}
    konta = []
    for g in raw["groups"]:
        title = g["naslov"].removeprefix("Konto:").strip()
        konto, _, naziv = title.partition(" - ")
        konta.append({"konto": konto.strip(), "naziv": naziv.strip(),
                      **{k: _amount(g[k], f"{konto} {k}") for k in ("duguje", "potrazuje", "saldo")}})
    result["konta"] = konta
    result["konta_potpuna"] = (_same(sum(k["potrazuje"] for k in konta), result["potrazuje"])
                               and _same(sum(k["duguje"] for k in konta), result["duguje"]))
    result["redova"] = raw["redova"]
    if not _same(result["duguje"] - result["potrazuje"], result["saldo"]):
        print(f"    Note: totals don't add up (duguje {result['duguje']} - potražuje {result['potrazuje']} "
              f"!= saldo {result['saldo']}); check which field is which.")
    return result


def _wait_answer(driver: WebDriver, before: int, timeout: float) -> None:
    """Wait until the AJAX request started by "Prikaži" has been answered and the table isn't loading."""
    end = time.monotonic() + timeout
    started = time.monotonic()
    while time.monotonic() < end:
        active, done = driver.execute_script(XHR_STATE_JS)
        if done > before and active == 0:
            break
        if done == before and active == 0 and time.monotonic() - started > 5:
            print("    No AJAX request seen after Prikaži; reading the page as it is.")
            break
        time.sleep(0.2)
    else:
        raise TimeoutError(f"Popis salda analitike (sintetika): odgovor na „{SHOW_TEXT}“ nije stigao za {timeout:g} s.")
    end = time.monotonic() + 30
    while time.monotonic() < end and driver.execute_script(RESULT_JS)["loading"]:
        time.sleep(0.2)
    time.sleep(0.3)


def _amount(text: str | None, what: str) -> float:
    if text is None:
        raise LookupError(f"Popis salda analitike (sintetika): polje za „{what}“ nije pronađeno.")
    value = parse_amount(text) if text.strip() else 0.0
    if value is None:
        raise ValueError(f"Popis salda analitike (sintetika): „{text}“ ({what}) nije iznos.")
    return value


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 0.005


# --- a konto's card (individual entries) ---------------------------------------------------------


def shown_konta(driver: WebDriver) -> list[str]:
    """Konta whose header (link) is shown in the report table now."""
    return list(driver.execute_script(KONTO_BUTTONS_JS))


def open_konto(driver: WebDriver, konto: str, timeout: float = 45) -> str:
    """Click the header "Konto: <konto> - …" and wait for the card it opens. Returns the card's view name."""
    buttons = driver.execute_script(KONTO_BUTTONS_JS)
    if konto not in buttons:
        raise LookupError(f"Konto {konto} nije prikazano u tabeli (prikazana su: {', '.join(buttons) or 'nijedno'}).")
    button = buttons[konto]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    app_page._navigate(driver, button.click, f"Konto {konto}", timeout)
    return driver.execute_script(app_page.VIEW_JS) or ""


def read_card(driver: WebDriver, on_progress=None) -> dict:
    """The individual entries on the open card: {"kolone", "redovi": [{column: text}], "broj", "tabela",
    "duguje" / "potrazuje" / "datum": the column used for each (or "")}. The table is the visible one with a
    "Potražuje" or "Duguje" column, the one with most rows if there are several."""
    tables = [t for t in find_tables(driver) if t["visible"] and any(t["columns"])]
    def column(t, *names):
        return next((c for c in t["columns"] if app_page.normalize(c) in names), "")
    amounts = [t for t in tables if column(t, "potrazuje", "duguje")]
    if not amounts:
        found = "; ".join(f"{t['id']}: {', '.join(c for c in t['columns'] if c)}" for t in tables) or "nijedna"
        raise LookupError(f"Na kartici konta nije pronađena tabela sa kolonama Duguje / Potražuje (tabele: {found}).")
    t = max(amounts, key=lambda t: t["total"])
    rows = WDTable(driver, t["id"]).read(on_progress=on_progress)
    date = next((c for c in t["columns"] if app_page.normalize(c).startswith("datum")), "")
    return {"tabela": t["id"], "kolone": [c for c in t["columns"] if c], "redovi": rows, "broj": len(rows),
            "ukupno_u_tabeli": t["total"], "duguje": column(t, "duguje"), "potrazuje": column(t, "potrazuje"),
            "datum": date}


def back(driver: WebDriver, timeout: float = 45) -> None:
    """Click the card's back arrow (M28) and wait for Popis salda analitike (sintetika) again."""
    button = driver.execute_script(BACK_JS, BACK_ID)
    if button is None:
        raise LookupError(f"Strelica za povratak ({BACK_ID}) nije pronađena na kartici konta.")
    app_page._navigate(driver, button.click, "Povratak na popis salda", timeout)
    if not is_open(driver):
        raise LookupError(f"Posle povratka nije otvoren popis salda (sada: {app_page.view_name(driver)}).")


def card_amount(text: str) -> float:
    value = parse_amount(text) if (text or "").strip() else 0.0
    if value is None:
        raise ValueError(f"Kartica konta: „{text}“ nije iznos.")
    return value


def card_date(text: str) -> str:
    """"05.03.2026" / "5/3/2026" -> "2026-03-05" ("" if there is no date)."""
    m = DATE_RE.search(text or "")
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""
