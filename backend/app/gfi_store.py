"""GFI data in PostgreSQL, and which cells can be edited.

GfiStore reads and writes the database only. The data gets in once per year through
`python -m app.gfi_import <year>` (or the Migracija page); the app never opens a workbook.
It returns a SourceTable with the original values (the import snapshot) and the edits
(current values that differ from them), which the API shows on top.

Editing rules (see edit_kind):
- GFI ZA RAD and PB-1,PB-2 za rad are formulas in every row (FORMULA_FIELDS: kom - GFI
  uradjen, PB-1,PB-2 - Predat; empty counts as 0), computed by the API, never editable;
- the other numeric GFI status columns (kom, Preliminarni, GFI uradjen, PB-1,PB-2,
  Predat): numbers and empty cells (they can be
  filled in), not formulas or text. The Home page edits only cells that hold a number in
  Excel; the Company Registry also fills empty ones;
- company details (NAZIV, PIB, REFERENT, office): text. The Home page shows these
  read-only; the Company Registry page edits them;
- everything else (unmapped columns): read-only.
Only the company list is stored (gfi_workbook.company_list at import): 165 rows for 2025,
without the R.B. columns. "#" in the frontend is the position in that list.
Company identity is the Excel row (company_year in the database). A PB-1 file is linked
to that identity once and the link is stored (pb1_link), so editing a company's name or
PIB never changes which company a PB-1 file belongs to.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.db import session_scope
from app.gfi_table import CellValue, SourceCell, SourceTable
from app.logging_config import get_logger
from app.models import NUMERIC_FIELDS, ChangeLog, CompanyYear, GfiColumn, Office, Pb1Link, Referent, SourceFile
from app.models import SourceCell as SourceCellRow

logger = get_logger(__name__)

# (Excel row, column letter) -> (current value, original value when the edit was made)
Edits = dict[tuple[int, str], tuple[CellValue, CellValue]]
EditKind = Literal["number", "text"]

# Workbook header (whitespace removed, upper case) -> field. First match wins.
HEADER_FIELDS = {
    "NAZIV": "name",
    "PIB": "pib",
    "REFERENT": "referent",
    "PRELIMINARNI": "preliminarni",
    "GFIURADJEN": "gfi_uradjen",
    "GFIZARAD": "gfi_za_rad",
    "PB-1,PB-2": "pb",
    "PB-1,PB-2PREDAT": "pb_predat",
    "PB-1,PB-2ZARAD": "pb_za_rad",
}
# The unnamed column right after REFERENT holds the office (SLAVIJA, FER, LJILJA, ...).
OFFICE_FIELD = "office"
REQUIRED_FIELDS = (*HEADER_FIELDS.values(), OFFICE_FIELD)
# Company details, edited as text (Edit Company Data page).
TEXT_FIELDS = ("name", "pib", "referent", OFFICE_FIELD)
# Input rules (user's decisions, 2026-11-14), the same on every page; the frontend applies them
# while typing, the backend enforces them:
# - NAZIV, REFERENT, office: upper case (as with caps lock on);
# - PIB: digits only, 9 (PIB of a company) or 13 (JMBG of a natural person); empty is allowed;
# - status columns (Preliminarni, GFI uradjen, PB-1, PB-2, Predat): 0 or 1, never empty: an
#   empty value is stored as 0 (also at import and construction; the database refuses empty);
# - PIB, REFERENT, office: "-" (shown for an empty one) entered as a value means empty.
# Upper case applies to edits; values from an import or a construction are stored as they are.
PIB_INPUT = re.compile(r"^(\d{9}|\d{13})$")
UPPER_CASE_FIELDS = ("name", "referent", OFFICE_FIELD)
STATUS_VALUES = (0, 1)
EMPTY_MARK = "-"


def normalize_header(header: str | None) -> str:
    return re.sub(r"\s+", "", header or "").upper()


def map_columns(headers: dict[str, str | None]) -> dict[str, str]:
    """Column letter -> field, found by header text. Raises ValueError if a field is missing."""
    fields: dict[str, str] = {}
    keys = list(headers)
    for i, key in enumerate(keys):
        field = HEADER_FIELDS.get(normalize_header(headers[key]))
        if field and field not in fields.values():
            fields[key] = field
            if field == "referent" and i + 1 < len(keys) and not normalize_header(headers[keys[i + 1]]):
                fields[keys[i + 1]] = OFFICE_FIELD
    missing = [f for f in REQUIRED_FIELDS if f not in fields.values()]
    if missing:
        raise ValueError(f"GFI columns not found in the workbook headers: {', '.join(missing)}")
    return fields


def edit_kind(source: SourceTable, column: str, cell: SourceCell) -> EditKind | None:
    """How a cell can be edited: "number", "text" or None (read-only)."""
    if not source.fields:
        # Unknown workbook layout: the original rule (plain numeric cells only).
        return "number" if cell.is_editable else None
    field = source.fields.get(column)
    if field in TEXT_FIELDS:
        return None if cell.is_formula else "text"
    if field in NUMERIC_FIELDS:
        # The status columns (Preliminarni, GFI uradjen, PB-1, PB-2, Predat) are set only by the
        # steps of the company's PB-1 reports, never by hand (user, 2026-11-17; app.pb1).
        return None
    return None


def is_blank(value: CellValue) -> bool:
    """Empty cell, or only spaces (e.g. " " in the workbook)."""
    return value is None or (isinstance(value, str) and not value.strip())


def text_of(value: CellValue) -> str | None:
    """Text form used to compare company details (PIB 114113887 == "114113887")."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or None


def is_original(kind: EditKind, value: CellValue, original: CellValue) -> bool:
    if kind == "text":
        return text_of(value) == text_of(original)
    if value is None:
        return is_blank(original)  # cleared a cell that was empty in Excel
    return value == original and not isinstance(original, (str, bool))


def clean_text(field: str | None, value: str | None) -> str | None:
    """Validate and normalize a text edit (see the input rules above). Raises HTTPException 422."""
    value = value.strip() if value is not None else None
    value = value or None
    if value == EMPTY_MARK and field != "name":
        value = None  # "-" is how an empty detail is shown: entered, it means empty
    if field in UPPER_CASE_FIELDS and value is not None:
        value = value.upper()
    if field == "name" and value is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Naziv firme ne može biti prazan.")
    if field == "pib" and value is not None and not PIB_INPUT.match(value):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "PIB mora imati 9 cifara, ili 13 cifara za JMBG fizičkog lica."
        )
    return value


def status_value(field: str | None, value: float | int | None) -> float | int | None:
    """A status column (Preliminarni ... Predat) takes only 0 or 1; empty means 0. Raises 422."""
    if field not in NUMERIC_FIELDS:
        return value
    if value is None:
        return 0
    if value not in STATUS_VALUES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dozvoljene su samo vrednosti 0 i 1.")
    return value


def to_decimal(value: float | int | None) -> Decimal | None:
    # repr() keeps the exact float (shortest round-trip form), e.g. 0.1 -> Decimal("0.1").
    return None if value is None else Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def from_decimal(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


@dataclass(frozen=True)
class StoredPb1Link:
    pb1_company: str  # company name as written in the PB-1 file when it was linked
    row: int | None  # Excel row of the linked company in the current company list (None: not in it)


class GfiStore:
    """GFI data in PostgreSQL: the years, the tables, cell edits and the PB-1 link."""

    name = "PostgreSQL"

    def pb1_link(self, year: int, pb1_file: str) -> StoredPb1Link | None:
        with session_scope() as session:
            link = session.get(Pb1Link, (year, pb1_file))
            if link is None:
                return None
            company_year = session.get(CompanyYear, link.company_year_id)
            return StoredPb1Link(link.pb1_company, company_year.source_row if company_year else None)

    def save_pb1_link(self, year: int, pb1_file: str, pb1_company: str, row: int, user: str) -> None:
        with session_scope() as session:
            company_year = session.scalar(
                select(CompanyYear).where(CompanyYear.year == year, CompanyYear.source_row == row)
            )
            if company_year is None:
                raise ValueError(f"No company in row {row} for {year}")
            link = session.get(Pb1Link, (year, pb1_file)) or Pb1Link(year=year, pb1_file_name=pb1_file)
            link.pb1_company, link.company_year_id = pb1_company, company_year.id
            link.linked_by, link.linked_at = user, datetime.now(timezone.utc)
            session.add(link)

    def delete_pb1_link(self, year: int, pb1_file: str) -> None:
        with session_scope() as session:
            link = session.get(Pb1Link, (year, pb1_file))
            if link is not None:
                session.delete(link)

    def years(self) -> list[int]:
        with session_scope() as session:
            return list(
                session.scalars(
                    select(SourceFile.year).where(SourceFile.kind == "gfi").order_by(SourceFile.year.desc())
                )
            )

    def load(self, year: int) -> tuple[SourceTable, Edits]:
        """The GFI table with original values, and the edits to show on top of it."""
        with session_scope() as session:
            return load_table(session, year)

    def save(
        self, year: int, row: int, column: str, kind: EditKind, value: CellValue, original: CellValue, user: str
    ) -> bool:
        """Stores a new value for an editable cell. Returns True if it now differs from the original."""
        with session_scope() as session:
            source_file = _source_file(session, year)
            field = session.scalar(
                select(GfiColumn.field).where(GfiColumn.source_file_id == source_file.id, GfiColumn.col == column)
            )
            company_year = session.scalar(
                select(CompanyYear)
                .where(CompanyYear.year == year, CompanyYear.source_row == row, CompanyYear.active)
                .options(joinedload(CompanyYear.company), joinedload(CompanyYear.referent), joinedload(CompanyYear.office))
            )
            allowed = NUMERIC_FIELDS if kind == "number" else TEXT_FIELDS
            if field not in allowed or company_year is None:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Polje {column}{row} je samo za čitanje.")
            now = datetime.now(timezone.utc)
            log = ChangeLog(
                company_year_id=company_year.id, year=year, source_row=row, col=column, field=field,
                changed_by=user, changed_at=now,
            )
            if kind == "number":
                log.old_value, log.new_value = getattr(company_year, field), to_decimal(value)
                setattr(company_year, field, log.new_value)
            else:
                log.old_text, log.new_text = current_text(company_year, field), value
                set_text(session, company_year, field, value)
            session.add(log)
            company_year.updated_at, company_year.updated_by = now, user
        return not is_original(kind, value, original)


def current_text(company_year: CompanyYear, field: str) -> str | None:
    if field == "name":
        return company_year.name
    if field == "pib":
        return company_year.company.pib
    if field == "referent":
        return company_year.referent.name if company_year.referent else None
    return company_year.office.name if company_year.office else None


def lookup_id(session: Session, model: type[Referent] | type[Office], name: str | None) -> int | None:
    """Id of the referent/office with this exact name; created if it doesn't exist."""
    if name is None:
        return None
    existing = session.scalar(select(model).where(model.name == name))
    if existing is None:
        existing = model(name=name)
        session.add(existing)
        session.flush()
    return existing.id


def set_text(session: Session, company_year: CompanyYear, field: str, value: str | None) -> None:
    """Set a company detail. The company keeps its id, so its identity and PB-1 link are unchanged."""
    if field == "name":
        company_year.name = value
        company_year.company.name = value
    elif field == "pib":
        company_year.company.pib = value
    elif field == "referent":
        old_id = company_year.referent_id
        company_year.referent_id = lookup_id(session, Referent, value)
        session.flush()
        _drop_if_unused(session, Referent, CompanyYear.referent_id, old_id)
    else:
        old_id = company_year.office_id
        company_year.office_id = lookup_id(session, Office, value)
        session.flush()
        _drop_if_unused(session, Office, CompanyYear.office_id, old_id)
    session.flush()
    session.expire(company_year, ["referent", "office"])


def _drop_if_unused(session: Session, model: type[Referent] | type[Office], column, old_id: int | None) -> None:
    """Removes a referent / office that no company uses any more (e.g. a name typed and then
    changed back), so the lookup tables hold only names in use."""
    if old_id is None:
        return
    if session.scalar(select(CompanyYear.id).where(column == old_id).limit(1)) is None:
        session.execute(delete(model).where(model.id == old_id))
        logger.info("%s %d removed: no company uses it any more", model.__tablename__, old_id)


def _source_file(session: Session, year: int) -> SourceFile:
    source_file = session.scalar(select(SourceFile).where(SourceFile.kind == "gfi", SourceFile.year == year))
    if source_file is None:
        logger.warning("No GFI data in the database for reporting year %s", year)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nema GFI podataka za godinu {year}.")
    return source_file


def _original_value(cell: SourceCellRow) -> CellValue:
    if cell.value_number is not None:
        return from_decimal(cell.value_number)
    if cell.value_text is not None:
        return cell.value_text
    return cell.value_bool


def load_table(session: Session, year: int) -> tuple[SourceTable, Edits]:
    """Build the GFI table from the database: originals from the snapshot, current values
    from company_year. Values that differ from the original are returned as edits."""
    source_file = _source_file(session, year)
    columns = list(
        session.scalars(
            select(GfiColumn).where(GfiColumn.source_file_id == source_file.id).order_by(GfiColumn.position)
        )
    )
    field_of = {c.col: c.field for c in columns if c.field}
    company_years = {
        cy.source_row: cy
        for cy in session.scalars(
            select(CompanyYear)
            # Only the year's selected companies (a constructed year's deselected ones are hidden).
            .where(CompanyYear.source_file_id == source_file.id, CompanyYear.active)
            .options(joinedload(CompanyYear.company), joinedload(CompanyYear.referent), joinedload(CompanyYear.office))
        )
    }
    cells = session.scalars(
        select(SourceCellRow).where(SourceCellRow.source_file_id == source_file.id).order_by(SourceCellRow.row)
    )

    rows: dict[int, dict[str, SourceCell]] = {}
    edits: Edits = {}
    for cell in cells:
        cy = company_years.get(cell.row)
        if cy is None:
            continue
        field = field_of.get(cell.col)
        original = _original_value(cell)
        value = original
        if field in TEXT_FIELDS:
            current = current_text(cy, field)
            if text_of(current) != text_of(original):
                edits[(cell.row, cell.col)] = (current, original)
        elif field in NUMERIC_FIELDS:
            # A status column: always its current value, set only by the PB-1 report steps (user,
            # 2026-11-17); not an edit of the workbook value (the snapshot keeps that).
            value = from_decimal(getattr(cy, field))
        rows.setdefault(cell.row, {})[cell.col] = SourceCell(
            value=value,
            number_format=cell.number_format,
            is_formula=cell.is_formula,
            # Numbers can be edited only in the numeric GFI status columns.
            locked=field not in NUMERIC_FIELDS,
        )

    source = SourceTable(
        workbook=source_file.file_name,
        sheet=source_file.sheet_name,
        headers={c.col: c.header for c in columns},
        rows=rows,
        fields=field_of,
    )
    return source, edits


def get_gfi_store() -> GfiStore:
    return GfiStore()
