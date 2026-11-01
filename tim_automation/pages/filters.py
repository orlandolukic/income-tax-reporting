"""The "Napredni filteri" window of list pages (e.g. Maloprodaja > Izlazi).

The funnel button next to "Filter..." (`<button title="Napredni filteri" onclick="_T6(event)">`, id M20)
runs `addIframeFilter()` + `_JSL(..., 'M20', frame)`: the window is an iframe with a list (looper "I2")
of predefined filters. Filter row N (from 1) has:
- `zrl_N_I31` checkbox: the filter is on (each click is sent to the server by AJAX)
- `#zrl_N_I32` table ("racun", "magacin", "komitent") and `#zrl_N_I3` field label ("Dokument", ...)
- `zrl_N_I16` operator select (texts: Jednako ... Sadrži ... Između; dates/numbers: Jednako ... Između;
  lists: Je u listi / Nije u listi)
- value: `zrl_N_I17` text, `zrl_N_I18` number, `zrl_N_I19` date (from) + `zrl_N_I23` date (to, for
  "Između"), `zrl_N_I39` multi-select (hidden, shown with jquery.multiselect), `zrl_N_I20` Da/Ne.
The button that applies the filters is not in the HTML we have; APPLY_TEXTS are the names tried.

A filter given to apply(): {"polje": "racun.Datum", "operator": "Između", "vrednost": "01/10/2026",
"do": "07/10/2026", "izbor": ["završeno", ...]}.
"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import Select, WebDriverWait

OPEN_TITLE = "Napredni filteri"
APPLY_TEXTS = ("Primeni", "Primeni filter", "Filtriraj", "Pretraži", "Traži", "Potvrdi", "Prihvati", "OK", "Ok", "U redu",
               "Izbor", "Izaberi")

ROWS_JS = r"""
const rows = [];
for (let n = 1; ; n++) {
  const label = document.getElementById('zrl_' + n + '_I3');
  if (!label) break;
  const table = document.getElementById('zrl_' + n + '_I32');
  const box = document.getElementsByName('zrl_' + n + '_I31').length
    ? [...document.getElementsByName('zrl_' + n + '_I31')].find((e) => e.type === 'checkbox') : null;
  rows.push({n, polje: (table ? table.textContent.trim() + '.' : '') + label.textContent.trim(),
             on: !!(box && box.checked)});
}
return rows;
"""
SET_VALUE_JS = """
const [name, value] = arguments;
const input = document.getElementsByName(name)[0];
input.focus();
input.value = value;
input.dispatchEvent(new Event('change', {bubbles: true}));
input.blur();
input.dispatchEvent(new Event('blur'));
return input.value;
"""
SET_LIST_JS = """
const [name, wanted] = arguments;
const select = document.getElementsByName(name)[0];
const missing = wanted.filter((w) => ![...select.options].some((o) => o.text.trim() === w));
if (missing.length) return {missing, options: [...select.options].map((o) => o.text.trim())};
[...select.options].forEach((o) => { o.selected = wanted.includes(o.text.trim()); });
if (window.jQuery) {
  const $s = window.jQuery(select);
  if ($s.multiselect) { try { $s.multiselect('reload'); } catch (e) {} }
  $s.trigger('change');
} else {
  select.dispatchEvent(new Event('change', {bubbles: true}));
}
return {missing: []};
"""
BUTTONS_JS = """
return [...document.querySelectorAll('button, a, input[type=button], input[type=submit]')]
  .filter((b) => b.offsetParent)
  .map((b) => (b.innerText || b.value || b.title || '').trim())
  .filter(Boolean);
"""


def _frames(driver: WebDriver) -> list:
    return driver.find_elements(By.TAG_NAME, "iframe")


def _settle(driver: WebDriver) -> None:
    """Each change is sent to the server (AJAX); give it a moment before the next one."""
    time.sleep(0.4)
    WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")


def apply(driver: WebDriver, filters: list[dict], timeout: float = 30) -> None:
    """Open "Napredni filteri" on the current list page, turn on exactly the given filters (all others
    off), set their operators and values, apply, and wait until the window is closed."""
    for f in filters:
        if isinstance(f.get("vrednost"), list) or isinstance(f.get("do"), list):
            raise ValueError(f"„{f['polje']}“: napredni filteri sajta primaju jednu vrednost, ne „svaki red“; "
                             "koristite podzadatke.")
    driver.switch_to.default_content()
    buttons = [b for b in driver.find_elements(By.CSS_SELECTOR, f"[title='{OPEN_TITLE}']") if b.is_displayed()]
    if not buttons:
        raise LookupError(f"Dugme „{OPEN_TITLE}“ nije pronađeno na ovoj stranici.")
    before = len(_frames(driver))
    buttons[0].click()
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: len(_frames(d)) > before)
    driver.switch_to.frame(_frames(driver)[-1])
    try:
        wait.until(lambda d: d.execute_script("return !!document.getElementById('zrl_1_I3')"))
        set_filters(driver, filters)
        _click_apply(driver)
    except Exception:
        _close_after_error(driver)
        driver.switch_to.default_content()
        raise
    driver.switch_to.default_content()
    end = time.monotonic() + timeout
    while time.monotonic() < end and len(_frames(driver)) > before:
        time.sleep(0.2)
    if len(_frames(driver)) > before:
        raise TimeoutError("Prozor „Napredni filteri“ se nije zatvorio posle primene.")


def set_filters(driver: WebDriver, filters: list[dict]) -> None:
    """Turn on exactly the given filters (all others off) and set their operators and values, in a filter
    form of the current document (the "Napredni filteri" window, or a form shown on the page itself, e.g.
    Finansije › Izveštaji › Popis salda analitike (sintetika))."""
    rows = {r["polje"]: r for r in driver.execute_script(ROWS_JS)}
    wanted = {f["polje"]: f for f in filters}
    unknown = [p for p in wanted if p not in rows]
    if unknown:
        raise LookupError(f"Filter „{', '.join(unknown)}“ ne postoji. Postoje: {', '.join(rows)}.")
    # Turn filters on/off first (the server may remember filters from before).
    for polje, row in rows.items():
        if row["on"] != (polje in wanted):
            _checkbox(driver, row["n"]).click()
            _settle(driver)
    for polje, f in wanted.items():
        _set_filter(driver, rows[polje]["n"], f)


def _close_after_error(driver: WebDriver) -> None:
    """Best effort: close the window so it does not cover the page for the next tasks."""
    try:
        for text in ("Zatvori", "Odustani", "Nazad"):
            for element in driver.find_elements(By.XPATH, f"//button[normalize-space()='{text}']"):
                if element.is_displayed():
                    element.click()
                    return
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass


def _checkbox(driver: WebDriver, n: int):
    return next(e for e in driver.find_elements(By.NAME, f"zrl_{n}_I31") if e.get_attribute("type") == "checkbox")


def _set_filter(driver: WebDriver, n: int, f: dict) -> None:
    label = f["polje"]
    operator = (f.get("operator") or "").strip()
    if operator:
        select = Select(driver.find_element(By.NAME, f"zrl_{n}_I16"))
        options = [o.text.strip() for o in select.options]
        if operator not in options:
            raise LookupError(f"Operator „{operator}“ ne postoji za „{label}“. Postoje: {', '.join(options)}.")
        if select.first_selected_option.text.strip() != operator:
            select.select_by_visible_text(operator)
            _settle(driver)
    value, to = str(f.get("vrednost") or ""), str(f.get("do") or "")
    names = {e.get_attribute("name"): e for e in driver.find_elements(By.CSS_SELECTOR, f"[name^='zrl_{n}_I']")}
    if f.get("izbor"):  # multi-select list
        result = driver.execute_script(SET_LIST_JS, f"zrl_{n}_I39", list(f["izbor"]))
        if result["missing"]:
            raise LookupError(f"„{', '.join(result['missing'])}“ ne postoji za „{label}“. "
                              f"Postoji: {', '.join(result['options'])}.")
    elif _visible(names.get(f"zrl_{n}_I20")) and value:  # Da / Ne
        Select(names[f"zrl_{n}_I20"]).select_by_visible_text(value)
    elif _visible(names.get(f"zrl_{n}_I19")):  # date from (and to)
        driver.execute_script(SET_VALUE_JS, f"zrl_{n}_I19", value)
        if operator == "Između":
            driver.execute_script(SET_VALUE_JS, f"zrl_{n}_I23", to)
    elif _visible(names.get(f"zrl_{n}_I18")):  # number
        driver.execute_script(SET_VALUE_JS, f"zrl_{n}_I18", value)
    elif _visible(names.get(f"zrl_{n}_I17")):  # text (and for "Između" the second one, I21)
        _type_text(driver, names[f"zrl_{n}_I17"], value)
        if operator == "Između" and _visible(names.get(f"zrl_{n}_I21")):
            _type_text(driver, names[f"zrl_{n}_I21"], to)
    _settle(driver)


def _type_text(driver: WebDriver, field, value: str) -> None:
    """Type into a text field like a user, then leave it. Some (e.g. konto) have an autocomplete list that
    can replace what was typed: then the value is set directly."""
    if (field.get_attribute("value") or "") == value:
        return
    field.click()
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(Keys.DELETE)
    field.send_keys(value, Keys.TAB)
    if (field.get_attribute("value") or "") != value:
        driver.execute_script(SET_VALUE_JS, field.get_attribute("name"), value)


def _visible(element) -> bool:
    return element is not None and element.get_attribute("type") != "hidden" and element.is_displayed()


def _click_apply(driver: WebDriver) -> None:
    for text in APPLY_TEXTS:
        for element in driver.find_elements(By.XPATH, f"//button[normalize-space()='{text}'] | //a[normalize-space()='{text}']"
                                                      f" | //input[@type='button' or @type='submit'][@value='{text}']"):
            if element.is_displayed():
                element.click()
                return
    found = driver.execute_script(BUTTONS_JS)
    raise LookupError("Dugme za primenu filtera nije pronađeno. Dugmad u prozoru: " + ", ".join(found))
