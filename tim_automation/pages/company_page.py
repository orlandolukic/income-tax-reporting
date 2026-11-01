import time
import unicodedata
from collections.abc import Iterator
from itertools import chain
from dataclasses import dataclass, field, replace

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from tim_automation.ui import wait_for_user
from tim_automation.pages import site_error
from tim_automation.pages.base_page import BasePage
from tim_automation.pages.home_page import HomePage


@dataclass(frozen=True)
class Company:
    name: str
    pib: str
    active: bool = field(default=True, compare=False)


def _sort_key(name: str) -> str:
    """Approximates the site's A-Z order: case and diacritics ignored, "đ" sorted as "d"."""
    name = name.casefold().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))


def mark_inactive(companies: list[Company]) -> list[Company]:
    """The site lists active companies A-Z, then inactive ones A-Z (its "aktivno" column is hidden and
    empty in the browser). Everything after the point where the order starts over is inactive."""
    keys = [_sort_key(c.name) for c in companies]
    restarts = [i for i in range(1, len(keys)) if keys[i] < keys[i - 1]]
    if not restarts:
        return [replace(c, active=True) for c in companies]
    # If odd sorting causes several restarts, the real one is where the order drops closest to "A".
    start = min(restarts, key=lambda i: (keys[i], -i))
    return [replace(c, active=i < start) for i, c in enumerate(companies)]


# The company list is a WebDev table ("A3") that only renders ~15 rows; scrolling its
# scrollbar (the parent of #A3_SB) makes it fetch the rows for that position from the server.
VISIBLE_ROWS_JS = """
return [...document.querySelectorAll('#A3_TB tr[id^="A3_"]')]
  .filter((r) => r.style.display !== 'none')
  .map((r) => {
    const cells = [...r.querySelectorAll('div[id^="' + r.id + '_"]')].map((d) => d.textContent.trim());
    return {row: r.id, name: cells[0] || '', pib: cells[1] || '', selected: r.classList.contains('Selection')};
  })
  .filter((r) => r.name);
"""
SCROLL_JS = "const s = arguments[0]; s.scrollTop = arguments[1]; s.dispatchEvent(new Event('scroll')); return s.scrollTop;"


class CompanySelectPage(BasePage):
    """"Odabir firme i godine obrade": the company list shown right after login."""

    TITLE = (By.XPATH, "//td[normalize-space()='Odabir firme i godine obrade']")
    SCROLLER = (By.XPATH, "//div[@id='A3_SB']/..")
    LOADING = (By.ID, "A3_MASQUE")
    ROW_COUNT = (By.NAME, "_A3_OCC")
    YEAR = (By.XPATH, "//td[normalize-space()='Godina obrade:']/following-sibling::td//select")
    SUBMIT = (By.XPATH, "//button[normalize-space()='Izbor']")
    # "Filter..." box above the table: it has no key handlers, the magnifier next to it (A2,
    # `_JAEE(_PAGE_,'A2',...)`) reloads the table by AJAX with only the matching companies.
    FILTER = (By.XPATH, "//input[@placeholder='Filter...']")
    FILTER_BUTTON = (By.ID, "A2")

    def is_open(self) -> bool:
        return bool(self.driver.find_elements(*self.TITLE))

    def _visible_rows(self) -> list[dict]:
        """Rows currently rendered, once the table has finished loading and stopped changing."""
        previous = None
        for _ in range(40):
            time.sleep(0.15)
            if any(e.is_displayed() for e in self.driver.find_elements(*self.LOADING)):
                continue
            rows = self.driver.execute_script(VISIBLE_ROWS_JS)
            if rows == previous:
                return rows
            previous = rows
        return previous or []

    def _pages(self) -> Iterator[list[dict]]:
        """Scroll the table from top to bottom, yielding the rendered rows at each position."""
        scroller = self.find(self.SCROLLER)
        step = max(scroller.size["height"] - 40, 20)
        top = 0
        while True:
            actual = self.driver.execute_script(SCROLL_JS, scroller, top)
            yield self._visible_rows()
            if actual < top:  # could not scroll further: reached the bottom
                return
            top += step

    def selected_company(self) -> Company | None:
        for row in self._visible_rows():
            if row["selected"]:
                return Company(row["name"], row["pib"])
        return None

    def row_count(self) -> int | None:
        """Total number of companies according to the table (hidden field _A3_OCC)."""
        elements = self.driver.find_elements(*self.ROW_COUNT)
        try:
            return int(elements[0].get_attribute("value")) if elements else None
        except (TypeError, ValueError):
            return None

    def _filter_text(self) -> str:
        elements = self.driver.find_elements(*self.FILTER)
        return (elements[0].get_attribute("value") or "") if elements else ""

    def filter(self, text: str) -> bool:
        """Type `text` into "Filter..." and click the magnifier, then wait for the table to reload.
        False if the page has no filter box."""
        boxes = self.driver.find_elements(*self.FILTER)
        if not boxes or not self.driver.find_elements(*self.FILTER_BUTTON):
            return False
        if self._filter_text() == text:
            return True
        before = self.driver.execute_script(VISIBLE_ROWS_JS)
        boxes[0].clear()
        if text:
            boxes[0].send_keys(text)
        self.click(self.FILTER_BUTTON)
        # Wait for the AJAX reload: the rows change (or stay the same if the filter didn't narrow them).
        for _ in range(30):
            time.sleep(0.1)
            if self.driver.execute_script(VISIBLE_ROWS_JS) != before:
                break
        self._visible_rows()  # settled
        return True

    def clear_filter(self) -> None:
        if self._filter_text():
            self.filter("")

    def _read_pass(self) -> list[Company]:
        companies: dict[Company, None] = {}
        for rows in self._pages():
            for row in rows:
                companies[Company(row["name"], row["pib"])] = None
        return list(companies)

    def read_all(self, attempts: int = 3) -> tuple[list[Company], bool]:
        """Read every company, in table order. Scrolling sometimes skips a page of rows, so the list is
        read again (up to `attempts` times) until it has as many companies as the table reports.
        Returns (companies, complete)."""
        self.clear_filter()  # e.g. left over from choosing a company: the whole list is needed
        expected = self.row_count()
        best: list[Company] = []
        for attempt in range(1, attempts + 1):
            companies = self._read_pass()
            if len(companies) > len(best):
                best = companies
            if expected is None or len(companies) >= expected:
                return mark_inactive(companies), True
            print(f"Read {len(companies)} of {expected} companies (attempt {attempt}/{attempts}), reading again...")
        return mark_inactive(best), False

    def years(self) -> tuple[list[str], str]:
        """Available years and the currently selected one."""
        elements = self.driver.find_elements(*self.YEAR)
        if not elements:
            return [], ""
        select = Select(elements[0])
        return [o.text.strip() for o in select.options], select.first_selected_option.text.strip()

    def select_row(self, company: Company) -> None:
        """Select the company's row in the table (scrolling to it if needed) and wait until the year
        list has been updated for it."""
        if self.selected_company() == company:
            return
        is_company = lambda r: r["name"] == company.name and r["pib"] == company.pib

        def find_and_click() -> bool:
            # The rows already shown first, then scrolling through the table.
            for rows in chain([self._visible_rows()], self._pages()):
                row = next((r for r in rows if is_company(r)), None)
                if row:
                    # A click can be lost while the table is still being redrawn: try it a few times.
                    for attempt in range(3):
                        try:
                            self.click((By.CSS_SELECTOR, f"#{row['row']} td"))
                            WebDriverWait(self.driver, 5).until(lambda _: self.selected_company() == company)
                            break
                        except Exception:
                            if attempt == 2:
                                raise
                            print(f"{company.name} was not selected after the click; trying again.")
                            row = next((r for r in self._visible_rows() if is_company(r)), row)
                    self._wait_years_settled()
                    return True
            return False

        # Narrow the table with the name in "Filter..."; without it, look through the whole list.
        if self.filter(company.name):
            if find_and_click():
                return
            print(f"Filter did not show {company.name} ({company.pib}); looking through the whole list.")
            self.clear_filter()
        if find_and_click():
            return
        raise LookupError(f"Firma {company.name} ({company.pib}) nije pronađena u listi.")

    def _wait_years_settled(self) -> None:
        """The year list can depend on the company and may be refreshed after the row is selected."""
        previous = None
        for _ in range(20):
            time.sleep(0.15)
            if any(e.is_displayed() for e in self.driver.find_elements(*self.LOADING)):
                continue
            current = self.years()
            if current == previous:
                return
            previous = current

    def available_years(self, company: Company) -> tuple[list[str], str]:
        """Select the company in the browser and return its years and the selected one."""
        self.select_row(company)
        return self.years()

    def set_year(self, company: Company, year: str) -> bool:
        """Select the company and choose the year in the browser. False if it has no such year."""
        self.select_row(company)
        years, _ = self.years()
        if year not in years:
            print(f"Godina {year} nije dostupna za {company.name} (dostupne: {', '.join(years)}).")
            return False
        Select(self.find(self.YEAR)).select_by_visible_text(year)
        return True

    def select(self, company: Company, year: str = "") -> None:
        """Select the company row, set the year and click "Izbor"."""
        self.select_row(company)
        if year:
            self.set_year(company, year)
        self.click(self.SUBMIT)
        self.wait.until(lambda _: HomePage(self.driver).is_open() or site_error.shown(self.driver))
        if site_error.shown(self.driver):
            raise site_error.SiteError()

    def wait_for_user_selection(self) -> bool:
        """Let the user pick a company and click "Izbor" in the browser. Returns True once the main
        menu has loaded (or the user clicks "Nastavi"), False if they cancel."""
        home = HomePage(self.driver)
        proceed = wait_for_user(
            "Izaberite firmu i godinu u pretraživaču i kliknite „Izbor“.\n\n"
            "Skeniranje menija počinje automatski kad se meni učita. "
            "Ako se ne pokrene, kliknite „Nastavi“.",
            home.is_open,
        )
        if proceed:
            self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        return proceed


class YearUnavailable(LookupError):
    """The company has no such year in TiM ERP."""


class DialogNotFound(Exception):
    """The company window didn't open after clicking the company's name in the menu (the caller logs in again)."""


# Texts of the button that confirms the company window: "Izbor" on the page after login; the window opened from
# the menu may say "Potvrdi" (the user said so; its HTML is not known yet).
CONFIRM_TEXTS = ("Izbor", "Potvrdi", "Prihvati", "Izaberi", "U redu", "OK", "Ok")
CANCEL_TEXTS = ("Odustani", "Otkaži", "Zatvori", "Nazad")
YEAR_SELECT_JS = """
const ok = (s) => s.offsetParent && s.options.length && [...s.options].every((o) => /^\s*\d{4}\s*$/.test(o.text));
return [...document.querySelectorAll('select')].find(ok) || null;
"""
BUTTONS_JS = """
return [...document.querySelectorAll('button, a, input[type=button], input[type=submit]')]
  .filter((b) => b.offsetParent).map((b) => (b.innerText || b.value || b.title || '').trim()).filter(Boolean);
"""
COMPANY_BUTTON_JS = """
const img = document.querySelector("img[class*='bazaicon']");
return img ? img.closest('button') || img.closest('a') || img : null;
"""


def _year_select(driver):
    """The year list of the company window: next to "Godina obrade:", else any shown list of only years."""
    found = [e for e in driver.find_elements(*CompanySelectPage.YEAR) if e.is_displayed()]
    return found[0] if found else driver.execute_script(YEAR_SELECT_JS)


def _click_text(driver, texts) -> str:
    for text in texts:
        for element in driver.find_elements(
                By.XPATH, f"//button[normalize-space()='{text}'] | //a[normalize-space()='{text}']"
                          f" | //input[@type='button' or @type='submit'][@value='{text}']"):
            if element.is_displayed():
                element.click()
                return text
    return ""


def _open_window(driver, timeout: float) -> str:
    """Click the company's name in the menu and wait for the company window. Leaves the driver in the document
    that has it; returns where it is ("stranica" = the page was replaced, "prozor" = an iframe over the page)."""
    driver.switch_to.default_content()
    button = driver.execute_script(COMPANY_BUTTON_JS)
    if button is None:
        raise DialogNotFound("Dugme sa imenom firme nije pronađeno u meniju.")
    label = (button.text or "").strip()  # read now: after the click the element may be gone
    driver.execute_script("window.__timOldPage = true;")
    button.click()
    companies = CompanySelectPage(driver)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        time.sleep(0.3)
        try:
            driver.switch_to.default_content()
            if companies.is_open() or _year_select(driver) is not None:
                return "stranica" if driver.execute_script("return !window.__timOldPage") else "na stranici"
            for frame in driver.find_elements(By.TAG_NAME, "iframe"):
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if companies.is_open() or _year_select(driver) is not None:
                    return "prozor"
        except Exception:  # the page is being replaced
            continue
    driver.switch_to.default_content()
    raise DialogNotFound(f"Prozor za izbor firme se nije otvorio za {timeout:g} s posle klika na „{label}“.")


def change_year(driver, company: Company, year: str, timeout: float = 30) -> None:
    """Open another year of the open company without logging in again: click the company's name in the menu
    (e.g. "SLAVIJA 2026"), choose the year in the company window that opens and confirm. Raises YearUnavailable
    (the window is closed again) or DialogNotFound (nothing was changed; the caller may log in again)."""
    where = _open_window(driver, timeout)
    companies = CompanySelectPage(driver)
    print(f"Company window open ({where}).")
    if driver.find_elements(By.ID, "A3_TB"):  # the company list, as after login: make sure the right row is selected
        companies.select_row(company)
    select = _year_select(driver)
    if select is None:
        raise DialogNotFound("Lista godina nije pronađena u prozoru za izbor firme.")
    years = [o.text.strip() for o in Select(select).options]
    if year not in years:
        # Close the window without changing anything (no cancel button: confirm it with the year as it is).
        if not _click_text(driver, CANCEL_TEXTS) and _click_text(driver, CONFIRM_TEXTS):
            driver.switch_to.default_content()
            WebDriverWait(driver, 60).until(lambda d: HomePage(d).is_open() or site_error.shown(d))
        driver.switch_to.default_content()
        raise YearUnavailable(f"firma nema godinu {year} u TiM ERP-u (ima: {', '.join(years) or 'nijednu'}).")
    Select(select).select_by_visible_text(year)
    time.sleep(0.3)  # the year change may be sent to the server (AJAX)
    clicked = _click_text(driver, CONFIRM_TEXTS)
    if not clicked:
        texts = driver.execute_script(BUTTONS_JS)
        _click_text(driver, CANCEL_TEXTS)
        driver.switch_to.default_content()
        raise DialogNotFound(f"Dugme za potvrdu nije pronađeno (dugmad: {', '.join(texts)}).")
    print(f"Year {year} chosen, clicked „{clicked}“.")
    driver.switch_to.default_content()
    home = HomePage(driver)
    WebDriverWait(driver, 60).until(
        lambda d: site_error.shown(d) or (home.is_open() and home.company_label().endswith(year)))
    if site_error.shown(driver):
        raise site_error.SiteError()
