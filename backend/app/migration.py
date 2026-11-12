"""Migracija: the company registry and building the next reporting year from the latest one.

The registry is every company of the database (`company`), each with its details from its most
recent year. The next year (latest year + 1) is built in the app ("constructed"), not imported
from a workbook: it gets the latest year's columns (headers, formats), and for each selected
company a `company_year` with the company's identity (`company`) and only its details carried
over: NAZIV, PIB, REFERENT and the office, as they are now (edits included). The status
columns (kom, Preliminarni, GFI uradjen, PB-1, PB-2, Predat) start at 0; the formula columns
(GFI ZA RAD, PB-1,PB-2 za rad) are computed as in every year. The table is then shown like any
year (Home, Company Registry).

The year's PB-1 form is constructed with it (ensure_pb1_form): a 'pb1' source_file of origin
"constructed" pointing to the year it was built from, so the year has the same three PB-1 tabs
(and everything set up for them), built from that year's form, empty (0) for every company.

The companies of a constructed year can be changed later: a deselected company is hidden
(`company_year.active`), not deleted, so its values are back when it is selected again.

PostgreSQL only (the Excel + SQLite mode has no registry). construct_year and
set_year_companies are the services; the API endpoints only call them.
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import require_user
from app.db import database_enabled, session_scope
from app.logging_config import get_logger
from app.models import (
    FORMULA_FIELDS,
    NUMERIC_FIELDS,
    Company,
    CompanyYear,
    GfiColumn,
    ReportingYear,
    SourceFile,
)
from app.models import SourceCell as SourceCellRow
from app import edits_store
from app.pb1 import comment_defaults, pb1_template
from app.pb1_workbook import PB1_TABS, find_pb1_workbook, load_pb1_workbook
from app.reporting_years import get_data_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/api/migration", tags=["migration"])

ZERO = Decimal(0)


class MigrationError(ValueError):
    """A registry or construction request that can't be done; status_code is the HTTP status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class YearInfo(BaseModel):
    year: int
    origin: str  # "workbook" | "constructed"
    based_on_year: int | None = None
    source: str  # workbook file name, or "<year> (iz <based_on_year>)"
    companies: int  # companies shown in the year's table
    pb1: str | None = None  # the year's PB-1 form: workbook file name, "<year> PB-1 (iz <year>)", or none


class MigrationStatus(BaseModel):
    years: list[YearInfo]  # newest first
    next_year: int | None  # the year that can be constructed (latest + 1)
    source_year: int | None  # it is built from this year (the latest)


class RegistryCompany(BaseModel):
    company_id: int
    name: str
    pib: str | None = None
    referent: str | None = None
    office: str | None = None
    years: list[int]  # years the company is in (shown in the table)
    selected: bool  # in the given year (for the next year: proposed, i.e. in the source year)


class CompanySelection(BaseModel):
    company_ids: list[int]


class SelectionResult(BaseModel):
    year: int
    companies: int  # companies shown in the year now
    added: int
    restored: int
    removed: int


def _require_database() -> None:
    if not database_enabled():
        raise MigrationError(status.HTTP_409_CONFLICT, "Migracija needs the PostgreSQL database (DATABASE_URL)")


def _gfi_sources(session: Session) -> list[SourceFile]:
    return list(session.scalars(select(SourceFile).where(SourceFile.kind == "gfi").order_by(SourceFile.year.desc())))


def migration_status(session: Session) -> MigrationStatus:
    sources = _gfi_sources(session)
    counts = dict(
        session.execute(
            select(CompanyYear.year, func.count()).where(CompanyYear.active).group_by(CompanyYear.year)
        ).all()
    )
    pb1_sources = {
        s.year: s.file_name
        for s in session.scalars(select(SourceFile).where(SourceFile.kind == "pb1", SourceFile.origin == "constructed"))
    }
    years = [
        YearInfo(
            year=s.year, origin=s.origin, based_on_year=s.based_on_year,
            source=s.file_name, companies=counts.get(s.year, 0), pb1=_pb1_name(s.year, pb1_sources),
        )
        for s in sources
    ]
    latest = sources[0].year if sources else None
    return MigrationStatus(years=years, next_year=latest + 1 if latest else None, source_year=latest)


def _pb1_name(year: int, constructed: dict[int, str]) -> str | None:
    if year in constructed:
        return constructed[year]
    path = find_pb1_workbook(get_data_dir(), year)
    return path.name if path else None


def ensure_pb1_form(session: Session, year: int, based_on_year: int, user: str) -> SourceFile | None:
    """The PB-1 form of a constructed year: the same three tabs as the form of the year it is
    built from (every setting, formula and comment default with it), empty for every company.
    Recorded as a constructed 'pb1' source_file; nothing is copied or written to a workbook.
    None (with a warning) when the source year has no PB-1 form."""
    existing = session.scalar(select(SourceFile).where(SourceFile.kind == "pb1", SourceFile.year == year))
    if existing is not None or find_pb1_workbook(get_data_dir(), year) is not None:
        return existing
    template = pb1_template(based_on_year)
    if template is None:
        logger.warning("No PB-1 form for %s: %s has none to build it from", year, based_on_year)
        return None
    path, template_year = template
    pb1 = SourceFile(
        kind="pb1", year=year, origin="constructed", based_on_year=based_on_year,
        file_name=f"{year} PB-1 (iz {based_on_year})", sheet_name=PB1_TABS[0].sheet_prefix,
        sha256=None, file_mtime=None, imported_at=datetime.now(timezone.utc), imported_by=user,
    )
    session.add(pb1)
    session.flush()
    # As the form is in the app for the year it is built from: its form-level settings (shared
    # template edits, default comments) are taken over; the source year's defaults are stored first.
    comment_defaults(based_on_year, load_pb1_workbook(path), PB1_TABS[0].key, user)
    edits, defaults = edits_store.copy_pb1_form_settings(based_on_year, path.name, year, path.name, user)
    logger.info(
        "PB-1 form of %s constructed from %s (workbook %s, empty for every company; %d template edits, %d default comments taken over)",
        year, based_on_year, path.name, edits, defaults,
    )
    return pb1


def _latest_company_years(session: Session, before_year: int) -> dict[int, CompanyYear]:
    """Each company's most recent active company_year before `before_year` (company id -> row)."""
    rows = session.scalars(
        select(CompanyYear)
        .where(CompanyYear.year < before_year, CompanyYear.active)
        .order_by(CompanyYear.year.desc())
        .options(joinedload(CompanyYear.company), joinedload(CompanyYear.referent), joinedload(CompanyYear.office))
    )
    latest: dict[int, CompanyYear] = {}
    for cy in rows:
        latest.setdefault(cy.company_id, cy)
    return latest


def registry(session: Session, year: int) -> list[RegistryCompany]:
    """Every company of the registry with its details (from its latest year before `year`) and
    whether it is in `year`. For a year that doesn't exist yet, the companies of the source
    (latest) year are proposed."""
    exists = session.scalar(select(SourceFile.id).where(SourceFile.kind == "gfi", SourceFile.year == year))
    in_year = {
        cid for cid in session.scalars(
            select(CompanyYear.company_id).where(CompanyYear.year == year, CompanyYear.active)
        )
    }
    years_of: dict[int, list[int]] = {}
    for cid, y in session.execute(
        select(CompanyYear.company_id, CompanyYear.year).where(CompanyYear.active).order_by(CompanyYear.year)
    ):
        years_of.setdefault(cid, []).append(y)
    latest = _latest_company_years(session, year)
    source_year = max((cy.year for cy in latest.values()), default=None)
    out = []
    for company_id, cy in latest.items():
        selected = company_id in in_year if exists else cy.year == source_year
        out.append(RegistryCompany(
            company_id=company_id, name=cy.name, pib=cy.company.pib,
            referent=cy.referent.name if cy.referent else None, office=cy.office.name if cy.office else None,
            years=years_of.get(company_id, []), selected=selected,
        ))
    # Also companies that are only in `year` itself (none before it).
    for cy in session.scalars(
        select(CompanyYear).where(CompanyYear.year == year, CompanyYear.company_id.not_in(list(latest) or [0]))
        .options(joinedload(CompanyYear.company), joinedload(CompanyYear.referent), joinedload(CompanyYear.office))
    ):
        out.append(RegistryCompany(
            company_id=cy.company_id, name=cy.name, pib=cy.company.pib,
            referent=cy.referent.name if cy.referent else None, office=cy.office.name if cy.office else None,
            years=years_of.get(cy.company_id, []), selected=cy.active,
        ))
    return sorted(out, key=lambda c: c.name.casefold())


def _copy_company(
    session: Session, source_file: SourceFile, columns: list[GfiColumn], template: CompanyYear,
    template_formats: dict[str, str], row: int, now: datetime, user: str,
) -> CompanyYear:
    """A company's row in a constructed year: details carried over, status columns 0."""
    company_year = CompanyYear(
        company_id=template.company_id, year=source_file.year, source_file_id=source_file.id, source_row=row,
        name=template.name, referent_id=template.referent_id, office_id=template.office_id,
        kom=ZERO, preliminarni=ZERO, gfi_uradjen=ZERO, pb=ZERO, pb_predat=ZERO,
        updated_at=now, updated_by=user, active=True,
    )
    session.add(company_year)
    # The year's snapshot ("original" values): the carried-over details and the zeros, so the
    # table marks later changes as edits, like for an imported year.
    details = {
        "name": template.name,
        "pib": template.company.pib,
        "referent": template.referent.name if template.referent else None,
        "office": template.office.name if template.office else None,
    }
    for column in columns:
        cell = SourceCellRow(
            source_file_id=source_file.id, row=row, col=column.col,
            number_format=template_formats.get(column.col, "General"), is_formula=False,
        )
        if column.field in details:
            cell.value_text = details[column.field]
        elif column.field in NUMERIC_FIELDS:
            cell.value_number = ZERO
        elif column.field in FORMULA_FIELDS:
            cell.value_number, cell.is_formula = ZERO, True
        session.add(cell)
    return company_year


def _formats(session: Session, template: CompanyYear) -> dict[str, str]:
    """Number formats of the template row in its year (column letter -> format)."""
    return dict(
        session.execute(
            select(SourceCellRow.col, SourceCellRow.number_format).where(
                SourceCellRow.source_file_id == template.source_file_id, SourceCellRow.row == template.source_row
            )
        ).all()
    )


def construct_year(session: Session, year: int, company_ids: list[int], user: str) -> SelectionResult:
    """Builds `year` from the latest year with the selected companies (see the module doc)."""
    state = migration_status(session)
    if state.next_year is None:
        raise MigrationError(status.HTTP_409_CONFLICT, "No year to build from: import a GFI workbook first")
    if year != state.next_year:
        raise MigrationError(status.HTTP_409_CONFLICT, f"Only the next year ({state.next_year}) can be constructed")
    if not company_ids:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select at least one company")
    source = session.scalar(select(SourceFile).where(SourceFile.kind == "gfi", SourceFile.year == state.source_year))
    columns = list(session.scalars(
        select(GfiColumn).where(GfiColumn.source_file_id == source.id).order_by(GfiColumn.position)
    ))
    latest = _latest_company_years(session, year)
    unknown = sorted(set(company_ids) - set(latest))
    if unknown:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown companies: {unknown[:10]}")

    now = datetime.now(timezone.utc)
    if session.get(ReportingYear, year) is None:
        session.add(ReportingYear(year=year))
    target = SourceFile(
        kind="gfi", year=year, origin="constructed", based_on_year=source.year,
        file_name=f"{year} (iz {source.year})", sheet_name=source.sheet_name,
        sha256=None, file_mtime=None, imported_at=now, imported_by=user,
    )
    session.add(target)
    session.flush()
    for column in columns:
        session.add(GfiColumn(
            source_file_id=target.id, col=column.col, position=column.position, header=column.header, field=column.field,
        ))
    used_rows: set[int] = set()
    next_row = max((cy.source_row for cy in latest.values()), default=1) + 1
    for company_id in sorted(set(company_ids), key=lambda c: latest[c].source_row):
        template = latest[company_id]
        row = template.source_row
        if row in used_rows:  # a company from an older year whose row is taken
            row, next_row = next_row, next_row + 1
        used_rows.add(row)
        _copy_company(session, target, columns, template, _formats(session, template), row, now, user)
    ensure_pb1_form(session, year, source.year, user)
    logger.info(
        "Year %s constructed from %s by '%s': %d companies (details carried over, statuses 0)",
        year, source.year, user, len(used_rows),
    )
    return SelectionResult(year=year, companies=len(used_rows), added=len(used_rows), restored=0, removed=0)


def set_year_companies(session: Session, year: int, company_ids: list[int], user: str) -> SelectionResult:
    """Changes the companies of a constructed year: new ones are added like at construction, a
    deselected one is hidden (its values are kept), a reselected one is shown again."""
    target = session.scalar(select(SourceFile).where(SourceFile.kind == "gfi", SourceFile.year == year))
    if target is None:
        raise MigrationError(status.HTTP_404_NOT_FOUND, f"Year {year} doesn't exist")
    if target.origin != "constructed":
        raise MigrationError(
            status.HTTP_409_CONFLICT, f"{year} comes from a workbook; only constructed years can be changed here"
        )
    wanted = set(company_ids)
    if not wanted:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select at least one company")
    existing = {cy.company_id: cy for cy in session.scalars(select(CompanyYear).where(CompanyYear.year == year))}
    latest = _latest_company_years(session, year)
    unknown = sorted(wanted - set(latest) - set(existing))
    if unknown:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown companies: {unknown[:10]}")

    now = datetime.now(timezone.utc)
    added = restored = removed = 0
    for company_id, cy in existing.items():
        if company_id in wanted and not cy.active:
            cy.active, cy.updated_at, cy.updated_by = True, now, user
            restored += 1
        elif company_id not in wanted and cy.active:
            cy.active, cy.updated_at, cy.updated_by = False, now, user
            removed += 1
    new = wanted - set(existing)
    if new:
        columns = list(session.scalars(
            select(GfiColumn).where(GfiColumn.source_file_id == target.id).order_by(GfiColumn.position)
        ))
        used_rows = {cy.source_row for cy in existing.values()}
        next_row = max(used_rows | {cy.source_row for cy in latest.values()} | {1}) + 1
        for company_id in sorted(new, key=lambda c: latest[c].source_row):
            template = latest[company_id]
            row = template.source_row
            if row in used_rows:
                row, next_row = next_row, next_row + 1
            used_rows.add(row)
            _copy_company(session, target, columns, template, _formats(session, template), row, now, user)
            added += 1
    shown = len(wanted)
    logger.info(
        "Companies of %s changed by '%s': %d shown (%d added, %d restored, %d hidden)",
        year, user, shown, added, restored, removed,
    )
    return SelectionResult(year=year, companies=shown, added=added, restored=restored, removed=removed)


def _run(work):
    try:
        _require_database()
        with session_scope() as session:
            return work(session)
    except MigrationError as exc:
        if exc.status_code < 500:
            logger.warning("Migracija request refused: %s", exc)
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get("")
def get_migration(username: str = Depends(require_user)) -> MigrationStatus:
    return _run(migration_status)


@router.get("/years/{year}/companies")
def get_year_companies(year: int, username: str = Depends(require_user)) -> list[RegistryCompany]:
    """The registry with the companies of `year` (or the proposal for the next year) selected."""
    return _run(lambda session: registry(session, year))


@router.post("/years/{year}")
def post_construct_year(year: int, selection: CompanySelection, username: str = Depends(require_user)) -> SelectionResult:
    return _run(lambda session: construct_year(session, year, selection.company_ids, username))


@router.put("/years/{year}/companies")
def put_year_companies(year: int, selection: CompanySelection, username: str = Depends(require_user)) -> SelectionResult:
    return _run(lambda session: set_year_companies(session, year, selection.company_ids, username))
