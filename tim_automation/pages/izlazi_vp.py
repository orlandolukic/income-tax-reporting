"""Veleprodaja › Izlazi ("Izlazni računi veleprodaje", form RACUNIZLAZVIEW like Maloprodaja › Izlazi; HTML pasted by
the user 2026-10-12) and the financial order an invoice was booked with.

List: WDTable `I2` (checkbox, Mag., Vrsta, Dokument, Datum, Komitent, Naziv, Prod. vred., Status; `_I2_OCC` = 323 for
SLAVIJA 2026), "Filter..." `M18`. Selecting a row fills the form below by AJAX: Vrsta `ALIAS2`, Dokument `ALIAS3`, Vrsta
knjiženja `I83`, Datum `ALIAS4`, Datum prometa `ALIAS5`, Komitent `ALIAS6` / `ALIAS7` + address `I38` / `I39`, Vrsta PDV
`I69`, Datum plaćanja `I70` (days) / `ALIAS9`, Tekući račun `ALIAS10`, Magacin `ALIAS12` / `I18`, Referent `I86`, Org. jed.
`I20` / `I21`, MPT `I23` / `I25`, Opis `I27`, Napomena `I74`, Uslovi plaćanja `I78`, totals Nabavna `I46`, Prod. vrednost
neto `I47`, PDV `I50`, sa PDV `I48`, Avansom `I59`, Prethodno uplaćeno `I88`, eFaktura data `tzI137`; items WDTable `I42`
(Roba, Naziv, Kol., Cena, Iznos); links looper `ALIAS17` ("Finansijski nalog: VIED00323", "KIR redni broj:340", ...).

The "Finansijski nalog" link opens FINNALVIEW (full page): order type `ALIAS4` + number `ALIAS5`, Vrsta `ALIAS2`, Datum
`ALIAS6`, Broj dokumenta `ALIAS7`, Opis `ALIAS8`, items WDTable `ALIAS9` (Konto, Analitka, Duguje, Potražuje; HTML pasted
2026-10-12), totals `I20` / `I21` / `I22`; "Nazad" `M33` returns to the invoices.
"""
import re
import time

from selenium.webdriver.remote.webdriver import WebDriver

from tim_automation import menu
from tim_automation.pages import app_page
from tim_automation.pages.app_page import parse_amount
from tim_automation.pages.wd_table import ROWS_JS, WDTable, find_tables

MENU_PATH = "Veleprodaja > Izlazi"
VIEW = "RACUNIZLAZVIEW"
TITLE = "Izlazni računi veleprodaje"
ORDER_VIEW = "FINNALVIEW"
ITEMS_TABLE = "I42"
ORDER_TABLE = "ALIAS9"

# (label, element name or id, kind): kind "text" (input / textarea value), "select" (shown option), "cell" (text).
FIELDS = [
    ("Vrsta", "ALIAS2", "select"), ("Dokument", "ALIAS3", "text"), ("Vrsta knjiženja", "I83", "select"),
    ("Datum", "ALIAS4", "text"), ("Datum prometa", "ALIAS5", "text"), ("Komitent", "ALIAS6", "text"),
    ("Naziv komitenta", "ALIAS7", "text"), ("Adresa", "I38", "text"), ("Mesto", "I39", "text"),
    ("Vrsta PDV", "I69", "select"), ("Rok plaćanja (dana)", "I70", "text"), ("Datum plaćanja", "ALIAS9", "text"),
    ("Tekući račun", "ALIAS10", "select"), ("Magacin", "ALIAS12", "text"), ("Naziv magacina", "I18", "text"),
    ("Referent", "I86", "text"), ("Org. jed.", "I20", "text"), ("Naziv org. jed.", "I21", "text"),
    ("MPT", "I23", "text"), ("Naziv MPT", "I25", "text"), ("Opis", "I27", "text"), ("Napomena", "I74", "text"),
    ("Uslovi plaćanja", "I78", "text"), ("Nabavna vrednost", "I46", "text"), ("Prod. vrednost (neto)", "I47", "text"),
    ("PDV", "I50", "text"), ("Prod. vrednost sa PDV", "I48", "text"), ("Avansom uplaćeno", "I59", "text"),
    ("Prethodno uplaćeno", "I88", "text"), ("Podaci za eFakturu", "tzI137", "cell"),
]
ORDER_FIELDS = [
    ("Vrsta", "ALIAS2", "select"), ("Podvrsta", "ALIAS3", "select"), ("Tip", "ALIAS4", "text"),
    ("Broj", "ALIAS5", "text"), ("Datum", "ALIAS6", "text"), ("Broj dokumenta", "ALIAS7", "text"),
    ("Opis", "ALIAS8", "text"), ("Duguje", "I20", "text"), ("Potražuje", "I21", "text"), ("Saldo", "I22", "text"),
]
FIELDS_JS = r"""
const out = {};
for (const [label, key, kind] of arguments[0]) {
  const e = document.getElementsByName(key)[0] || document.getElementById(key);
  if (!e) continue;
  if (kind === 'select') out[label] = e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : '';
  else if (kind === 'cell') out[label] = e.innerText.trim();
  else out[label] = (e.value || '').trim();
}
return out;
"""
TITLES_JS = """
const out = [];
for (let c = 0; ; c++) { const t = document.getElementById(arguments[0] + '_TITRES_' + c); if (!t) break;
  out.push(t.textContent.trim()); }
return out;
"""


def order_key(text: str) -> str:
    """ "VIED00323", "VIED 323", "vied323" -> "VIED323" ("" if it isn't letters + a number)."""
    m = re.fullmatch(r"\s*([A-Za-zČĆŽŠĐčćžšđ]+)\s*0*(\d+)\s*", text or "")
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else ""


def is_open(driver: WebDriver) -> bool:
    return app_page.view_name(driver) == VIEW and driver.execute_script(app_page.PAGE_TITLE_JS) == TITLE


def open_page(driver: WebDriver) -> None:
    """Open Veleprodaja › Izlazi (also when Maloprodaja › Izlazi, the same form, is shown)."""
    if is_open(driver):
        return
    print(f"Opening {MENU_PATH}...")
    app_page.open_menu_item(driver, menu.find(MENU_PATH))
    if not is_open(driver):
        raise LookupError(f"„{MENU_PATH}“ se nije otvorila (sada: {app_page.view_name(driver)}).")


def clear_filter(driver: WebDriver) -> None:
    field = [e for e in driver.find_elements(*app_page.FILTER) if e.is_displayed()]
    if field and field[0].get_attribute("value"):
        app_page.apply_filter(driver, app_page.main_table(driver), "")


def read_list(driver: WebDriver, on_progress=None) -> list[dict]:
    """All invoices of the list (the open year) as {column: text}."""
    clear_filter(driver)
    return app_page.main_table(driver).read(on_progress=on_progress)


def _table(driver: WebDriver, table_id: str) -> dict:
    """{kolone, redovi} of a WebDev table on the page (all rows; only the shown ones if it has no row count)."""
    if any(t["id"] == table_id for t in find_tables(driver)):
        table = WDTable(driver, table_id)
        rows = table.read()
        return {"kolone": [c for c in table.columns if c], "redovi": rows}
    columns = driver.execute_script(TITLES_JS, table_id)
    rows = [{c: v for c, v in zip(columns, r) if c} for r in driver.execute_script(ROWS_JS, table_id)]
    return {"kolone": [c for c in columns if c], "redovi": rows}


def read_invoice(driver: WebDriver, document: str) -> dict:
    """Select the invoice `document` in the list and read it: {"polja": FIELDS, "stavke": {kolone, redovi},
    "veze": {"Finansijski nalog": "VIED00323", ...}}."""
    app_page.select_row(driver, "Dokument", document)
    if not app_page.wait_details(driver, document):
        raise TimeoutError(f"Podaci računa {document} se nisu prikazali.")
    fields = driver.execute_script(FIELDS_JS, FIELDS)
    if fields.get("Dokument") != document:
        raise LookupError(f"Prikazan je račun {fields.get('Dokument')!r}, a ne {document}.")
    return {"polja": fields, "stavke": _table(driver, ITEMS_TABLE), "veze": app_page.linked_documents(driver)}


def read_order(driver: WebDriver, number: str) -> dict:
    """Open the selected invoice's "Finansijski nalog" link, read the order (fields + konta) and go back to the
    invoices. {"broj", "polja", "kolone", "redovi": [{Konto, Analitka, Duguje, Potražuje}], "duguje", "potrazuje"}."""
    try:
        view = app_page.open_link(driver, "Finansijski nalog")
        if view != ORDER_VIEW:
            raise LookupError(f"Link „Finansijski nalog“ je otvorio {view}, a ne finansijski nalog.")
        fields = driver.execute_script(FIELDS_JS, ORDER_FIELDS)
        shown = f"{fields.get('Tip', '')} {fields.get('Broj', '')}"
        if order_key(shown) and order_key(shown) != order_key(number):
            raise LookupError(f"Otvoren je nalog {shown.strip()}, a ne {number}.")
        table = _table(driver, ORDER_TABLE)
        amount = lambda r, c: parse_amount(r.get(c, "")) or 0.0
        return {"broj": number, "polja": fields, **table, "greska": "",
                "duguje": round(sum(amount(r, "Duguje") for r in table["redovi"]), 2),
                "potrazuje": round(sum(amount(r, "Potražuje") for r in table["redovi"]), 2)}
    finally:
        back_to_invoices(driver)


def back_to_invoices(driver: WebDriver) -> None:
    """From the order page (or anywhere else) back to Veleprodaja › Izlazi."""
    if is_open(driver):
        return
    if app_page.view_name(driver) == ORDER_VIEW:
        try:
            app_page.click_back(driver)
        except Exception as e:
            print(f"    Nazad from the order failed: {e}")
        time.sleep(0.2)
    if not is_open(driver):
        open_page(driver)
