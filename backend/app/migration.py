"""Migracija: the company registry and building the next reporting year from the latest one.

The registry is every company of the database (`company`), each with its details from its most
recent year. The next year (latest year + 1) is built in the app ("constructed"), not imported
from a workbook. **It must behave exactly like the year it is built from** (user's rule): it is
a copy of that year (columns, each company's original cells with their kinds, formats and
formula flags, the PB-1 form and its settings) with only the agreed changes applied: company
details (NAZIV, PIB, REFERENT, office) as they are now (edits included); status columns that
hold a number start at 0 (empty ones stay empty); company values and PB-1 amounts are not
carried. Anything added to the app later must be carried the same way (YEAR_TABLES below; the
backend doesn't start while a table has no policy). The table is then shown like any year.

The year's PB-1 form is constructed with it (ensure_pb1_form): a 'pb1' source_file of origin
"constructed" pointing to the year it was built from, so the year has the same three PB-1 tabs
(and everything set up for them), built from that year's form, empty (0) for every company.

The companies of a constructed year can be changed later: a deselected company is hidden
(`company_year.active`), not deleted, so its values are back when it is selected again.

The latest year, if it was constructed here, can be deleted completely (delete_year): a wrong
construction is undone. Only the latest one (no other year is built from it); a year imported
from a workbook is never deleted here. Nothing of the year is left behind (its change_log history
included) and nothing of the other years is changed.

construct_year and set_year_companies are the services; the API endpoints only call them.
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import require_user
from app.db import session_scope
from app.logging_config import get_logger
from app.models import (
    FORMULA_FIELDS,
    NUMERIC_FIELDS,
    ChangeLog,
    Company,
    CompanyYear,
    GfiColumn,
    Office,
    Pb1CompanyEdit,
    Pb1ReportEvent,
    Pb1ReportState,
    Pb1Link,
    Pb1TemplateEdit,
    Referent,
    ReportingYear,
    SourceFile,
)
from app.models import SourceCell as SourceCellRow
from app.gfi_store import clean_text, lookup_id, text_of
from app.pb1_store import copy_form_settings, form_source
from app.pb1_workbook import PB1_TABS

logger = get_logger(__name__)

router = APIRouter(prefix="/api/migration", tags=["migration"])

ZERO = Decimal(0)

# What constructing a year (construct_year / set_year_companies / ensure_pb1_form) and deleting
# the latest constructed year (delete_year) do with each table. Every table of the database must
# be listed here or in GLOBAL_TABLES: check_table_policies() refuses to start the backend
# otherwise, so a table added later can't be forgotten by the Migracija (user's rule: a new
# year is built the way the current state is, and deleting it leaves nothing behind).
YEAR_TABLES: dict[str, str] = {
    "reporting_year": "construct: the new year | delete: removed",
    "source_file": "construct: a 'constructed' gfi and pb1 source (based_on_year) | delete: removed",
    "gfi_column": "construct: copied from the source year | delete: removed (cascade)",
    "source_cell": "construct: each company's source cells copied, statuses holding a number set to 0 (_copy_company) | delete: removed (cascade)",
    "company_year": "construct: per selected company, details carried, statuses as in source_cell | delete: removed (cascade)",
    "import_issue": "construct: not carried (workbook import only) | delete: removed (cascade)",
    "change_log": "construct: not carried (history of the source year) | delete: the year's rows removed",
    "pb1_link": "construct: not carried (the file's amounts belong to the workbook year) | delete: removed",
    "pb1_sheet": "construct: not copied, the form is shared from the workbook year (form_source) | delete: only constructed sources, no rows",
    "pb1_sheet_column": "construct: not copied (as pb1_sheet) | delete: none",
    "pb1_source_cell": "construct: not copied (as pb1_sheet) | delete: none",
    "pb1_template_edit": "construct: copied (form-level settings, copy_form_settings) | delete: removed",
    "pb1_company_edit": "construct: not carried (company values of both reports start empty) | delete: removed",
    "pb1_report_state": "construct: not carried (a new year starts with the preliminary report) | delete: removed",
    "pb1_report_event": "construct: not carried (history of the source year's reports) | delete: removed",
}
# Not tied to a year: kept by construction and deletion (unused companies / lookups are removed
# by delete_year after its year's rows are gone).
# pb1_comment: the PB-1 comments, one set for every year and company (Global Settings).
GLOBAL_TABLES = frozenset({"company", "referent", "office", "app_user", "user_session", "pb1_comment"})


def check_table_policies() -> None:
    """Raises RuntimeError when a database table has no Migracija policy (see YEAR_TABLES)."""
    from app.models import Base

    tables = set(Base.metadata.tables)
    missing = sorted(tables - set(YEAR_TABLES) - GLOBAL_TABLES)
    stale = sorted((set(YEAR_TABLES) | GLOBAL_TABLES) - tables)
    if missing or stale:
        raise RuntimeError(
            f"Migracija table policies out of date (app/migration.py YEAR_TABLES / GLOBAL_TABLES):"
            f" no policy for {missing or '-'}; unknown {stale or '-'}"
        )


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
    deletable: bool = False  # the latest year, constructed here: can be deleted (delete_year)


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


class DeleteResult(BaseModel):
    year: int
    companies: int  # company years removed (shown and hidden)
    pb1_values: int  # PB-1 values removed (company values, template edits)


class CompanySelection(BaseModel):
    company_ids: list[int]


class SelectionResult(BaseModel):
    year: int
    companies: int  # companies shown in the year now
    added: int
    restored: int
    removed: int


def _gfi_sources(session: Session) -> list[SourceFile]:
    return list(session.scalars(select(SourceFile).where(SourceFile.kind == "gfi").order_by(SourceFile.year.desc())))


def migration_status(session: Session) -> MigrationStatus:
    sources = _gfi_sources(session)
    counts = dict(
        session.execute(
            select(CompanyYear.year, func.count()).where(CompanyYear.active).group_by(CompanyYear.year)
        ).all()
    )
    pb1_sources = {s.year: s.file_name for s in session.scalars(select(SourceFile).where(SourceFile.kind == "pb1"))}
    years = [
        YearInfo(
            year=s.year, origin=s.origin, based_on_year=s.based_on_year,
            source=s.file_name, companies=counts.get(s.year, 0), pb1=pb1_sources.get(s.year),
            deletable=i == 0 and s.origin == "constructed",
        )
        for i, s in enumerate(sources)
    ]
    latest = sources[0].year if sources else None
    return MigrationStatus(years=years, next_year=latest + 1 if latest else None, source_year=latest)


def ensure_pb1_form(session: Session, year: int, based_on_year: int, user: str) -> SourceFile | None:
    """The PB-1 form of a constructed year: the same three tabs as the form of the year it is
    built from (every setting and formula with it; the comments are global), empty for every company.
    Recorded as a constructed 'pb1' source_file (database only; no file is read or written).
    None (with a warning) when the source year has no PB-1 form."""
    existing = session.scalar(select(SourceFile).where(SourceFile.kind == "pb1", SourceFile.year == year))
    if existing is not None:
        return existing
    template = form_source(session, based_on_year)
    if template is None:
        logger.warning("No PB-1 form for %s: %s has none to build it from", year, based_on_year)
        return None
    workbook = template[0].file_name
    pb1 = SourceFile(
        kind="pb1", year=year, origin="constructed", based_on_year=based_on_year,
        file_name=f"{year} PB-1 (iz {based_on_year})", sheet_name=PB1_TABS[0].sheet_prefix,
        sha256=None, file_mtime=None, imported_at=datetime.now(timezone.utc), imported_by=user,
    )
    session.add(pb1)
    session.flush()
    # As the form is in the app for the year it is built from: its form-level settings (shared
    # template edits) are taken over; the comments are global (pb1_comment).
    edits = copy_form_settings(session, based_on_year, year, user)
    logger.info(
        "PB-1 form of %s constructed from %s (workbook %s, empty for every company; %d template edits taken over)",
        year, based_on_year, workbook, edits,
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


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _copy_cell(target: SourceCellRow, source: SourceCellRow) -> None:
    """The source cell exactly: value of the same kind, number format, formula flag."""
    target.value_number, target.value_text, target.value_bool = source.value_number, source.value_text, source.value_bool
    target.number_format, target.is_formula = source.number_format, source.is_formula


def _cell_value(cell: SourceCellRow | None) -> object:
    if cell is None:
        return None
    if cell.value_number is not None:
        return cell.value_number
    return cell.value_text if cell.value_text is not None else cell.value_bool


def _copy_company(
    session: Session, source_file: SourceFile, columns: list[GfiColumn], template: CompanyYear,
    source_cells: dict[str, SourceCellRow], row: int, now: datetime, user: str,
) -> CompanyYear:
    """A company's row in a constructed year, built as a copy of its row in the source year so
    that it behaves exactly the same (which cells are editable where, colors, alignment, "-"/0,
    formats, formulas). Each snapshot cell is the source year's original cell; only the agreed
    changes are applied:
    - status columns (Preliminarni ... Predat) and the formula columns: 0 (status columns are
      never empty; a non-number formula cell of the source stays as it is);
    - company details (NAZIV, PIB, REFERENT, office): the current value (edits included); when
      it equals the source's original, the original cell is copied as it is (same type, e.g. a
      PIB stored as a number), otherwise the current value (a digits-only PIB that was a number
      stays a number).
    Columns without a mapped field are copied as they are."""
    field_col = {c.field: c.col for c in columns if c.field}
    statuses = {field: ZERO for field in NUMERIC_FIELDS}  # never empty
    company_year = CompanyYear(
        company_id=template.company_id, year=source_file.year, source_file_id=source_file.id, source_row=row,
        name=template.name, referent_id=template.referent_id, office_id=template.office_id,
        updated_at=now, updated_by=user, active=True, **statuses,
        # The company's type (PDP / PPDG-1S) is carried as it is (user, 2026-11-25).
        form_type=getattr(template, "form_type", None) or "pdp",
    )
    session.add(company_year)
    details = {
        "name": template.name,
        "pib": template.company.pib,
        "referent": template.referent.name if template.referent else None,
        "office": template.office.name if template.office else None,
    }
    for column in columns:
        source = source_cells.get(column.col)
        cell = SourceCellRow(source_file_id=source_file.id, row=row, col=column.col, number_format="General", is_formula=False)
        if source is not None:
            _copy_cell(cell, source)
        if column.field in details:
            current = details[column.field]
            if text_of(current) != text_of(_from_db(_cell_value(source))):
                cell.value_number = cell.value_text = cell.value_bool = None
                if column.field == "pib" and source is not None and source.value_number is not None and current and current.isdigit():
                    cell.value_number = Decimal(current)
                else:
                    cell.value_text = current
        elif column.field in NUMERIC_FIELDS:
            cell.value_number, cell.value_text, cell.value_bool = ZERO, None, None
        elif column.field in FORMULA_FIELDS:
            if source is not None and source.value_number is not None:
                cell.value_number = ZERO
        session.add(cell)
    return company_year


def _from_db(value: object) -> object:
    """A snapshot value as the app compares it (Decimal -> int / float)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _source_cells(session: Session, template: CompanyYear) -> dict[str, SourceCellRow]:
    """The template row's original cells in its year (column letter -> cell)."""
    return {
        cell.col: cell
        for cell in session.scalars(
            select(SourceCellRow).where(
                SourceCellRow.source_file_id == template.source_file_id, SourceCellRow.row == template.source_row
            )
        )
    }


def construct_year(session: Session, year: int, company_ids: list[int], user: str) -> SelectionResult:
    """Builds `year` from the latest year with the selected companies (see the module doc)."""
    state = migration_status(session)
    if state.next_year is None:
        raise MigrationError(status.HTTP_409_CONFLICT, "Nema godine iz koje bi se pravila nova: prvo treba uvesti GFI fajl.")
    if year != state.next_year:
        raise MigrationError(status.HTTP_409_CONFLICT, f"Može se napraviti samo sledeća godina ({state.next_year}).")
    if not company_ids:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Izaberite bar jednu firmu.")
    source = session.scalar(select(SourceFile).where(SourceFile.kind == "gfi", SourceFile.year == state.source_year))
    columns = list(session.scalars(
        select(GfiColumn).where(GfiColumn.source_file_id == source.id).order_by(GfiColumn.position)
    ))
    latest = _latest_company_years(session, year)
    unknown = sorted(set(company_ids) - set(latest))
    if unknown:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Nepoznate firme: {unknown[:10]}")

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
        _copy_company(session, target, columns, template, _source_cells(session, template), row, now, user)
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
        raise MigrationError(status.HTTP_404_NOT_FOUND, f"Godina {year} ne postoji.")
    if target.origin != "constructed":
        raise MigrationError(
            status.HTTP_409_CONFLICT, f"Godina {year} je uvezena; ovde se menjaju samo napravljene godine."
        )
    wanted = set(company_ids)
    if not wanted:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Izaberite bar jednu firmu.")
    existing = {cy.company_id: cy for cy in session.scalars(select(CompanyYear).where(CompanyYear.year == year))}
    latest = _latest_company_years(session, year)
    unknown = sorted(wanted - set(latest) - set(existing))
    if unknown:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Nepoznate firme: {unknown[:10]}")

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
            _copy_company(session, target, columns, template, _source_cells(session, template), row, now, user)
            added += 1
    shown = len(wanted)
    logger.info(
        "Companies of %s changed by '%s': %d shown (%d added, %d restored, %d hidden)",
        year, user, shown, added, restored, removed,
    )
    return SelectionResult(year=year, companies=shown, added=added, restored=restored, removed=removed)


FORM_TYPES = ("pdp", "ppdg")  # PDP / PPDG-1S (user, 2026-11-25)


class NewCompany(BaseModel):
    name: str | None = None
    pib: str | None = None
    referent: str | None = None
    office: str | None = None
    form_type: str = "pdp"  # "pdp" or "ppdg" (PPDG-1S)


class AddedCompany(BaseModel):
    year: int
    row: int  # the new company's row (source_row): the last row of the year's table
    company_id: int
    name: str


def add_company(session: Session, year: int, details: NewCompany, user: str) -> AddedCompany:
    """Adds a new company to `year` (user, 2026-11-25: Edit Company Data, "Dodaj firmu"): a new
    company with its row at the end of the year's table. The row is built like a company of a
    constructed year (_copy_company), from the year's last row as the template of the cells
    (column kinds, number formats, formula flags), with the new company's details (the same
    input rules as editing them, clean_text) and every status 0; so it behaves exactly like the
    other rows: Home, Edit Company Data, its PB-1 form (empty amounts), the PDF report, and it is
    carried by the next Migracija like any company of the year. Its row number is above every
    row used in any year, so no later construction can collide with it."""
    try:
        name = clean_text("name", details.name)
        pib = clean_text("pib", details.pib)
        referent = clean_text("referent", details.referent)
        office = clean_text("office", details.office)
    except HTTPException as exc:
        raise MigrationError(exc.status_code, str(exc.detail)) from None
    if details.form_type not in FORM_TYPES:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Tip firme mora biti PDP ili PPDG-1S.")
    source_file = session.scalar(select(SourceFile).where(SourceFile.kind == "gfi", SourceFile.year == year))
    if source_file is None:
        raise MigrationError(status.HTTP_404_NOT_FOUND, f"Godina {year} ne postoji.")
    year_rows = list(session.scalars(
        select(CompanyYear).where(CompanyYear.year == year).options(
            joinedload(CompanyYear.company), joinedload(CompanyYear.referent), joinedload(CompanyYear.office)
        )
    ))
    if any(cy.active and cy.name == name for cy in year_rows):
        raise MigrationError(status.HTTP_409_CONFLICT, f"Firma {name} već postoji u godini {year}.")
    active = [cy for cy in year_rows if cy.active] or year_rows
    if not active:
        raise MigrationError(status.HTTP_409_CONFLICT, f"Godina {year} nema nijednu firmu po kojoj bi se napravio red.")
    template = max(active, key=lambda cy: cy.source_row)
    columns = list(session.scalars(
        select(GfiColumn).where(GfiColumn.source_file_id == source_file.id).order_by(GfiColumn.position)
    ))
    row = (session.scalar(select(func.max(CompanyYear.source_row))) or 1) + 1
    now = datetime.now(timezone.utc)
    company = Company(name=name, pib=pib, created_at=now)
    session.add(company)
    session.flush()
    referent_id, office_id = lookup_id(session, Referent, referent), lookup_id(session, Office, office)
    # The new company's details in the shape _copy_company reads from its template.
    details_row = type("NewRow", (), {
        "company_id": company.id, "name": name, "referent_id": referent_id, "office_id": office_id,
        "form_type": details.form_type,
        "company": company,
        "referent": session.get(Referent, referent_id) if referent_id else None,
        "office": session.get(Office, office_id) if office_id else None,
    })()
    _copy_company(session, source_file, columns, details_row, _source_cells(session, template), row, now, user)
    session.flush()
    logger.info(
        "Company %r (PIB %s) added to %s by '%s' as row %d (template row %d)",
        name, pib, year, user, row, template.source_row,
    )
    return AddedCompany(year=year, row=row, company_id=company.id, name=name)


class YearCompany(BaseModel):
    row: int
    name: str
    pib: str | None = None
    referent: str | None = None
    office: str | None = None
    # Why it can't be deleted (it holds entered data), or None when it can.
    blocked: str | None = None


class CompanyRows(BaseModel):
    rows: list[int]


class DeletedCompanies(BaseModel):
    year: int
    deleted: int
    companies_removed: int  # companies no other year uses, removed with their last row


def _blocked_reason(session: Session, company_year: CompanyYear) -> str | None:
    """Why a company of a year can't be deleted: it holds data entered in the app (user,
    2026-11-25: only companies without data are deleted)."""
    cy_id = company_year.id
    checks = (
        (Pb1CompanyEdit, "ima PB-1 iznose"),
        (Pb1ReportState, "ima korake izveštaja"),
        (Pb1ReportEvent, "ima istoriju izveštaja"),
        (Pb1Link, "vezana je za PB-1 obrazac"),
        (ChangeLog, "ima istoriju izmena"),
    )
    for model, reason in checks:
        query = select(model.company_year_id).where(model.company_year_id == cy_id)
        if model is ChangeLog:
            # Only edits made by people: the automatic entries of a schema migration (e.g.
            # "migration 0020", statuses aligned with the report steps) are not data entered.
            query = query.where(ChangeLog.changed_by.not_like("migration %"))
        if session.scalar(query.limit(1)) is not None:
            return reason
    if any(getattr(company_year, field) != ZERO for field in NUMERIC_FIELDS):
        return "ima postavljen status"
    return None


def year_companies(session: Session, year: int) -> list[YearCompany]:
    """The companies shown in `year` (table order) with whether each can be deleted."""
    rows = session.scalars(
        select(CompanyYear).where(CompanyYear.year == year, CompanyYear.active).order_by(CompanyYear.source_row).options(
            joinedload(CompanyYear.company), joinedload(CompanyYear.referent), joinedload(CompanyYear.office)
        )
    )
    return [
        YearCompany(
            row=cy.source_row, name=cy.name, pib=cy.company.pib,
            referent=cy.referent.name if cy.referent else None, office=cy.office.name if cy.office else None,
            blocked=_blocked_reason(session, cy),
        )
        for cy in rows
    ]


def delete_companies(session: Session, year: int, rows: list[int], user: str) -> DeletedCompanies:
    """Deletes companies from `year` permanently (user, 2026-11-25: Edit Company Data, "Obriši
    firme"): their row (company_year and its snapshot cells); the company itself when no other
    year has it; a referent / office no company uses any more. Only companies without data
    entered in the app (_blocked_reason); if any of the chosen ones has data, nothing is deleted
    (409). Nothing of other companies or years changes."""
    from app.gfi_store import _drop_if_unused  # noqa: PLC0415

    wanted = set(rows)
    if not wanted:
        raise MigrationError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Izaberite bar jednu firmu.")
    found = {
        cy.source_row: cy
        for cy in session.scalars(select(CompanyYear).where(CompanyYear.year == year, CompanyYear.source_row.in_(wanted)))
    }
    missing = sorted(wanted - set(found))
    if missing:
        raise MigrationError(status.HTTP_404_NOT_FOUND, f"U godini {year} nema firmi u redovima {missing[:10]}.")
    blocked = [(cy.name, reason) for cy in found.values() if (reason := _blocked_reason(session, cy))]
    if blocked:
        names = ", ".join(f"{name} ({reason})" for name, reason in blocked[:5])
        raise MigrationError(status.HTTP_409_CONFLICT, f"Ne brišu se firme sa podacima: {names}. Ništa nije obrisano.")
    removed = 0
    for cy in found.values():
        company_id, referent_id, office_id = cy.company_id, cy.referent_id, cy.office_id
        session.execute(delete(SourceCellRow).where(
            SourceCellRow.source_file_id == cy.source_file_id, SourceCellRow.row == cy.source_row
        ))
        session.delete(cy)
        session.flush()
        if session.scalar(select(CompanyYear.id).where(CompanyYear.company_id == company_id).limit(1)) is None:
            session.execute(delete(Company).where(Company.id == company_id))
            removed += 1
        _drop_if_unused(session, Referent, CompanyYear.referent_id, referent_id)
        _drop_if_unused(session, Office, CompanyYear.office_id, office_id)
        logger.info("Company %r (row %d) deleted from %s by '%s'", cy.name, cy.source_row, year, user)
    return DeletedCompanies(year=year, deleted=len(found), companies_removed=removed)


# Company details stored once per company (company table) and shared by all its years.
SHARED_DETAILS = ("name", "pib")


def _undo_shared_details(session: Session, year: int) -> int:
    """Before a year is deleted: the shared company details (company.name, company.pib) its edits
    changed get the value they would have without those edits: the last change made in another
    year, or, without one, the value before the first change. Based on change_log (every edit is
    logged), in time order. Returns the number of details restored."""
    touched = session.execute(
        select(CompanyYear.company_id, ChangeLog.field).distinct()
        .join(ChangeLog, ChangeLog.company_year_id == CompanyYear.id)
        .where(CompanyYear.year == year, ChangeLog.field.in_(SHARED_DETAILS))
    ).all()
    restored = 0
    for company_id, field in touched:
        history = session.execute(
            select(ChangeLog.year, ChangeLog.old_text, ChangeLog.new_text)
            .join(CompanyYear, ChangeLog.company_year_id == CompanyYear.id)
            .where(CompanyYear.company_id == company_id, ChangeLog.field == field)
            .order_by(ChangeLog.changed_at, ChangeLog.id)
        ).all()
        others = [h for h in history if h.year != year]
        value = others[-1].new_text if others else history[0].old_text
        company = session.get(Company, company_id)
        if getattr(company, field) != value:
            logger.info("Company %d %s restored to %r (its %s edits are deleted)", company_id, field, value, year)
            setattr(company, field, value)
            restored += 1
    session.flush()
    return restored


def delete_year(session: Session, year: int, user: str) -> DeleteResult:
    """Deletes the latest year, constructed here, completely: its companies' rows and values, its
    PB-1 form with every value entered in it, its edit history (change_log) and the year itself.
    Companies, referents and offices no other year uses are removed too (only ones the year itself
    brought in: a constructed year reuses the companies of the year it was built from), and the
    shared company details (name, PIB) its edits changed are restored (_undo_shared_details).
    Nothing of the year is left and nothing of the other years changes."""
    sources = _gfi_sources(session)
    target = next((s for s in sources if s.year == year), None)
    if target is None:
        raise MigrationError(status.HTTP_404_NOT_FOUND, f"Godina {year} ne postoji.")
    if target is not sources[0]:
        raise MigrationError(status.HTTP_409_CONFLICT, f"Može se obrisati samo poslednja godina ({sources[0].year}).")
    if target.origin != "constructed":
        raise MigrationError(status.HTTP_409_CONFLICT, f"Godina {year} je uvezena; može se obrisati samo napravljena godina.")
    built_from = session.scalar(select(func.count()).select_from(SourceFile).where(SourceFile.based_on_year == year, SourceFile.year != year))
    if built_from:
        raise MigrationError(status.HTTP_409_CONFLICT, f"Iz godine {year} je napravljena druga godina.")

    company_years = select(CompanyYear.id).where(CompanyYear.year == year)
    restored = _undo_shared_details(session, year)
    companies = session.scalar(select(func.count()).select_from(CompanyYear).where(CompanyYear.year == year))
    pb1_values = 0
    pb1_values += session.execute(delete(Pb1CompanyEdit).where(Pb1CompanyEdit.company_year_id.in_(company_years))).rowcount
    session.execute(delete(Pb1ReportState).where(Pb1ReportState.company_year_id.in_(company_years)))
    session.execute(delete(Pb1ReportEvent).where(Pb1ReportEvent.company_year_id.in_(company_years)))
    pb1_values += session.execute(delete(Pb1TemplateEdit).where(Pb1TemplateEdit.year == year)).rowcount
    session.execute(delete(Pb1Link).where(Pb1Link.year == year))
    history = session.execute(delete(ChangeLog).where(
        (ChangeLog.year == year) | ChangeLog.company_year_id.in_(company_years)
    )).rowcount
    # The year's sources; cascades to gfi_column, source_cell, company_year, import_issue (and a
    # PB-1 snapshot).
    session.execute(delete(SourceFile).where(SourceFile.year == year))
    session.execute(delete(ReportingYear).where(ReportingYear.year == year))
    session.flush()
    used_companies = select(CompanyYear.company_id)
    removed_companies = session.execute(delete(Company).where(Company.id.not_in(used_companies))).rowcount
    removed_lookups = session.execute(delete(Referent).where(Referent.id.not_in(
        select(CompanyYear.referent_id).where(CompanyYear.referent_id.is_not(None))
    ))).rowcount + session.execute(delete(Office).where(Office.id.not_in(
        select(CompanyYear.office_id).where(CompanyYear.office_id.is_not(None))
    ))).rowcount
    logger.warning(
        "Year %s deleted by '%s': %d company years, %d PB-1 values, %d history rows; %d shared company details restored;"
        " %d companies and %d referents/offices no longer used removed",
        year, user, companies, pb1_values, history, restored, removed_companies, removed_lookups,
    )
    return DeleteResult(year=year, companies=companies, pb1_values=pb1_values)


def _run(work):
    try:
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


@router.delete("/years/{year}")
def delete_constructed_year(year: int, username: str = Depends(require_user)) -> DeleteResult:
    """Deletes the latest year if it was constructed here (see delete_year)."""
    return _run(lambda session: delete_year(session, year, username))
