import re
import sys
import time
import traceback

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

from tim_automation import company_cache, config, credentials, home_status, log, purs_login, purs_queue, purs_reports, ui
from tim_automation.company_dialog import REFRESH, choose_company
from tim_automation.driver import create_driver
from tim_automation.jobs import JobRunner
from tim_automation.reports import ReportRunner
from tim_automation.pages.company_page import Company, CompanySelectPage, DialogNotFound, YearUnavailable, change_year
from tim_automation.pages.home_page import HomePage
from tim_automation.pages import site_error
from tim_automation.pages.login_page import LoginFailed, LoginPage


def read_companies(companies: CompanySelectPage, username: str) -> company_cache.CachedCompanies | None:
    """Read the whole company list from the site and cache it. None if it couldn't be read."""
    ui.status("Čitanje liste firmi...")
    print("Reading company list...")
    all_companies, complete = companies.read_all()
    if not all_companies:
        return None
    inactive = sum(not c.active for c in all_companies)
    print(f"Found {len(all_companies)} companies ({inactive} inactive):")
    for company in all_companies:
        print(f"  {company.name} ({company.pib}){'' if company.active else ' [inactive]'}")
    if not complete:
        # Don't keep an incomplete list for days; it's read again on the next run.
        print("Some companies could not be read; the list is not cached.")
        return company_cache.CachedCompanies(all_companies, time.time())
    return company_cache.save(username, all_companies)


def choose_company_step(companies: CompanySelectPage, username: str) -> dict | None:
    """Let the user search and pick a company in the web UI (from the cached list when it's fresh),
    then select it in the browser. Falls back to choosing in the browser if the list can't be read.
    Returns {name, pib, year, active} ({} if chosen in the browser), or None if cancelled."""
    default = companies.selected_company()
    cached = company_cache.load(username)
    if cached:
        age_hours = (time.time() - cached.saved_at) / 3600
        print(f"Using cached company list ({len(cached.companies)} companies, {age_hours:.1f} h old).")
    message = ""
    while True:
        if cached is None:
            cached = read_companies(companies, username)
            if cached is None:
                print("Could not read the company list. Choose a company in the browser and click Izbor.")
                return {} if companies.wait_for_user_selection() else None
        years, current_year = companies.years()
        if default in cached.companies and default not in cached.years and years:
            company_cache.save_years(username, cached, default, years, current_year)

        def check_years(company: Company, cached=cached) -> tuple[list[str], str]:
            company_years = companies.available_years(company)
            company_cache.save_years(username, cached, company, *company_years)
            return company_years

        ui.status("Izbor firme")
        choice = choose_company(
            cached.companies, years, current_year, default, cached.saved_at, message,
            known_years=cached.years, check_years=check_years, set_year=companies.set_year)
        if choice is None:
            return None
        if choice == REFRESH:
            cached = None
            message = ""
            continue
        company, year = choice
        remember_choice(company, year)
        ui.status(f"Otvaranje firme {company.name}...")
        print(f"Selecting {company.name} ({company.pib}), year {year}...")
        try:
            companies.select(company, year)
            return {"name": company.name, "pib": company.pib, "year": year, "active": company.active}
        except LookupError:
            # The cached list is out of date: read it again and let the user choose once more.
            print(f"{company.name} ({company.pib}) is no longer in the list; reading the list again.")
            message = f"Firma {company.name} više nije u listi. Lista je ponovo učitana, izaberite ponovo."
            cached = None


def company_key(company: dict) -> str | None:
    """Which company's jobs to use: name + PIB, or the site's label without the year if the company was
    chosen in the browser. None if neither is known."""
    if company.get("name"):
        return f"{company['name']}	{company.get('pib', '')}"
    label = re.sub(r"\s+\d{4}$", "", company.get("naSajtu") or "").strip()
    return f"site:{label}" if label else None


def session_year(company: dict) -> str:
    """The open year when the company was chosen in the browser: from the site's label ("FIRMA 2026")."""
    m = re.search(r"(\d{4})$", (company.get("naSajtu") or "").strip())
    return m.group(1) if m else ""


# The company last chosen in the picker, kept even if opening it fails: after a browser restart (site error)
# it is opened again without asking.
last_choice: dict = {}


def remember_choice(company: Company, year: str) -> None:
    last_choice.clear()
    last_choice.update(name=company.name, pib=company.pib, year=year, active=company.active)


def publish_session(user: str = "", company: dict | None = None) -> None:
    """Show who is logged in and which company is open in the page header."""
    ui.set_shared("session", {"user": user, "company": company})


def login(page: LoginPage, creds: credentials.Credentials) -> credentials.Credentials | None:
    """Log in, asking again until the site accepts the credentials. None if the user cancels."""
    while True:
        ui.status("Prijavljivanje na TiM ERP...")
        page.load()
        try:
            page.login(creds.username, creds.password)
            return creds
        except LoginFailed as e:
            credentials.forget()
            ui.status("Prijava")
            try:
                creds = credentials.prompt(creds.username, f"{e} Pokušajte ponovo.")
            except credentials.CredentialsCancelled:
                return None


class Browser:
    """The automated browser. When TiM ERP shows "Došlo je do nepredviđene greške", the session is broken:
    restart() closes it and opens a new one (the caller then logs in again from the login page)."""

    def __init__(self) -> None:
        self.driver = None

    def start(self):
        ui.status("Pokretanje pretraživača...")
        self.driver = create_driver(on_status=ui.status)
        ui.set_browser(self.driver)
        return self.driver

    def restart(self):
        print("Restarting the browser...")
        ui.set_browser(None)
        try:
            self.driver.quit()
        except Exception:
            pass
        return self.start()

    def quit(self) -> None:
        ui.set_browser(None)
        if self.driver is not None:
            self.driver.quit()


SETUP_RESTARTS = 3


def _message(e: Exception) -> str:
    return f"{type(e).__name__}: {e}".splitlines()[0]  # browser restarts in a row while logging in / opening the company


def open_company(driver, creds: credentials.Credentials, company: dict, require_year: bool = False) -> None:
    """After a restart: log in again and open the same company and year, without asking (the runner then
    runs the job again). Also used by reports to open another year of the company (require_year: raise
    YearUnavailable instead of opening the year the site offers). Raises if that can't be done."""
    page = LoginPage(driver)
    page.load()
    page.login(creds.username, creds.password)
    companies, home = CompanySelectPage(driver), HomePage(driver)
    page.wait.until(lambda _: companies.is_open() or home.is_open() or site_error.shown(driver))
    if site_error.shown(driver):
        raise site_error.SiteError()
    if companies.is_open():
        if not company.get("name"):
            raise RuntimeError("Firma je bila izabrana u pretraživaču, pa ne može da se izabere sama.")
        chosen, year = Company(company["name"], company.get("pib", "")), company.get("year", "")
        if require_year and year:
            years, _ = companies.available_years(chosen)
            if year not in years:
                raise YearUnavailable(f"firma nema godinu {year} u TiM ERP-u (ima: {', '.join(years) or 'nijednu'}).")
        companies.select(chosen, year)
    elif require_year:
        raise RuntimeError("Posle prijave nije prikazana lista firmi, pa godina ne može da se promeni.")
    WebDriverWait(driver, 60).until(lambda _: home.is_open() or site_error.shown(driver))
    if site_error.shown(driver):
        raise site_error.SiteError()
    print(f"Logged in again; {company.get('name') or company.get('naSajtu', 'the company')} is open.")


def main() -> None:
    if "--forget" in sys.argv:
        credentials.forget()
        print("Saved credentials removed.")
        return
    if "--relogin" in sys.argv:
        credentials.forget()
    if "--headless" in sys.argv:
        config.HEADLESS = True

    runner = JobRunner()  # the Poslovi page works (editing) even before the browser is ready
    reports = ReportRunner()
    purs_reports.setup()  # ePorezi "Упит стања" reports: files, page list
    ui.register_api("purs-login", purs_login.handle_api)  # "Prijava na ePorezi" on the PURS page
    ui.register_api("purs-red", purs_queue.handle_api)  # the PURS queue (one ePorezi session for the whole program)
    purs_queue.publish()
    purs_login.publish()
    ui.register_api("pocetna", home_status.handle_api)  # Početna: TiM ERP / ePorezi checks, statistics
    home_status.publish()
    publish_session()
    ui.status("Prijava")
    try:
        creds = credentials.get()
    except credentials.CredentialsCancelled:
        print("Login cancelled.")
        return

    browser = Browser()
    browser.start()
    restarts = 0
    reopen: dict | None = None  # after a restart while opening a company: open this one again, without asking
    try:
        # One pass per login: "Promena firme" logs in again (the site then shows the company page),
        # "Odjava" forgets the saved password and shows the login form, a site error restarts the browser.
        while True:
            driver = browser.driver
            page = LoginPage(driver)
            company: dict = {}
            try:
                creds = login(page, creds)
                if creds is None:
                    print("Login cancelled.")
                    return
                print(f"Logged in as {creds.username}. Now at: {driver.current_url}")
                publish_session(creds.username)
                companies, home = CompanySelectPage(driver), HomePage(driver)
                page.wait.until(lambda _: companies.is_open() or home.is_open() or site_error.shown(driver))
                if site_error.shown(driver):
                    raise site_error.SiteError()

                if companies.is_open():
                    if reopen and reopen.get("name"):
                        print(f"Opening {reopen['name']} again...")
                        companies.select(Company(reopen["name"], reopen.get("pib", "")), reopen.get("year", ""))
                        company = {k: v for k, v in reopen.items() if k != "naSajtu"}
                    else:
                        chosen = choose_company_step(companies, creds.username)
                        if chosen is None:
                            print("Cancelled.")
                            return
                        company = chosen
                    print(f"Company selected. Now at: {driver.current_url}")
                ui.status("Čekanje glavnog menija...")
                print("Waiting for the main menu...")
                try:
                    WebDriverWait(driver, 60).until(lambda _: home.is_open() or site_error.shown(driver))
                    if site_error.shown(driver):
                        raise site_error.SiteError()
                    company["naSajtu"] = home.company_label()
                except TimeoutException:
                    print(f"Main menu did not appear (now at {driver.current_url}).")
            except Exception as e:
                if not site_error.shown(driver) and not isinstance(e, site_error.SiteError):
                    raise
                restarts += 1
                if restarts > SETUP_RESTARTS:
                    raise
                print(f"The site shows „{site_error.MESSAGE}“ while logging in ({_message(e)}); restarting the "
                      f"browser ({restarts}/{SETUP_RESTARTS}).")
                reopen = company or dict(last_choice) or reopen
                browser.restart()
                continue
            restarts, reopen = 0, None
            last_choice.clear()
            label = ", ".join(x for x in (company.get("name"), company.get("year")) if x) or company.get("naSajtu", "")
            publish_session(creds.username, company)
            year = company.get("year") or session_year(company)
            key = company_key(company)

            def recover(company=company, label=label, creds=creds, year=year, key=key) -> None:
                """For the runner: new browser, log in, same company (a few tries if the site errors again)."""
                for attempt in range(1, SETUP_RESTARTS + 1):
                    new_driver = browser.restart()
                    try:
                        open_company(new_driver, creds, company)
                        runner.attach(new_driver, label, key)
                        reports.attach(new_driver, label, key, year)
                        purs_reports.set_company(key, label)
                        publish_session(creds.username, company)
                        return
                    except Exception as e:
                        if attempt == SETUP_RESTARTS or not (isinstance(e, site_error.SiteError) or site_error.shown(new_driver)):
                            raise
                        print(f"The site shows „{site_error.MESSAGE}“ again; restarting once more.")

            def switch_year(new_year: str, company=company, creds=creds) -> None:
                """For reports: open the same company in another year (or back in its own) like the user does:
                the company's name in the menu → company window → year → confirm. If that window can't be used,
                log in again and choose the company and year on the page after login."""
                driver = browser.driver
                ui.status(f"Otvaranje godine {new_year}...")
                try:
                    change_year(driver, Company(company["name"], company.get("pib", "")), new_year)
                except DialogNotFound as e:
                    print(f"Could not change the year in the session ({e}); logging in again.")
                    driver.switch_to.default_content()
                    driver.delete_all_cookies()
                    open_company(driver, creds, {**company, "year": new_year}, require_year=True)
                shown = HomePage(driver).company_label()
                if not shown.endswith(new_year):
                    print(f"Note: the site shows {shown!r} after opening year {new_year}.")
                publish_session(creds.username, {**company, "year": new_year, "naSajtu": shown})
                print(f"Year {new_year} is open.")

            def tick() -> None:
                runner.process_pending()
                reports.process_pending()
                home_status.process_pending(browser.driver)

            # Ready: jobs started on the "Poslovi" page and reports from "Izveštaji" run here, on this thread,
            # until the user finishes.
            runner.recover = recover
            reports.recover = recover
            reports.switch_year = switch_year if company.get("name") else None
            runner.attach(driver, label, key)
            reports.attach(driver, label, key, year)
            purs_reports.set_company(key, label)  # each company has its own PURS requests
            ui.status("Spremno")
            print("Ready. Run jobs from the Poslovi page.")
            purs_login.ready = True
            purs_login.publish()
            home_status.ready = True
            home_status.request_tim(force=True)
            home_status.check_purs(force=True)
            try:
                action = ui.ask("ready", {"company": label}, tick=tick)
            finally:
                runner.recover = reports.recover = reports.switch_year = None
                purs_login.ready = False
                purs_login.publish()
                home_status.ready = False
                home_status.reset_tim()
                runner.detach()
                reports.detach()
                purs_reports.set_company(None)
            driver = browser.driver  # a new one if a job restarted it
            if action in ("company", "logout"):
                driver.delete_all_cookies()  # start a new site session from the login page
            if action == "company":
                print("Changing the company: logging in again.")
                publish_session(creds.username)
                continue
            if action == "logout":
                print(f"Logged out ({creds.username}); saved credentials removed.")
                credentials.forget()
                publish_session()
                ui.status("Prijava")
                try:
                    creds = credentials.prompt(creds.username, "Odjavljeni ste. Prijavite se ponovo.")
                except credentials.CredentialsCancelled:
                    print("Login cancelled.")
                    return
                continue
            return
    finally:
        runner.detach()
        reports.detach()
        browser.quit()
        purs_queue.shutdown()  # the ePorezi browser


if __name__ == "__main__":
    print(f"Log: {log.start()}")
    print(f"Web UI: {ui.start()}")
    try:
        main()
        ui.status("Program je završen. Možete zatvoriti ovu stranicu.")
    except Exception as e:
        traceback.print_exc()
        ui.status("Greška")
        ui.ask("done", {"error": f"{type(e).__name__}: {e}"})  # keep the page up so the error stays visible
    time.sleep(0.5)  # let the page receive the last messages
