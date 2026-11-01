"""The "Fiskalni računi / Način plaćanja" popup of Maloprodaja > Izlazi (Opcije > Fiskalni računi).

The option runs `_T10()` → `addIframe()` + `_JEM("C8", frame)`: the popup is an iframe with WebDev table
"I2" (one row per fiscal receipt: Broj računa, Vreme, Kartica, Ček, Virman, Vaučer, Mobilni, Drugo,
Gotovina, Ukupno) and read-only total fields under the amount columns (A2 Kartica, A3 Ček, A4 Virman,
A5 Vaučer, A8 Mobilni, A9 Drugo, A6 Gotovina, A7 Ukupno). "Zatvori" (M27) closes it.
"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from tim_automation.pages.app_page import format_amount, parse_amount, wait_until_idle
from tim_automation.pages.wd_table import main_table

MENU_TEXT = "Fiskalni računi"
LINK_JS = """
const link = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === arguments[0]);
return link ? link.getAttribute('href') : null;
"""
TITLE_JS = """
const t = document.querySelector('.A1_2') || document.querySelector('[class$="_2"]');
return t ? t.textContent.trim() : document.title;
"""
# Read-only amount fields outside the table, with the column they stand under (by position).
TOTALS_JS = r"""
const id = arguments[0];
const heads = [];
for (let c = 0; ; c++) {
  const t = document.getElementById(id + '_TITRES_' + c);
  if (!t) break;
  const r = t.closest('td').getBoundingClientRect();
  heads.push({title: t.textContent.trim(), left: r.left, right: r.right});
}
const table = document.getElementById(id + '_TB');
return [...document.querySelectorAll('input[type="text"]')]
  .filter((i) => i.readOnly && i.offsetParent && !table.contains(i) && /^[-+]?[\d.]+,\d+$/.test(i.value.trim()))
  .map((i) => {
    const r = i.getBoundingClientRect();
    const x = (r.left + r.right) / 2;
    const head = heads.find((h) => h.title && x >= h.left && x <= h.right);
    return {id: i.id || i.name, value: i.value.trim(), column: head ? head.title : ''};
  });
"""
# The field ids in the popup's HTML (2026-10-07), used if the position match fails.
TOTAL_IDS = {"A2": "Kartica", "A3": "Ček", "A4": "Virman", "A5": "Vaučer", "A8": "Mobilni", "A9": "Drugo",
             "A6": "Gotovina", "A7": "Ukupno"}


def _frames(driver: WebDriver) -> list:
    return driver.find_elements(By.TAG_NAME, "iframe")


NOT_AVAILABLE = f"Opcija „{MENU_TEXT}“ nije pronađena. Otvorite Maloprodaja › Izlazi (zadatak „Otvori stranicu“)."


def available(driver: WebDriver) -> bool:
    """Whether the current page has Opcije > Fiskalni računi."""
    driver.switch_to.default_content()
    href = driver.execute_script(LINK_JS, MENU_TEXT)
    return bool(href and href.startswith("javascript:"))


def read_fiscal_receipts(driver: WebDriver, timeout: float = 30) -> dict:
    """Open Opcije > Fiskalni računi for the selected document, read every receipt and the totals,
    then close the popup. Returns {"naslov", "kolone", "redovi", "broj", "ukupno", "zbir_odgovara"}."""
    driver.switch_to.default_content()
    href = driver.execute_script(LINK_JS, MENU_TEXT)
    if not href or not href.startswith("javascript:"):
        raise LookupError(NOT_AVAILABLE)
    before = len(_frames(driver))
    driver.execute_script(href[len("javascript:"):])
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: len(_frames(d)) > before)
    driver.switch_to.frame(_frames(driver)[-1])
    try:
        wait.until(lambda d: d.execute_script(
            "return document.readyState === 'complete' && !!document.querySelector('input[name$=\"_OCC\"]')"))
        wait_until_idle(driver)
        table = main_table(driver)
        title = driver.execute_script(TITLE_JS)
        columns = [c for c in table.columns if c]
        rows = table.read(0)
        totals = {}
        for field in driver.execute_script(TOTALS_JS, table.id):
            name = field["column"] or TOTAL_IDS.get(field["id"], field["id"])
            totals[name] = field["value"]
    finally:
        _close(driver, before)

    # Check that each total is the sum of its column (the site computes both).
    mismatches = []
    for name, value in totals.items():
        total = parse_amount(value)
        if name not in columns or total is None:
            continue
        cells = [parse_amount(r.get(name, "")) for r in rows]
        column_sum = sum(c for c in cells if c is not None)
        if abs(column_sum - total) > 0.005:
            mismatches.append(f"{name}: zbir redova {format_amount(column_sum)}, ukupno {value}")
    return {
        "naslov": title,
        "kolone": columns,
        "redovi": rows,
        "broj": len(rows),
        "ukupno": totals,
        "zbir_odgovara": not mismatches,
        "razlike": mismatches,
    }


def _close(driver: WebDriver, frames_before: int) -> None:
    """Click "Zatvori" in the popup and wait until it is gone."""
    try:
        buttons = [b for b in driver.find_elements(By.TAG_NAME, "button")
                   if b.text.strip() == "Zatvori" and b.is_displayed()]
        if buttons:
            buttons[0].click()
    finally:
        driver.switch_to.default_content()
    end = time.monotonic() + 10
    while time.monotonic() < end and len(_frames(driver)) > frames_before:
        time.sleep(0.2)
    if len(_frames(driver)) > frames_before:
        print("    The Fiskalni računi window did not close.")
