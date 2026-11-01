"""Any page of the logged-in application: open pages from the main menu, describe what is on the
current page and search its main table.

Every application page has the main menu (`mnClk`). `mnClk(g, i, 0)` submits the whole page and the
server answers with the new page; `mnClk(g, i, 1)` opens it in an iframe instead. List pages (e.g.
Maloprodaja > Izlazi) have a "Filter..." field at the top: Enter runs the search on the server (AJAX)
and the main table then shows only matching rows.
"""
import time
import unicodedata

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from tim_automation.menu import MenuItem
from tim_automation.pages.wd_table import WDTable, find_tables, main_table

FILTER = (By.CSS_SELECTOR, "input[placeholder^='Filter']")
PAGE_TITLE_JS = """
const header = document.querySelector('.M29_2');
return header ? header.textContent.trim() : document.title.replace(/\\s*ErpX\\s*$/, '');
"""


def normalize(text: str) -> str:
    """Lowercase, no diacritics, "đ" as "dj", single spaces: for matching what the user typed."""
    text = " ".join(text.casefold().replace("đ", "dj").split())
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _page_replaced(driver: WebDriver) -> bool:
    try:
        return driver.execute_script("return !window.__timOldPage && document.readyState === 'complete'")
    except WebDriverException:  # the old page is unloading
        return False


def open_menu_item(driver: WebDriver, item: MenuItem, timeout: float = 45) -> dict:
    """Open a page from the main menu and wait until it has loaded. Returns describe_page()."""
    driver.switch_to.default_content()
    if not driver.execute_script("return typeof mnClk === 'function'"):
        raise RuntimeError("Glavni meni nije dostupan na trenutnoj stranici.")
    wait = WebDriverWait(driver, timeout)
    if item.dialog:
        frames = len(driver.find_elements(By.TAG_NAME, "iframe"))
        driver.execute_script(f"{item.js};")
        wait.until(lambda d: len(d.find_elements(By.TAG_NAME, "iframe")) > frames)
        driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[-1])
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    else:
        # Mark the current document; the mark is gone once the server has sent the new page.
        driver.execute_script(f"window.__timOldPage = true; {item.js};")
        try:
            wait.until(_page_replaced)
        except Exception:
            raise TimeoutError(f"Stranica „{item.path}“ se nije otvorila za {timeout:g} s.") from None
    wait_until_idle(driver)
    return describe_page(driver)


def wait_until_idle(driver: WebDriver, timeout: float = 15) -> None:
    """Wait until no table shows its loading overlay."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        tables = find_tables(driver)
        if not any(WDTable(driver, t["id"]).loading() for t in tables if t["visible"]):
            return
        time.sleep(0.2)


def describe_page(driver: WebDriver) -> dict:
    """What is on the current page: its title, tables (with columns and row counts) and whether it
    has a "Filter..." search field."""
    tables = [
        {"id": t["id"], "naziv": t["caption"], "kolone": [c for c in t["columns"] if c], "ukupno": t["total"]}
        for t in find_tables(driver) if t["visible"] and any(t["columns"])
    ]
    return {
        "naslov": driver.execute_script(PAGE_TITLE_JS),
        "tabele": tables,
        "filter": any(e.is_displayed() for e in driver.find_elements(*FILTER)),
    }


def apply_filter(driver: WebDriver, table: WDTable, text: str) -> bool:
    """Type `text` into the page's "Filter..." field and press Enter (the site searches on the server),
    then wait until the table shows the result. False if the page has no such field."""
    fields = [e for e in driver.find_elements(*FILTER) if e.is_displayed()]
    if not fields:
        return False
    before = table.signature()
    field = fields[0]
    field.click()
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(Keys.DELETE)
    field.send_keys(text, Keys.ENTER)
    # Wait for the site to apply the search: the overlay appears or the rows change.
    end = time.monotonic() + 5
    while time.monotonic() < end and not table.loading() and table.signature() == before:
        time.sleep(0.1)
    wait_until_idle(driver)
    return True


FIND_ROW_JS = r"""
const [id, column, value] = arguments;
const pattern = new RegExp('^' + id + '_(\\d+)$');
for (const row of document.querySelectorAll('#' + id + '_TB > tbody > tr')) {
  const m = row.id.match(pattern);
  if (!m || row.style.display === 'none') continue;
  const cell = document.getElementById(id + '_' + m[1] + '_' + column);
  if (cell && cell.innerText.trim() === value) return Number(m[1]);
}
return -1;
"""
SELECTED_JS = "const r = document.getElementById(arguments[0]); return !!r && r.classList.contains('Selection');"


def select_row(driver: WebDriver, column: str, value: str, timeout: float = 20) -> None:
    """Select (click) the main table's row whose `column` is exactly `value`, as the user would, so the
    page shows that row's details. Uses the "Filter..." field if the row is not among the shown rows."""
    table = main_table(driver)
    columns = table.columns
    if column not in columns:
        raise LookupError(f"Kolona „{column}“ ne postoji na ovoj stranici.")
    c = columns.index(column)
    find = lambda: driver.execute_script(FIND_ROW_JS, table.id, c, value)
    n = find()
    if n < 0 and apply_filter(driver, table, value):
        n = find()
    if n < 0:
        for _ in table._pages():
            n = find()
            if n >= 0:
                break
    if n < 0:
        raise LookupError(f"Red sa {column} = „{value}“ nije pronađen.")
    cell = driver.find_element(By.ID, f"{table.id}_{n}_{c}")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", cell)
    cell.click()
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script(SELECTED_JS, f"{table.id}_{n}"))
    wait_until_idle(driver)
    time.sleep(0.5)  # the details below the list are loaded by AJAX after the click


SELECTED_ROW_JS = """
const id = arguments[0];
const row = [...document.querySelectorAll('#' + id + '_TB > tbody > tr.Selection')][0];
return row ? row.id.slice(id.length + 1) : null;
"""


def selected_row(driver: WebDriver) -> dict | None:
    """The main table's selected (highlighted) row as {column: text}, or None."""
    table = main_table(driver)
    n = driver.execute_script(SELECTED_ROW_JS, table.id)
    if n is None:
        return None
    cells = [driver.execute_script("const c = document.getElementById(arguments[0]); return c ? c.innerText.trim() : ''",
                                   f"{table.id}_{n}_{c}") for c in range(len(table.columns))]
    return {c: v for c, v in zip(table.columns, cells) if c}


def parse_amount(text: str) -> float | None:
    """ "1.798,59" -> 1798.59 (None if it is not an amount)."""
    cleaned = text.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def format_amount(value: float) -> str:
    """1798.59 -> "1.798,59" (how the site writes amounts)."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def search_rows(driver: WebDriver, text: str, column: str = "", limit: int = 0, on_progress=None) -> dict:
    """Search the current page's main table: type `text` into the page's "Filter..." field (the
    site filters on the server), read the resulting rows (all of them if limit is 0) and keep those
    whose `column` contains the text (case and diacritics ignored; no column = keep all rows the site
    returned). on_progress(read, expected) reports reading progress."""
    table = main_table(driver)
    columns = [c for c in table.columns if c]
    if column and column not in columns:
        raise LookupError(f"Kolona „{column}“ ne postoji na ovoj stranici. Kolone: {', '.join(columns)}.")

    apply_filter(driver, table, text)
    total = table.total
    rows = table.read(limit, on_progress=on_progress)
    if column:
        wanted = normalize(text)
        rows = [r for r in rows if wanted in normalize(r.get(column, ""))]
    return {
        "pretraga": text,
        "kolona": column,
        "kolone": columns,
        "redovi": rows,
        "broj": len(rows),
        "ukupno_na_stranici": total,
        "skraceno": bool(limit) and total > limit,
    }


def search_advanced(driver: WebDriver, filters: list[dict], limit: int = 0, on_progress=None) -> dict:
    """Search the current page's main table with the "Napredni filteri" window (see pages/filters.py):
    turn on exactly these filters, apply them and read the resulting rows (all if limit is 0)."""
    from tim_automation.pages import filters as advanced

    table = main_table(driver)
    columns = [c for c in table.columns if c]
    # Clear the quick "Filter..." text so only the advanced filters apply.
    if any(e.get_attribute("value") for e in driver.find_elements(*FILTER) if e.is_displayed()):
        apply_filter(driver, table, "")
    before = table.signature()
    advanced.apply(driver, filters)
    end = time.monotonic() + 5  # the list refreshes after the window closes
    while time.monotonic() < end and not table.loading() and table.signature() == before:
        time.sleep(0.1)
    wait_until_idle(driver)
    total = table.total
    rows = table.read(limit, on_progress=on_progress)
    return {
        "filteri": filters,
        "kolone": columns,
        "redovi": rows,
        "broj": len(rows),
        "ukupno_na_stranici": total,
        "skraceno": bool(limit) and total > limit,
    }


DETAILS_JS = """
return [...document.querySelectorAll('input[type="text"]')]
  .some((i) => i.readOnly && i.offsetParent && i.value.trim() === arguments[0]);
"""
# Links under the selected document's details, e.g. "Finansijski nalog: MIED03297", "KIR redni broj:150"
# (`<a href="javascript:_PAGE_.ALIAS17.value=1;M32_T21()" id="c-1-ALIAS18">` in looper ALIAS17).
LINKS_JS = r"""
return [...document.querySelectorAll('a')]
  .filter((a) => a.offsetParent && /^c-\d+-/.test(a.id) && a.textContent.includes(':'))
  .map((a) => a.textContent.trim());
"""


def wait_details(driver: WebDriver, document: str, timeout: float = 10) -> bool:
    """Wait until the details below the list show `document` (a read-only field holds its number), so
    nothing is read from the previously selected document. False if that did not happen in time."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if driver.execute_script(DETAILS_JS, document):
            wait_until_idle(driver)
            time.sleep(0.3)
            return True
        time.sleep(0.2)
    return False


def linked_documents(driver: WebDriver) -> dict[str, str]:
    """The selected document's links as {label: value}, e.g. {"Finansijski nalog": "MIED03297"}."""
    links = {}
    for text in driver.execute_script(LINKS_JS):
        label, _, value = text.partition(":")
        links[label.strip()] = value.strip()
    return links


VIEW_JS = "return document.forms.length ? document.forms[0].name : document.title;"
LINK_BY_LABEL_JS = """
const [label, exact] = arguments;
return [...document.querySelectorAll('a')].find((a) => {
  const text = a.textContent.trim();
  return a.offsetParent && (exact ? text === label : text.startsWith(label));
}) || null;
"""


def view_name(driver: WebDriver) -> str:
    """Which application page is shown: its form name, e.g. "RACUNIZLAZVIEW" (Izlazi), "FINNALVIEW"."""
    driver.switch_to.default_content()
    return driver.execute_script(VIEW_JS) or ""


def _navigate(driver: WebDriver, action, what: str, timeout: float = 45) -> None:
    """Mark the page, do `action` (which submits it) and wait until the server has sent the next page."""
    driver.execute_script("window.__timOldPage = true;")
    action()
    try:
        WebDriverWait(driver, timeout).until(_page_replaced)
    except Exception:
        raise TimeoutError(f"{what}: nova stranica se nije otvorila za {timeout:g} s.") from None
    wait_until_idle(driver)


def open_link(driver: WebDriver, label: str, exact: bool = False) -> str:
    """Click the link whose text starts with (or with exact=True: is) `label`, e.g. "Finansijski nalog" or
    "Stavke", and wait for the page it opens. Returns the new page's view name."""
    driver.switch_to.default_content()
    link = driver.execute_script(LINK_BY_LABEL_JS, label, exact)
    if link is None:
        raise LookupError(f"Link „{label}“ nije pronađen.")
    _navigate(driver, link.click, f"Link „{label}“")
    return view_name(driver)


def click_back(driver: WebDriver) -> str:
    """Click the page's "Nazad" button (e.g. M33 on the financial order page) and wait for the page it
    goes back to. Returns that page's view name."""
    driver.switch_to.default_content()
    buttons = [b for b in driver.find_elements(By.XPATH, "//button[normalize-space()='Nazad']") if b.is_displayed()]
    if not buttons:
        raise LookupError("Dugme „Nazad“ nije pronađeno na ovoj stranici.")
    _navigate(driver, buttons[0].click, "Nazad")
    return view_name(driver)


def return_to(driver: WebDriver, view: str) -> None:
    """Go back (with "Nazad") to the page `view` if another page is shown, e.g. after subtasks on a page
    a task opened. Does nothing when already there (the job may have clicked "Nazad" itself)."""
    current = view_name(driver)
    if current == view:
        return
    print(f"    Returning from {current} to {view} (Nazad)...")
    try:
        if click_back(driver) != view:
            print(f"    After Nazad the page is {view_name(driver)}, not {view}.")
    except Exception as e:
        print(f"    Could not go back to {view}: {e}")
