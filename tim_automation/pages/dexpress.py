"""D Express "Grupisana uplata" (grouped payment of cash-on-delivery parcels), https://usersupport.dexpress.rs/ExternalApi/GP.

Form (HTML pasted 2026-10-25, ASP.NET MVC + Bootstrap, no login): `form[action$="/GP/View"]` method GET with
"Broj računa" `#AccountNumber`, "Poziv na broj" `#ReferenceNumber` (the one on the received payment) and the submit
`input[type=submit][value="Pogledaj"]`. Result page `/ExternalApi/GP/View?...`: `table.table` whose first row has the
`th`s PaymentDate, ShCode, ReferenceId, BuyOut, RName, RAddress, RTown, then one `tr` of `td`s per parcel, e.g.
"10/15/2026 12:00:00 AM" (US date), "KO0079850842", "KO0079850842", "1578.40" (dot decimal), "Aleksandar Rankovic",
"Selo Vinča bb", "Topola(KG) (selo)"; a link "Nazad" back to the form. What it shows for an unknown poziv na broj was
not pasted (an empty table or a message is assumed).

The page is opened in a window of its own in the TiM browser (kept for the next run, handle on the driver); the TiM
window is made current again afterwards, so the job goes on where it was."""
import re
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from tim_automation import config, ui
from tim_automation.pages.app_page import format_amount

GP_URL = config.DEXPRESS_GP_URL
ACCOUNT = "205-0000000003084-51"  # the user's account at D Express
COLUMNS = ("PaymentDate", "ShCode", "ReferenceId", "BuyOut", "RName", "RAddress", "RTown")
TAB_ATTR = "_tim_dexpress_tab"
TIMEOUT = 30

# The result table (header cells + rows), or the page's text when there is none.
READ_JS = r"""
const text = (el) => (el ? el.innerText || el.textContent || '' : '').replace(/\s+/g, ' ').trim();
const table = document.querySelector('table.table') || document.querySelector('.body-content table');
const form = !!document.querySelector('#ReferenceNumber');
const body = document.querySelector('.body-content') || document.body;
if (!table) return {table: false, form, text: text(body).slice(0, 1500)};
const rows = [...table.rows];
const head = rows.find((r) => r.querySelector('th'));
return {
  table: true, form,
  kolone: head ? [...head.cells].map(text) : [],
  redovi: rows.filter((r) => r !== head && r.querySelector('td')).map((r) => [...r.cells].map(text)),
};
"""


def open_window(driver: WebDriver) -> str:
    """Switch to the D Express window (open one if there is none) and show it in the live view."""
    handle = getattr(driver, TAB_ATTR, None)
    if handle in driver.window_handles:
        driver.switch_to.window(handle)
    else:
        driver.switch_to.new_window("window")
        handle = driver.current_window_handle
        setattr(driver, TAB_ATTR, handle)
    try:  # a background window isn't painted (live view)
        driver.execute_cdp_cmd("Page.bringToFront", {})
    except Exception:
        pass
    ui.show_window(handle)
    return handle


def grouped_payment(driver: WebDriver, reference: str, account: str = ACCOUNT, log=print) -> dict:
    """Look up the parcels paid by one grouped payment (`reference` = its poziv na broj). Returns rows with the site's
    columns (PaymentDate as DD/MM/YYYY, BuyOut as "1.578,40"), "broj" and "ukupno" {"BuyOut"}."""
    reference, account = str(reference or "").strip(), str(account or "").strip() or ACCOUNT
    if not reference:
        raise ValueError("Poziv na broj je obavezan.")
    back = driver.current_window_handle
    try:
        open_window(driver)
        log(f"D Express: opening {GP_URL}")
        driver.get(GP_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        try:
            wait.until(lambda d: d.find_elements(By.ID, "ReferenceNumber"))
        except Exception:
            raise LookupError(f"Stranica „Grupisana uplata“ se nije otvorila ({driver.current_url}).") from None
        for field_id, value in (("AccountNumber", account), ("ReferenceNumber", reference)):
            field = driver.find_element(By.ID, field_id)
            field.clear()
            field.send_keys(value)
        log(f"D Express: account {account}, poziv na broj {reference}, Pogledaj")
        driver.execute_script("window.__timOldPage = true;")
        driver.find_element(By.CSS_SELECTOR, 'input[type="submit"], button[type="submit"]').click()
        try:
            wait.until(lambda d: not d.execute_script("return window.__timOldPage === true;")
                       and d.execute_script("return document.readyState") == "complete")
        except Exception:
            raise TimeoutError(f"D Express nije odgovorio za {TIMEOUT} s.") from None
        page = driver.execute_script(READ_JS)
        url = driver.current_url
    finally:
        driver.switch_to.window(back)
        ui.show_window(back)
    if not page["table"]:
        if page["form"] and page["text"]:  # back on the form: a validation message, or nothing found
            raise LookupError(f"D Express nije vratio tabelu za poziv na broj {reference}: {page['text']}")
        return _value([], [], account, reference, url)
    return _value(page["kolone"], page["redovi"], account, reference, url)


def _value(header: list[str], cells: list[list[str]], account: str, reference: str, url: str) -> dict:
    columns = [c for c in header if c] or list(COLUMNS)
    rows, total = [], 0.0
    for line in cells:
        row = {c: (line[i] if i < len(line) else "") for i, c in enumerate(columns)}
        if "PaymentDate" in row:
            row["PaymentDate"] = site_date(row["PaymentDate"])
        if "BuyOut" in row:
            amount = site_amount(row["BuyOut"])
            if amount is not None:
                total += amount
                row["BuyOut"] = format_amount(amount)
        rows.append(row)
    return {
        "kolone": columns,
        "redovi": rows,
        "broj": len(rows),
        "ukupno": {"BuyOut": format_amount(total)},
        "Broj računa": account,
        "Poziv na broj": reference,
        "adresa": url,
    }


def site_amount(text: str) -> float | None:
    """ "1578.40" (dot decimal; also "1,578.40") -> 1578.4."""
    cleaned = re.sub(r"[\s,]", "", str(text or ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def site_date(text: str) -> str:
    """ "10/15/2026 12:00:00 AM" (month first) -> "15/10/2026" (how TiM writes dates); other text unchanged."""
    match = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(text or ""))
    if not match:
        return str(text or "").strip()
    try:
        return datetime(int(match[3]), int(match[1]), int(match[2])).strftime("%d/%m/%Y")
    except ValueError:
        return str(text).strip()
