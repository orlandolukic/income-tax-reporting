"""The financial order's items page (FINNALSTAVVIEW, HTML pasted 2026-10-07).

Below the items table, a form shows the selected item (it is refreshed by AJAX after a row is clicked);
on the right, the order's own fields. Ids are from the pasted page; a field whose id is missing is looked
up by its label ("lz<ID>" cell, e.g. "Datum plaćanja:") as a fallback.
"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from tim_automation.pages import app_page
from tim_automation.pages.wd_table import main_table

# (name used in conditions and results, element id, kind, label on the page). Kinds: text, number, date,
# bool (checkbox: "Da" / "Ne"), list (a select: its shown text), link (a link's text).
FORM_FIELDS = (
    ("Naziv konta", "ALIAS3", "text", ""),
    ("Datum plaćanja", "ALIAS9", "date", "Datum plaćanja:"),
    ("Dev. dug.", "I16", "number", "Dev. dug.:"),
    ("Dev. pot.", "I17", "number", "Dev. pot.:"),
    ("Devizna klauzula", "I7_1", "bool", "Devizna klauzula"),
    ("Devizna valuta", "I18", "text", "Devizna valuta:"),
    ("Vrsta kursa", "I19", "list", "Vrsta kursa:"),
    ("Kurs", "I30", "number", "Kurs:"),
    ("Org. jed.", "I20", "text", "Org. jed.:"),
    ("Naziv org. jed.", "I21", "text", ""),
    ("MPT", "I23", "text", "MPT:"),
    ("Naziv MPT", "I24", "text", ""),
    ("Opis", "I53", "text", "Opis:"),
    ("Vrs. prihoda/rashoda", "I49", "text", "Vrs.prihoda/rashoda:"),
    ("Naziv vrs. prihoda/rashoda", "I57", "text", ""),
    ("Ne zatvara se automatski", "I54_1", "bool", "Ne zatvara se automatski"),
)
# The same for every item: read once per page.
ORDER_FIELDS = (
    ("Nalog: dokument", "I32", "text", ""),
    ("Nalog: broj", "I67", "link", ""),
    ("Nalog: status", "I72", "text", "Status:"),
    ("Nalog: datum", "I71", "date", ""),
    ("Nalog: duguje", "I64", "number", ""),
    ("Nalog: potražuje", "I33", "number", ""),
    ("Nalog: saldo", "I34", "number", "Saldo:"),
)
LIST_OPTIONS = {"Vrsta kursa": ("Srednji", "Prodajni", "Kupovni", "Slobodni")}
# Fields of the form that repeat the table's columns: used to tell that the form shows the clicked item.
SYNC = (("Konto", "ALIAS2"), ("Duguje", "I14"), ("Potražuje", "I15"))

READ_JS = r"""
const read = (el, kind) => {
  if (!el) return null;
  if (kind === 'bool') return el.checked ? 'Da' : 'Ne';
  if (el.tagName === 'SELECT') return el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : '';
  if (el.tagName === 'A' || kind === 'link') return el.textContent.trim();
  return (el.value ?? el.textContent ?? '').trim();
};
const byLabel = (label) => {
  if (!label) return null;
  for (const cell of document.querySelectorAll('[id^="lz"], label')) {
    if (cell.textContent.trim() !== label) continue;
    if (cell.tagName === 'LABEL') return cell.querySelector('input');
    const id = cell.id.slice(2);
    return document.getElementById(id) || document.getElementsByName(id)[0] || null;
  }
  return null;
};
const out = {};
for (const [name, id, kind, label] of arguments[0]) {
  const value = read(document.getElementById(id) || byLabel(label), kind);
  out[name] = value === null ? '' : value;
}
return out;
"""


def read_fields(driver: WebDriver, fields) -> dict[str, str]:
    driver.switch_to.default_content()
    return driver.execute_script(READ_JS, [list(f) for f in fields])


def read_order(driver: WebDriver) -> dict[str, str]:
    return read_fields(driver, ORDER_FIELDS)


def _form_shows(driver: WebDriver, row: dict) -> bool:
    shown = driver.execute_script(
        "return arguments[0].map((id) => { const e = document.getElementById(id); return e ? e.value : null; });",
        [i for _, i in SYNC])
    for (column, _), value in zip(SYNC, shown):
        if value is None:
            continue  # field not on the page: nothing to compare
        wanted = row.get(column, "")
        if column == "Konto":
            if value.strip() != wanted.strip():
                return False
        elif (app_page.parse_amount(value) or 0) != (app_page.parse_amount(wanted) or 0):
            return False
    return True


def select_item(driver: WebDriver, row: dict, timeout: float = 10) -> bool:
    """Click the item with this R.b. (scrolling the table if needed) and wait until the form below shows
    it. False if the form did not show the same Konto / Duguje / Potražuje in time."""
    driver.switch_to.default_content()
    table = main_table(driver)
    c = table.columns.index("R.b.")
    find = lambda: driver.execute_script(app_page.FIND_ROW_JS, table.id, c, row["R.b."])
    n = find()
    if n < 0:
        for _ in table._pages():
            n = find()
            if n >= 0:
                break
    if n < 0:
        raise LookupError(f"Stavka R.b. {row['R.b.']} nije pronađena u tabeli.")
    cell = driver.find_element(By.ID, f"{table.id}_{n}_{c}")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", cell)
    cell.click()
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script(app_page.SELECTED_JS, f"{table.id}_{n}"))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app_page.wait_until_idle(driver)
        if _form_shows(driver, row):
            time.sleep(0.2)  # let the rest of the form settle
            return True
        time.sleep(0.2)
    return False


def read_item(driver: WebDriver, row: dict) -> tuple[dict[str, str], bool]:
    """Select the item and read its form fields. Returns (fields, whether the form matched the item)."""
    ok = select_item(driver, row)
    return read_fields(driver, FORM_FIELDS), ok
