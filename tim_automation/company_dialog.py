from collections.abc import Callable

from tim_automation import ui
from tim_automation.pages.company_page import Company

REFRESH = "refresh"


def choose_company(
    companies: list[Company],
    years: list[str],
    default_year: str = "",
    default: Company | None = None,
    saved_at: float | None = None,
    message: str = "",
    known_years: dict[Company, tuple[list[str], str]] | None = None,
    check_years: Callable[[Company], tuple[list[str], str]] | None = None,
    set_year: Callable[[Company, str], bool] | None = None,
) -> tuple[Company, str] | str | None:
    """Show the searchable company list in the web UI. Returns (company, year), REFRESH if the user
    wants the list read again from the site, or None if cancelled. saved_at is when the list was read.

    known_years holds the years already known per company (e.g. cached). For other companies, opening
    the year list calls check_years(company), which returns the years that company really has (and the
    selected one). Picking a year calls set_year(company, year) to set it in the browser."""

    def on_request(request: dict, data: dict) -> None:
        index = request["index"]
        company = companies[index]
        try:
            if request["type"] == "years" and check_years:
                company_years, selected = check_years(company)
                data["checked"][str(index)] = {"years": company_years, "year": selected}
                data["inBrowser"] = index
            elif request["type"] == "year" and set_year:
                set_year(company, request["year"])
                data["inBrowser"] = index
        except Exception as e:  # e.g. the company is no longer in the list
            print(f"Browser request {request} for {company.name} failed: {e}")
            if request["type"] == "years":
                data["checked"][str(index)] = {"years": [], "year": "", "error": str(e).splitlines()[0]}
                data["inBrowser"] = index  # ends the page's "checking" state

    known = known_years or {}
    answer = ui.ask("company", {
        "companies": [{"name": c.name, "pib": c.pib, "active": c.active} for c in companies],
        "years": years,
        "year": default_year or (years[0] if years else ""),
        "selected": companies.index(default) if default in companies else -1,
        "savedAt": saved_at,
        "message": message,
        # Years confirmed in the browser, by company index (as a string, since it's a JSON key).
        "checked": {
            str(i): {"years": known[c][0], "year": known[c][1]} for i, c in enumerate(companies) if c in known
        },
        # Index of the company currently selected in the browser.
        "inBrowser": companies.index(default) if default in companies else -1,
    }, on_request=on_request)
    if not answer:
        return None
    if answer.get("refresh"):
        return REFRESH
    return companies[answer["index"]], answer["year"]
