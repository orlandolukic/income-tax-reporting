"""Cache the company list per TiM ERP user in cache/companies.json, so it isn't re-read from the
site (which means scrolling the whole table) on every run. Entries expire after COMPANY_CACHE_DAYS.
Each company's available years are cached with the list once checked, and dropped when the list is
read again (e.g. "Osveži listu")."""
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from tim_automation import config
from tim_automation.pages.company_page import Company, mark_inactive

CACHE_FILE = Path("cache") / "companies.json"


@dataclass
class CachedCompanies:
    companies: list[Company]
    saved_at: float
    # Years each company has in TiM ERP, and the one the site selects for it.
    years: dict[Company, tuple[list[str], str]] = field(default_factory=dict)


def _key(username: str) -> str:
    # Hash the username so the file doesn't reveal which accounts were used.
    return hashlib.sha256(username.strip().lower().encode()).hexdigest()[:16]


def _company_key(company: Company) -> str:
    return f"{company.name}	{company.pib}"


def _read_file() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load(username: str) -> CachedCompanies | None:
    """The cached list for this user, or None if there is none or it is older than COMPANY_CACHE_DAYS."""
    entry = _read_file().get(_key(username))
    if not entry:
        return None
    try:
        companies = [Company(c["name"], c["pib"], c.get("active", True)) for c in entry["companies"]]
        if any("active" not in c for c in entry["companies"]):  # saved before the active flag existed
            companies = mark_inactive(companies)
        by_key = {_company_key(c): c for c in companies}
        years = {by_key[k]: (v["years"], v["year"]) for k, v in entry.get("years", {}).items() if k in by_key}
        cached = CachedCompanies(companies, entry["saved_at"], years)
    except (KeyError, TypeError):
        return None
    if not cached.companies or time.time() - cached.saved_at > config.COMPANY_CACHE_DAYS * 86400:
        return None
    return cached


def save(username: str, companies: list[Company]) -> CachedCompanies:
    data = _read_file()
    cached = CachedCompanies(companies, time.time())
    data[_key(username)] = {"saved_at": cached.saved_at, "companies": [c.__dict__ for c in companies]}
    _write_file(data)
    return cached


def save_years(username: str, cached: CachedCompanies, company: Company, years: list[str], selected: str) -> None:
    """Remember a company's years, in `cached` and (if this list is the one in the file) on disk."""
    cached.years[company] = (years, selected)
    data = _read_file()
    entry = data.get(_key(username))
    if not entry or entry.get("saved_at") != cached.saved_at:  # list wasn't cached (incomplete read)
        return
    entry.setdefault("years", {})[_company_key(company)] = {"years": years, "year": selected}
    _write_file(data)


def _write_file(data: dict) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
