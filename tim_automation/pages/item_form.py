"""New item of a financial order on its items page (FINNALSTAVVIEW, "Fin.nalozi > Stavke"; form HTML pasted 2026-10-10).

The item form (readonly / disabled until "Unos"): Konto (ALIAS2, autocomplete; its change is sent by AJAX and the
program fills in the account's name ALIAS3), Analitička šifra (ALIAS5 → name ALIAS6), Datum (ALIAS8) and Datum
plaćanja (ALIAS9) with the DD/MM/YYYY mask, Dokument (ALIAS10, at most 25 characters), Duguje (I14) / Potražuje (I15)
and Dev. dug. (I16) / Dev. pot. (I17) with a number mask ("+9 999 999 999,99"), "Devizna klauzula" checkbox (I7_1),
Devizna valuta (I18, autocomplete), Vrsta kursa (select I19, AJAX), Kurs (I30), Org. jed. (I20 → name I21), MPT
(I23 → name I24), Opis (textarea I53). "Nudi podatke sa prethodne stavke" (I56, checked) makes "Unos" start from
the previous item's values. The action bar was not in the pasted HTML: the buttons are found like on the order page
(classes btnUnos / btnSave / btnCancel, else by text).
"""
import re
import time

from selenium.common.exceptions import UnexpectedAlertPresentException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import Select

from tim_automation.pages import app_page, items_page, order_form

VIEW = "FINNALSTAVVIEW"
DOCUMENT_MAX = 25
RATES = ("Srednji", "Prodajni", "Kupovni", "Slobodni")  # Vrsta kursa

# (name, id, kind, label) as in items_page.read_fields.
FIELDS = (
    ("Konto", "ALIAS2", "text", "Konto:"),
    ("Naziv konta", "ALIAS3", "text", ""),
    ("Analitička šifra", "ALIAS5", "text", "Analitička šifra:"),
    ("Analitika", "ALIAS6", "text", ""),
    ("Datum", "ALIAS8", "date", ""),
    ("Datum plaćanja", "ALIAS9", "date", "Datum plaćanja:"),
    ("Dokument", "ALIAS10", "text", ""),
    ("Duguje", "I14", "number", "Duguje:"),
    ("Potražuje", "I15", "number", "Potražuje:"),
    ("Devizna klauzula", "I7_1", "bool", "Devizna klauzula"),
    ("Devizna valuta", "I18", "text", "Devizna valuta:"),
    ("Dev. dug.", "I16", "number", "Dev. dug.:"),
    ("Dev. pot.", "I17", "number", "Dev. pot.:"),
    ("Vrsta kursa", "I19", "list", "Vrsta kursa:"),
    ("Kurs", "I30", "number", "Kurs:"),
    ("Org. jed.", "I20", "text", "Org. jed.:"),
    ("Naziv org. jed.", "I21", "text", ""),
    ("MPT", "I23", "text", "MPT:"),
    ("Naziv MPT", "I24", "text", ""),
    ("Opis", "I53", "text", "Opis:"),
)
_BY_NAME = {f[0]: f for f in FIELDS}
# Code fields the program looks up after a change, and the field it writes the name into (None: no name shown).
CODES = {"Konto": "Naziv konta", "Analitička šifra": "Analitika", "Org. jed.": "Naziv org. jed.", "MPT": "Naziv MPT",
         "Devizna valuta": None}
DECIMALS = {"Duguje": 2, "Potražuje": 2, "Dev. dug.": 6, "Dev. pot.": 6, "Kurs": 6}
BUTTONS = {"Unos": ("btnUnos", ""), "Sačuvaj": ("btnSave", ""), "Odustani": ("btnCancel", "")}

# The jQuery UI autocomplete list shown under a code field: click the entry for exactly this code, if there is one.
_PICK_JS = r"""
const code = arguments[0].trim().toLowerCase();
for (const li of document.querySelectorAll('ul.ui-autocomplete li')) {
  if (li.offsetParent === null) continue;
  const text = li.textContent.trim().toLowerCase();
  if (text === code || (text.startsWith(code) && /^[\s\-–:|]/.test(text.slice(code.length)))) return li;
}
return null;
"""
_CLOSE_MENUS_JS = "for (const ul of document.querySelectorAll('ul.ui-autocomplete')) ul.style.display = 'none';"
_OCC_JS = "const e = document.querySelector('input[name=\"_I2_OCC\"]'); return e ? Number(e.value) : null;"


def _field(driver: WebDriver, name: str):
    _, id_, _, label = _BY_NAME[name]
    el = driver.execute_script(order_form._FIND_JS, id_, label)
    if el is None:
        raise RuntimeError(f"Polje „{name}“ nije pronađeno na stranici stavki naloga.")
    return el


def _button(driver: WebDriver, text: str):
    cls, id_ = BUTTONS[text]
    return driver.execute_script(order_form._BUTTON_JS, cls, id_, text)


def editing(driver: WebDriver) -> bool:
    return bool(_button(driver, "Sačuvaj")[1])


def read(driver: WebDriver) -> dict[str, str]:
    return items_page.read_fields(driver, FIELDS)


def _open(el) -> bool:
    return el.is_enabled() and not el.get_attribute("readonly")


def to_number(value, name: str) -> float:
    """1234.5, "1234.5", "1.234,50", "1 234,50", "-12,3", "--12,3" (= 12,3) -> float."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(" ", "")
    # Signs in front, e.g. "-" + a value from another task that is itself negative: "--50,00" = 50.
    sign = 1
    while text[:1] in ("-", "+"):
        sign, text = (-sign if text[0] == "-" else sign), text[1:]
    if not text:
        raise ValueError(f"{name}: „{value}“ nije broj.")
    return sign * _unsigned(text, value, name)


def _unsigned(text: str, value, name: str) -> float:
    number = app_page.parse_amount(text) if "," in text else None
    if number is None:
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"{name}: „{value}“ nije broj.") from None
    return number


def _number_text(number: float, decimals: int) -> str:
    text = f"{number:.{decimals}f}"
    while text.endswith("0") and len(text.split(".")[1]) > 2:  # 1,500000 -> 1,50
        text = text[:-1]
    return text.replace(".", ",")


def _settle(driver: WebDriver, timeout: float = 10) -> dict[str, str]:
    """After an AJAX change: wait until the form stops changing; returns what it shows."""
    app_page.wait_until_idle(driver, timeout)
    previous, same, end = None, 0, time.monotonic() + timeout
    while time.monotonic() < end:
        message = order_form._alert_text(driver)
        if message:
            raise RuntimeError(f"Sajt je javio „{message.strip()}“.")
        try:
            current = read(driver)
        except UnexpectedAlertPresentException as e:
            raise RuntimeError(f"Sajt je javio „{order_form._site_message(e)}“.") from None
        same = same + 1 if current == previous else 0
        if same >= 3:
            return current
        previous = current
        time.sleep(0.2)
    return previous or read(driver)


def start_new(driver: WebDriver) -> None:
    """Click "Unos" and wait until the form can be filled in."""
    driver.switch_to.default_content()
    button, _ = _button(driver, "Unos")
    if button is None:
        raise RuntimeError("Dugme „Unos“ nije pronađeno na stranici stavki naloga.")
    if not editing(driver):
        driver.execute_script("arguments[0].click()", button)
    order_form._wait(driver, lambda: editing(driver) and _open(_field(driver, "Konto")), "Unos")
    _settle(driver)


def set_code(driver: WebDriver, name: str, code: str, log=print) -> dict[str, str]:
    """Type a code (konto, analitika, ...) into its autocomplete field; the program then looks it up and shows
    its name. Picks the code's entry in the autocomplete list if it shows one."""
    el = _field(driver, name)
    if not _open(el):
        raise RuntimeError(f"Polje „{name}“ nije otvoreno za unos (možda ga ovaj konto ne koristi).")
    order_form.type_into(el, code)
    entry, end = None, time.monotonic() + 1.5
    while entry is None and time.monotonic() < end:
        time.sleep(0.25)
        entry = driver.execute_script(_PICK_JS, code)
    if entry is not None:
        log(f"{name}: picked {entry.text.strip()!r} from the list")
        entry.click()
    driver.execute_script("arguments[0].blur()", el)
    driver.execute_script(_CLOSE_MENUS_JS)
    shown = _settle(driver)
    value, label = shown.get(name, ""), CODES.get(name)
    if app_page.normalize(value) != app_page.normalize(code):
        raise RuntimeError(f"{name} „{code}“ nije prihvaćen (polje pokazuje „{value}“).")
    if label and not shown.get(label):
        raise RuntimeError(f"{name} „{code}“ nije pronađen: program nije prikazao naziv.")
    log(f"{name} {code}" + (f": {shown.get(label)}" if label else ""))
    return shown


def set_number(driver: WebDriver, name: str, number: float, log=print) -> None:
    el = _field(driver, name)
    if not _open(el):
        raise RuntimeError(f"Polje „{name}“ nije otvoreno za unos.")
    text = _number_text(number, DECIMALS[name])
    order_form.type_into(el, text)
    driver.execute_script("arguments[0].blur()", el)
    time.sleep(0.2)
    shown = el.get_attribute("value") or ""
    if app_page.parse_amount(shown) != round(number, DECIMALS[name]):
        log(f"{name}: the number mask did not take {text!r} (shows {shown!r}); setting it directly")
        driver.execute_script(
            "const e = arguments[0]; e.value = arguments[1];"
            "for (const t of ['input', 'change', 'blur']) e.dispatchEvent(new Event(t, {bubbles: true}));",
            el, text)
        shown = el.get_attribute("value") or ""
        if app_page.parse_amount(shown) != round(number, DECIMALS[name]):
            raise RuntimeError(f"{name} „{text}“ nije upisan (polje pokazuje „{shown}“).")
    _settle(driver)


def _set_text(driver: WebDriver, name: str, text: str) -> None:
    el = _field(driver, name)
    if not _open(el):
        raise RuntimeError(f"Polje „{name}“ nije otvoreno za unos.")
    order_form.type_into(el, text)
    driver.execute_script("arguments[0].blur()", el)


def _set_check(driver: WebDriver, name: str, on: bool) -> None:
    el = _field(driver, name)
    if el.is_selected() != on:
        if not el.is_enabled():
            raise RuntimeError(f"Polje „{name}“ nije otvoreno za unos.")
        driver.execute_script("arguments[0].click()", el)
    _settle(driver)


def _choose(driver: WebDriver, name: str, text: str) -> None:
    select = Select(_field(driver, name))
    for option in select.options:
        if app_page.normalize(option.text) == app_page.normalize(text):
            if not option.is_selected():
                select.select_by_visible_text(option.text)
                _settle(driver)
            return
    raise ValueError(f"{name} „{text}“ ne postoji. Ponuđeno: {', '.join(o.text.strip() for o in select.options)}.")


def order_number(driver: WebDriver) -> str:
    """The order whose items are shown ("Broj naloga" link, e.g. "OK00318")."""
    return items_page.read_order(driver).get("Nalog: broj", "")


def same_order(shown: str, wanted: str) -> bool:
    """ "OK00318" vs "OK 318", "OK318", "ok 00318": the same type letters and number."""
    def split(text):
        m = re.fullmatch(r"\s*([A-Za-zČĆŽŠĐčćžšđ]*)\s*0*(\d+)\s*", text or "")
        return (m.group(1).upper(), int(m.group(2))) if m else (text or "").strip().upper()
    return split(shown) == split(wanted)


def create(driver: WebDriver, values: dict, log=print) -> dict:
    """Add an item with these field values (names as in FIELDS; only those given are filled in, the rest stays as
    the program offers it) and save it. Returns {"popunjeno": the form before saving, "nalog": the order's
    fields afterwards (totals)}."""
    dokument = str(values.get("Dokument") or "")
    if len(dokument) > DOCUMENT_MAX:
        raise ValueError(f"Dokument može imati najviše {DOCUMENT_MAX} znakova (ima {len(dokument)}).")
    for name in ("Datum", "Datum plaćanja"):
        if values.get(name):
            values[name] = order_form.normalize_date(values[name])
    numbers = {name: to_number(values[name], name) for name in DECIMALS if values.get(name) not in (None, "")}
    count = driver.execute_script(_OCC_JS)
    start_new(driver)
    try:
        filled = _fill(driver, values, numbers, log)
        _save(driver, count, log)
    except Exception:
        try:
            if editing(driver):
                log("Cancelling the unfinished item (Odustani)")
                _click(driver, "Odustani")
                order_form._wait(driver, lambda: not editing(driver), "Odustani", timeout=30)
        except Exception as e:
            log(f"Could not cancel the form: {e}")
        raise
    return {"popunjeno": filled, "nalog": items_page.read_order(driver)}


def _click(driver: WebDriver, text: str) -> None:
    button, shown = _button(driver, text)
    if button is None or not shown:
        raise RuntimeError(f"Dugme „{text}“ nije prikazano.")
    driver.execute_script("arguments[0].click()", button)


def _fill(driver: WebDriver, values: dict, numbers: dict, log) -> dict:
    # In the order of the form: the account first (it decides which other fields are open).
    for name in ("Konto", "Analitička šifra"):
        if values.get(name):
            set_code(driver, name, str(values[name]).strip(), log)
    for name in ("Datum", "Datum plaćanja"):
        if values.get(name):
            order_form.set_date(driver, _field(driver, name), values[name], log, what=name)
    if values.get("Dokument") is not None and values.get("Dokument") != "":
        _set_text(driver, "Dokument", str(values["Dokument"]))
    # An amount given on one side only: the other side is 0 (not what the previous item had).
    if ("Duguje" in numbers) != ("Potražuje" in numbers):
        numbers.setdefault("Duguje", 0.0)
        numbers.setdefault("Potražuje", 0.0)
    for name in ("Duguje", "Potražuje"):
        if name in numbers:
            set_number(driver, name, numbers[name], log)
    if values.get("Devizna klauzula") is not None:
        _set_check(driver, "Devizna klauzula", bool(values["Devizna klauzula"]))
    if values.get("Devizna valuta"):
        set_code(driver, "Devizna valuta", str(values["Devizna valuta"]).strip(), log)
    for name in ("Dev. dug.", "Dev. pot."):
        if name in numbers:
            set_number(driver, name, numbers[name], log)
    if values.get("Vrsta kursa"):
        _choose(driver, "Vrsta kursa", str(values["Vrsta kursa"]))
    if "Kurs" in numbers:
        set_number(driver, "Kurs", numbers["Kurs"], log)
    for name in ("Org. jed.", "MPT"):
        if values.get(name):
            set_code(driver, name, str(values[name]).strip(), log)
    if values.get("Opis") is not None and values.get("Opis") != "":
        _set_text(driver, "Opis", str(values["Opis"]))
    filled = _settle(driver)
    for name in ("Datum", "Datum plaćanja"):
        if values.get(name) and filled.get(name) != values[name]:
            raise RuntimeError(f"{name} na obrascu je „{filled.get(name)}“, a trebalo je „{values[name]}“.")
    log(f"Filled in: {filled}")
    return filled


def _save(driver: WebDriver, count, log) -> None:
    """Click "Sačuvaj" and wait until the item is in the table (the row count grows) or the form is closed. If the
    program opens the next item right away, that one is cancelled."""
    _click(driver, "Sačuvaj")

    def done():
        now = driver.execute_script(_OCC_JS)
        return not editing(driver) or (count is not None and now is not None and now > count)

    order_form._wait(driver, done, "Sačuvaj", timeout=30)
    app_page.wait_until_idle(driver)
    if editing(driver):
        log("The program opened the next item after saving; cancelling it (Odustani)")
        _click(driver, "Odustani")
        order_form._wait(driver, lambda: not editing(driver), "Odustani", timeout=30)
    app_page.wait_until_idle(driver)
    now = driver.execute_script(_OCC_JS)
    log(f"Item saved (items: {count} -> {now})")
