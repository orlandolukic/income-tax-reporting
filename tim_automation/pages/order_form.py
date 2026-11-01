"""New financial order on Finansije › Finansijski nalozi (FINNALVIEW; HTML pasted 2026-10-10).

The action bar has "Unos" (M23, AJAX), "Izmene", "Brisanje" and, hidden until "Unos" / "Izmene", "Sačuvaj" (M26)
and "Odustani" (M27). The order's form (readonly / disabled until then): Vrsta (select ALIAS2, its change is sent by
AJAX and the program fills in the order's type and number and loads Podvrsta's options), Podvrsta (select ALIAS3), Broj naloga (ALIAS4 "OK",
readonly) + its number (ALIAS5 "36", readonly), Datum (ALIAS6, mask DD/MM/YYYY), Broj dokumenta (ALIAS7, at most
25 characters), Opis (textarea ALIAS8). Fields are found by id, else by their label ("lz<ID>" cell).
"""
import re
import time
from datetime import date, datetime

from selenium.common.exceptions import (NoAlertPresentException, StaleElementReferenceException,
                                        TimeoutException, UnexpectedAlertPresentException)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select, WebDriverWait

from tim_automation.pages import app_page, items_page
from tim_automation.pages.wd_table import main_table

VIEW = "FINNALVIEW"
MENU_PATH = "Finansije > Finansijski nalozi"

# Options of "Vrsta" as on the page.
VRSTE = (
    "Izvodi", "Blagajna", "Zarade", "Veleprodaja - ulazi", "Veleprodaja - izlazi", "Veleprodaja - nivelacije",
    "Proizvodnja - ulazi", "Proizvodnja - izlazi", "Maloprodaja - ulazi", "Maloprodaja - izlazi",
    "Maloprodaja - nivelacije", "Troškovi", "Avansni računi dobavljača", "Avansni računi kupaca", "Osnovna sredstva",
    "Kursne razlike", "Devizni izvodi", "PDV Obračun", "Odobrenja/zaduženja izlaz", "Odobrenja/zaduženja ulaz",
    "Razgraničeni PDV", "Službeni putevi", "Uplate kredita", "Početno stanje", "Izlazni računi - direktan unos u KIR",
    "Ostala knjiženja",
)
DOCUMENT_MAX = 25

# (name, id, kind, label) as in items_page.read_fields.
FIELDS = (
    ("Vrsta", "ALIAS2", "list", "Vrsta:"),
    ("Podvrsta", "ALIAS3", "list", "Podvrsta:"),
    ("Tip naloga", "ALIAS4", "text", "Broj naloga:"),
    ("Broj naloga", "ALIAS5", "text", ""),
    ("Datum", "ALIAS6", "date", "Datum:"),
    ("Broj dokumenta", "ALIAS7", "text", "Broj dokumenta:"),
    ("Opis", "ALIAS8", "text", "Opis:"),
)
_BY_NAME = {f[0]: f for f in FIELDS}
# Buttons: their user class on the page, id, text.
BUTTONS = {"Unos": ("btnUnos", "M23"), "Sačuvaj": ("btnSave", "M26"), "Odustani": ("btnCancel", "M27"),
           "Brisanje": ("btnBrisanje", "M25")}
# "Obriši nalog ako postoji": how long the list may take to show the result of "Filter..." (a big list is slow), and
# the only status in which an order can be deleted.
FILTER_TIMEOUT = 45
DELETABLE = "u pripremi"

_FIND_JS = r"""
const [id, label] = arguments;
let el = document.getElementById(id);
if (!el && label) {
  for (const cell of document.querySelectorAll('[id^="lz"]')) {
    if (cell.textContent.trim() === label) { el = document.getElementById(cell.id.slice(2)); break; }
  }
}
return el;
"""
_BUTTON_JS = r"""
const [cls, id, text] = arguments;
const shown = (b) => b && b.offsetParent !== null && getComputedStyle(b).visibility !== 'hidden'
  && !(b.closest('table') && getComputedStyle(b.closest('table')).visibility === 'hidden');
const all = [...document.querySelectorAll('button')];
const b = document.querySelector('button.' + cls) || document.getElementById(id)
  || all.find((x) => x.textContent.trim() === text);
return b ? [b, shown(b)] : [null, false];
"""


def normalize_date(value) -> str:
    """A date as the site's mask wants it: DD/MM/YYYY. Accepts 31/10/2026, 31.10.2026(.), 31-10-2026, 2026-10-31,
    31102026, 1.9.2026, and date / datetime objects."""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    text = str(value or "").strip().rstrip(".")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", text)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[./\- ]\s*(\d{1,2})[./\- ]\s*(\d{4})", text) or re.fullmatch(r"(\d{2})(\d{2})(\d{4})", text)
        if not m:
            raise ValueError(f"Datum „{value}“ nije u obliku DD/MM/GGGG.")
        d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d)).strftime("%d/%m/%Y")
    except ValueError:
        raise ValueError(f"Datum „{value}“ ne postoji.") from None


def _field(driver: WebDriver, name: str):
    _, id_, _, label = _BY_NAME[name]
    el = driver.execute_script(_FIND_JS, id_, label)
    if el is None:
        raise RuntimeError(f"Polje „{name}“ nije pronađeno na stranici finansijskog naloga.")
    return el


def _button(driver: WebDriver, text: str):
    cls, id_ = BUTTONS[text]
    return driver.execute_script(_BUTTON_JS, cls, id_, text)


def editing(driver: WebDriver) -> bool:
    """Whether the form is open for entry ("Sačuvaj" is shown)."""
    return bool(_button(driver, "Sačuvaj")[1])


def read(driver: WebDriver) -> dict[str, str]:
    return items_page.read_fields(driver, FIELDS)


def _alert_text(driver: WebDriver) -> str:
    try:
        alert = driver.switch_to.alert
    except NoAlertPresentException:
        return ""
    text = alert.text
    alert.accept()
    return text


def _site_message(e: UnexpectedAlertPresentException) -> str:
    # Selenium closes the site's message box when a command meets it and only reports its text here.
    return (getattr(e, "alert_text", None) or "").strip() or "(poruka bez teksta)"


def _wait(driver: WebDriver, condition, what: str, timeout: float = 20) -> None:
    """Wait for `condition`; a message box from the site (alert) ends the wait with its text as the error."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if condition():
                return
        except UnexpectedAlertPresentException as e:
            raise RuntimeError(f"{what}: sajt je javio „{_site_message(e)}“.") from None
        message = _alert_text(driver)
        if message:
            raise RuntimeError(f"{what}: sajt je javio „{message.strip()}“.")
        time.sleep(0.2)
    raise TimeoutError(f"{what}: nije završeno za {timeout:g} s.")


_OPTIONS_JS = _FIND_JS.replace("return el;", "return el ? [...el.options].map((o) => o.text.trim()) : null;")


def podvrste(driver: WebDriver) -> list[str]:
    """The options Podvrsta shows now (they depend on Vrsta). Read in one script: the program replaces the options
    while it loads them, so element references to them would go stale."""
    _, id_, _, label = _BY_NAME["Podvrsta"]
    options = driver.execute_script(_OPTIONS_JS, id_, label)
    if options is None:
        raise RuntimeError("Polje „Podvrsta“ nije pronađeno na stranici finansijskog naloga.")
    return options


def _settle(driver: WebDriver, timeout: float = 10) -> dict[str, str]:
    """After an AJAX change (e.g. Vrsta): wait until the form stops changing; returns what it shows."""
    app_page.wait_until_idle(driver, timeout)
    previous, same, end = None, 0, time.monotonic() + timeout
    while time.monotonic() < end:
        message = _alert_text(driver)
        if message:
            raise RuntimeError(f"Sajt je javio „{message.strip()}“.")
        try:
            current = read(driver)
            current["_podvrste"] = "|".join(podvrste(driver))
        except UnexpectedAlertPresentException as e:
            raise RuntimeError(f"Sajt je javio „{_site_message(e)}“.") from None
        same = same + 1 if current == previous else 0
        if same >= 3:
            break
        previous = current
        time.sleep(0.2)
    return previous or read(driver)


def start_new(driver: WebDriver) -> None:
    """Click "Unos" and wait until the form can be filled in."""
    driver.switch_to.default_content()
    button, shown = _button(driver, "Unos")
    if button is None:
        raise RuntimeError("Dugme „Unos“ nije pronađeno na stranici finansijskih naloga.")
    if not editing(driver):
        driver.execute_script("arguments[0].click()", button)
    _wait(driver, lambda: editing(driver) and _field(driver, "Vrsta").is_enabled(), "Unos")


def _choose(driver: WebDriver, name: str, text: str, attempts: int = 3) -> str:
    for attempt in range(attempts):  # the options may be replaced while we look at them (AJAX)
        try:
            return _choose_once(driver, name, text)
        except StaleElementReferenceException:
            if attempt == attempts - 1:
                raise
            time.sleep(0.3)


def _choose_once(driver: WebDriver, name: str, text: str) -> str:
    select = Select(_field(driver, name))
    wanted = app_page.normalize(text)
    for option in select.options:
        if app_page.normalize(option.text) == wanted:
            if not option.is_selected():
                select.select_by_visible_text(option.text)
            elif name == "Vrsta" and not read(driver).get("Tip naloga"):
                # Already chosen (e.g. the default after "Unos") but the program hasn't given the order its type
                # and number: send the change it would get from a choice.
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}))", select._el)
            return option.text.strip()
    options = ", ".join(o.text.strip() for o in select.options)
    raise ValueError(f"{name} „{text}“ ne postoji. Ponuđeno: {options}.")


def _type(driver: WebDriver, name: str, text: str) -> None:
    type_into(_field(driver, name), text)


def type_into(el, text: str) -> None:
    """Replace the field's text by typing (so the page's key handlers and masks see it)."""
    el.click()
    el.send_keys(Keys.CONTROL, "a")
    el.send_keys(Keys.DELETE)
    if text:
        el.send_keys(text)


def type_date(driver: WebDriver, value: str, log=print) -> None:
    set_date(driver, _field(driver, "Datum"), value, log)


def set_date(driver: WebDriver, el, value: str, log=print, what: str = "Datum") -> None:
    """Type the date through the site's input mask (DD/MM/YYYY). If the mask doesn't end up with the date,
    try the digits only (a mask that adds the "/" itself), then set it directly."""
    for attempt, text in (("with /", value), ("digits only", value.replace("/", ""))):
        type_into(el, text)
        driver.execute_script("arguments[0].blur()", el)
        time.sleep(0.2)
        shown = (el.get_attribute("value") or "").strip()
        if shown == value:
            if attempt != "with /":
                log(f"{what} typed as {attempt}")
            return
    log(f"{what}: the date mask did not take {value!r} (shows {shown!r}); setting it directly")
    driver.execute_script(
        "const e = arguments[0]; e.value = arguments[1];"
        "for (const t of ['input', 'change', 'blur']) e.dispatchEvent(new Event(t, {bubbles: true}));", el, value)
    if (el.get_attribute("value") or "").strip() != value:
        raise RuntimeError(f"{what} „{value}“ nije upisan (polje pokazuje „{el.get_attribute('value')}“).")


def finish(driver: WebDriver, save: bool) -> None:
    """Click "Sačuvaj" (or "Odustani") and wait until the form is closed again."""
    text = "Sačuvaj" if save else "Odustani"
    button, shown = _button(driver, text)
    if button is None or not shown:
        raise RuntimeError(f"Dugme „{text}“ nije prikazano.")
    driver.execute_script("arguments[0].click()", button)
    _wait(driver, lambda: not editing(driver), text, timeout=30)
    app_page.wait_until_idle(driver)


def create(driver: WebDriver, vrsta: str, datum: str, podvrsta: str = "", dokument: str = "", opis: str = "",
           save: bool = True, log=print) -> dict:
    """Fill in a new order and save it (or cancel, with save=False). Returns the form as shown afterwards
    (with the order's type and number the program gave it)."""
    datum = normalize_date(datum)
    if len(dokument) > DOCUMENT_MAX:
        raise ValueError(f"Broj dokumenta može imati najviše {DOCUMENT_MAX} znakova (ima {len(dokument)}).")
    start_new(driver)
    try:
        filled = _fill(driver, vrsta, datum, podvrsta, dokument, opis, log)
        finish(driver, save)
    except Exception:
        # Leave the page as it was (not half-filled) for the next row / task.
        try:
            if editing(driver):
                log("Cancelling the unfinished order (Odustani)")
                finish(driver, False)
        except Exception as e:
            log(f"Could not cancel the form: {e}")
        raise
    return {"popunjeno": filled, "posle": read(driver)}


def _fill(driver: WebDriver, vrsta: str, datum: str, podvrsta: str, dokument: str, opis: str, log) -> dict:
    chosen = _choose(driver, "Vrsta", vrsta)
    # Choosing Vrsta makes the program load Podvrsta's options (and the order's type and number): wait for that.
    shown = _settle(driver)
    options = podvrste(driver)
    log(f"Vrsta {chosen}: order {shown.get('Tip naloga')} {shown.get('Broj naloga')}; Podvrsta options: {options}")
    if podvrsta:
        _choose(driver, "Podvrsta", podvrsta)
        _settle(driver)
    type_date(driver, datum, log)
    _type(driver, "Broj dokumenta", dokument)
    _type(driver, "Opis", opis)
    driver.execute_script("arguments[0].blur()", _field(driver, "Opis"))
    filled = read(driver)
    if filled.get("Datum") != datum:
        raise RuntimeError(f"Datum na obrascu je „{filled.get('Datum')}“, a trebalo je „{datum}“.")
    log(f"Filled in: {filled}")
    return filled


# --- "Obriši nalog ako postoji" -------------------------------------------------------------------------------

_ROW_NUMBERS_JS = r"""
const id = arguments[0];
const pattern = new RegExp('^' + id + '_(\\d+)$');
return [...document.querySelectorAll('#' + id + '_TB > tbody > tr')]
  .filter((row) => pattern.test(row.id) && row.style.display !== 'none' && row.innerText.trim())
  .map((row) => {
    const n = row.id.match(pattern)[1];
    const cells = [];
    for (let c = 0; ; c++) {
      const cell = document.getElementById(id + '_' + n + '_' + c);
      if (!cell) break;
      cells.push(cell.innerText.trim());
    }
    const first = [...row.querySelectorAll('[id^="' + id + '_' + n + '_"]')].find((c) => c.innerText.trim());
    return [Number(n), first ? first.id : null, row.innerText.replace(/\s+/g, ' ').trim(), cells];
  });
"""


def _filtered_rows(driver: WebDriver, table, dokument: str, log) -> list:
    """Search the list for the document number ("Filter...") and wait until it shows the result: every shown row
    has the number, or the list is empty. The site filters on the server; a big list can take a while."""
    if not app_page.apply_filter(driver, table, dokument):
        raise RuntimeError("Na stranici finansijskih naloga nema polja „Filter...“ za traženje naloga.")
    wanted = app_page.normalize(dokument)
    end = time.monotonic() + FILTER_TIMEOUT
    while True:
        if not table.loading():
            rows = driver.execute_script(_ROW_NUMBERS_JS, table.id)
            if rows and all(wanted in app_page.normalize(text) for _, _, text, _ in rows):
                return rows
            if not rows and table.total == 0:
                return []
        if time.monotonic() > end:
            raise RuntimeError(f"Lista naloga za {FILTER_TIMEOUT} s nije prikazala rezultat pretrage „{dokument}“ "
                               f"(prikazano {table.total} redova). Nalog nije obrisan.")
        time.sleep(0.3)


def find_orders(driver: WebDriver, vrsta: str, dokument: str, log=print) -> list[dict]:
    """Orders of this Vrsta with exactly this Broj dokumenta: the list is searched by the document number, then each
    row with exactly that number is clicked and the form below is read (it shows Vrsta and Broj dokumenta)."""
    table = main_table(driver)
    rows = _filtered_rows(driver, table, dokument, log)
    columns = [app_page.normalize(c) for c in table.columns]
    status_at = columns.index("status") if "status" in columns else None
    wanted = app_page.normalize(dokument)
    found = []
    for n, cell_id, text, cells in rows:
        # The search finds the number anywhere in the row ("ISPR-1" is also in "ISPR-10"): only an exact cell counts.
        if cell_id is None or wanted not in (app_page.normalize(c) for c in cells):
            continue
        shown = _select_row(driver, table.id, n, cell_id)
        same = _is_order(shown, vrsta, dokument)
        log(f"Row {text!r}: {shown.get('Vrsta')} / {shown.get('Broj dokumenta')!r}" + (" - matches" if same else ""))
        if same:
            status = cells[status_at] if status_at is not None and status_at < len(cells) else ""
            found.append({"red": n, "celija": cell_id, "tekst": text, "status": status,
                          "naziv": f"{shown.get('Tip naloga', '')} {shown.get('Broj naloga', '')}".strip()})
    return found


def _deletable(order: dict) -> bool:
    """Only an order "u pripremi" can be deleted (the Status column, else the row's text)."""
    where = order["status"] or order["tekst"]
    return DELETABLE in app_page.normalize(where)


def _is_order(shown: dict, vrsta: str, dokument: str) -> bool:
    return (app_page.normalize(shown.get("Vrsta", "")) == app_page.normalize(vrsta)
            and shown.get("Broj dokumenta", "").strip() == dokument.strip())


def _select_row(driver: WebDriver, table_id: str, n: int, cell_id: str) -> dict[str, str]:
    """Click row n of the list and return the order form once it shows that row."""
    cell = driver.find_element(By.ID, cell_id)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", cell)
    cell.click()
    WebDriverWait(driver, 20).until(lambda d: d.execute_script(app_page.SELECTED_JS, f"{table_id}_{n}"))
    time.sleep(0.5)  # the form below is loaded by AJAX after the click
    return _settle(driver)


def _accept_dialogs(driver: WebDriver, log, first_wait: float = 5) -> list[str]:
    """Confirm the browser's question(s) ("Da li ste sigurni…") with OK. Returns their texts."""
    texts, wait = [], first_wait
    while len(texts) < 3:
        try:
            WebDriverWait(driver, wait).until(expected_conditions.alert_is_present())
        except TimeoutException:
            break
        alert = driver.switch_to.alert
        texts.append((alert.text or "").strip())
        log(f"Site asks {texts[-1]!r}: OK")
        alert.accept()
        wait = 1.5
    return texts


def delete_selected(driver: WebDriver, log=print) -> list[str]:
    """Click "Brisanje" for the selected order and confirm the browser's question with OK."""
    button, shown = _button(driver, "Brisanje")
    if button is None or not shown:
        raise RuntimeError("Dugme „Brisanje“ nije prikazano.")
    # A WebDriver click (not a script): it returns while the site's confirm() is open, so it can be accepted.
    button.click()
    texts = _accept_dialogs(driver, log)
    if not texts:
        log("No confirmation was asked")
    app_page.wait_until_idle(driver)
    time.sleep(0.5)
    app_page.wait_until_idle(driver)
    return texts


def delete_existing(driver: WebDriver, vrsta: str, dokument: str, log=print) -> list[str]:
    """Delete the order of this Vrsta with this Broj dokumenta, if there is one and it is "u pripremi" (in another
    state, or more than one: error, nothing is deleted). Returns the deleted order (["OK 35"]) or []."""
    dokument = dokument.strip()
    if not dokument:
        raise ValueError("„Obriši nalog ako postoji“ traži broj dokumenta (po njemu se nalog traži).")
    driver.switch_to.default_content()
    if editing(driver):
        finish(driver, False)
    table = main_table(driver)
    try:
        found = find_orders(driver, vrsta, dokument, log)
        if not found:
            log(f"No {vrsta} order with document {dokument!r}: nothing to delete")
            return []
        if len(found) > 1:
            raise RuntimeError(f"Postoji {len(found)} naloga vrste „{vrsta}“ sa brojem dokumenta „{dokument}“ "
                               f"({', '.join(f['naziv'] for f in found)}); nijedan nije obrisan.")
        order = found[0]
        if not _deletable(order):
            status = order["status"] or "nije „u pripremi“"
            raise RuntimeError(f"Nalog {order['naziv']} ({dokument}) je „{status}“; obrisati se može samo nalog „u "
                               f"pripremi“. Nalog nije obrisan i novi nije napravljen.")
        # Select it again (other rows were clicked while looking) and check the form once more before deleting.
        shown = _select_row(driver, table.id, order["red"], order["celija"])
        if not _is_order(shown, vrsta, dokument) or not driver.execute_script(app_page.SELECTED_JS, f"{table.id}_{order['red']}"):
            raise RuntimeError(f"Nalog {order['naziv']} nije mogao ponovo da se izabere; nije obrisan.")
        log(f"Deleting order {order['naziv']} ({vrsta}, {dokument!r})")
        texts = delete_selected(driver, log)
        if find_orders(driver, vrsta, dokument, log):
            site = f" (sajt: „{' / '.join(texts)}“)" if texts else ""
            raise RuntimeError(f"Nalog {order['naziv']} nije obrisan{site}.")
        log(f"Order {order['naziv']} deleted")
        return [order["naziv"]]
    finally:
        try:
            app_page.apply_filter(driver, table, "")  # the whole list again
        except Exception as e:
            log(f"Could not clear the filter: {e}")
