"""Company table API: GFI values (columns A..N) with user edits applied on top.

The data comes from PostgreSQL (see app.gfi_store).
"""

import math

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_user
from sqlalchemy import select

from app.db import session_scope
from app.models import CompanyYear as CompanyYearRow
from app.gfi_store import Edits, clean_text, edit_kind, get_gfi_store, status_value
from app.migration import (
    AddedCompany, CompanyRows, DeletedCompanies, MigrationError, NewCompany, YearCompany, add_company, delete_companies,
    year_companies,
)
from app.models import FORMULA_FIELDS, KOM
from app.gfi_table import CellValue, SourceTable
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reporting-years/{year}", tags=["companies"])

# Statistics above the Home table: totals of these fields and their share of the kom total,
# i.e. of the number of companies (kom = 1 for every company).
STATS_FIELDS = ("preliminarni", "gfi_uradjen", "gfi_za_rad")


class Column(BaseModel):
    key: str  # Excel column letter, e.g. "A"
    header: str | None  # original header text (may be empty or duplicated)


class Cell(BaseModel):
    value: CellValue = None  # effective value: the edit if there is one, else the original value
    format: str | None = None  # Excel number format; omitted for "General"
    formula: bool = False  # formula cell (read-only, shows the stored result)
    editable: bool = False
    text: bool = False  # edited as text (company details); the Home page shows these read-only
    edited: bool = False
    original: CellValue = None  # original (Excel) value, only sent for edited cells


class Row(BaseModel):
    row: int  # Excel row number
    cells: dict[str, Cell]  # column letter -> cell


class ColumnTotal(BaseModel):
    key: str  # column letter
    header: str | None  # original header text
    total: int | float
    share: float | None = None  # total / number of companies (0.085 = 8.5 %); omitted without companies


class TableStats(BaseModel):
    """Statistics shown above the Home table: column totals and their share of the kom total
    (the number of companies, kom being 1 for every company)."""

    base_total: int | float  # kom total = number of companies
    columns: list[ColumnTotal]  # Preliminarni, GFI uradjen, GFI ZA RAD (table order)


class CompanyTable(BaseModel):
    workbook: str
    sheet: str
    columns: list[Column]
    rows: list[Row]
    stats: TableStats | None = None  # omitted when the workbook layout is unknown


class CellUpdate(BaseModel):
    value: float | str | None  # number for numeric cells, text for company details; None clears the cell


class CellUpdateResult(BaseModel):
    row: int
    column: str
    value: float | str | None
    edited: bool
    # Recomputed formula columns of the same row (column letter -> value).
    formulas: dict[str, CellValue] = {}
    # Recomputed table statistics (totals change with every numeric edit).
    stats: TableStats | None = None


def _number(value: CellValue) -> int | float:
    """Formula input: a number, or 0 for an empty (or non-numeric) cell."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def apply_formulas(source: SourceTable, cells: dict[str, Cell]) -> None:
    """Compute the formula columns of one row from its current values (edits included)."""
    col_of = {field: col for col, field in source.fields.items()}

    def operand(name: str | int) -> int | float:
        if isinstance(name, int):
            return name  # a constant (kom = 1)
        col = col_of.get(name)
        return _number(cells[col].value if col in cells else None)

    for field, (minuend, subtrahend) in FORMULA_FIELDS.items():
        col = col_of.get(field)
        if col is None or col not in cells or not all(isinstance(o, int) or o in col_of for o in (minuend, subtrahend)):
            continue
        cell = cells[col]
        cell.value = operand(minuend) - operand(subtrahend)
        cell.formula, cell.editable, cell.text, cell.edited, cell.original = True, False, False, False, None


def build_row(source: SourceTable, edits: Edits, row_number: int) -> Row:
    cells = {}
    for key, src in source.rows[row_number].items():
        kind = edit_kind(source, key, src)
        cell = Cell(
            value=src.value,
            format=None if src.number_format == "General" else src.number_format,
            formula=src.is_formula,
            editable=kind is not None,
            text=kind == "text",
        )
        edit = edits.get((row_number, key))
        if edit is not None and kind is not None:
            value, original_at_edit = edit
            if original_at_edit != src.value:
                logger.warning(
                    "Original value of %s!%s%d changed since it was edited (%r -> %r); keeping the edit",
                    source.workbook, key, row_number, original_at_edit, src.value,
                )
            cell.value, cell.edited, cell.original = value, True, src.value
        cells[key] = cell
    apply_formulas(source, cells)
    return Row(row=row_number, cells=cells)


def _total(rows: list[Row], column: str) -> int | float:
    total = math.fsum(_number(r.cells[column].value) for r in rows if column in r.cells)
    return int(total) if total.is_integer() else total


def build_stats(source: SourceTable, rows: list[Row]) -> TableStats | None:
    """Totals of STATS_FIELDS over all companies (current values, formulas computed; an
    empty cell counts as 0) and each total's share of the kom total (KOM per company)."""
    col_of = {field: col for col, field in source.fields.items()}
    if any(field not in col_of for field in STATS_FIELDS):
        return None
    base_total = KOM * len(rows)
    columns = []
    for field in STATS_FIELDS:
        col = col_of[field]
        total = _total(rows, col)
        share = total / base_total if base_total else None
        columns.append(ColumnTotal(key=col, header=source.headers.get(col), total=total, share=share))
    return TableStats(base_total=base_total, columns=columns)


def build_company_table(source: SourceTable, edits: Edits) -> CompanyTable:
    rows = [build_row(source, edits, row_number) for row_number in source.rows]
    columns = [Column(key=key, header=header) for key, header in source.headers.items()]
    return CompanyTable(
        workbook=source.workbook, sheet=source.sheet, columns=columns, rows=rows, stats=build_stats(source, rows)
    )


# The company type column (user, 2026-11-25): shown on Edit Company Data, read-only, after the
# office column; not a workbook column (key "TIP"), so Home leaves it out.
TYPE_COLUMN = "TIP"
TYPE_LABELS = {"pdp": "PDP", "ppdg": "PPDG-1S"}


def _with_types(table: CompanyTable, year: int) -> CompanyTable:
    with session_scope() as session:
        types = dict(session.execute(
            select(CompanyYearRow.source_row, CompanyYearRow.form_type).where(CompanyYearRow.year == year)
        ).all())
    headers = [(c.header or "").strip().upper() for c in table.columns]
    position = headers.index("REFERENT") + 2 if "REFERENT" in headers else len(table.columns)
    table.columns.insert(position, Column(key=TYPE_COLUMN, header="Tip"))
    for row in table.rows:
        row.cells[TYPE_COLUMN] = Cell(value=TYPE_LABELS.get(types.get(row.row, "pdp"), "PDP"))
    return table


@router.get("/companies", response_model_exclude_defaults=True)
def get_companies(year: int, username: str = Depends(require_user)) -> CompanyTable:
    store = get_gfi_store()
    source, edits = store.load(year)
    table = _with_types(build_company_table(source, edits), year)
    logger.info(
        "Loaded %d company rows for %s from %s (%s, %d edits)",
        len(table.rows), year, source.workbook, store.name, len(edits),
    )
    return table


@router.put("/cells/{column}/{row}")
def update_cell(
    year: int, column: str, row: int, update: CellUpdate, username: str = Depends(require_user)
) -> CellUpdateResult:
    store = get_gfi_store()
    source, _ = store.load(year)
    src = source.rows.get(row, {}).get(column)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Polje {column}{row} ne postoji.")
    kind = edit_kind(source, column, src)
    if kind is None:
        logger.warning("Rejected edit of read-only cell %s!%s%d by '%s'", source.workbook, column, row, username)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Polje {column}{row} je samo za čitanje.")
    value = update.value
    if kind == "number":
        if isinstance(value, str) or (value is not None and not math.isfinite(value)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Vrednost mora biti broj.")
        value = status_value(source.fields.get(column), value)
    else:
        if value is not None and not isinstance(value, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Vrednost mora biti tekst.")
        value = clean_text(source.fields.get(column), value)

    edited = store.save(year, row, column, kind, value, src.value, username)
    logger.info("Cell %s!%s%d %s by '%s'", source.workbook, column, row, "edited" if edited else "reverted", username)
    logger.debug("Cell %s!%s%d new value: %r", source.workbook, column, row, value)
    # Send the recomputed formula columns of this row, so the page can show them at once.
    source, edits = store.load(year)
    table = build_company_table(source, edits)
    cells = next(r.cells for r in table.rows if r.row == row)
    formulas = {key: cell.value for key, cell in cells.items() if cell.formula and key != column}
    return CellUpdateResult(
        row=row, column=column, value=value, edited=edited, formulas=formulas, stats=table.stats
    )


@router.post("/companies")
def add_company_route(year: int, details: NewCompany, username: str = Depends(require_user)) -> AddedCompany:
    """Adds a new company at the end of the year's table (Edit Company Data, user 2026-11-25)."""
    try:
        with session_scope() as session:
            return add_company(session, year, details, username)
    except MigrationError as exc:
        if exc.status_code < 500:
            logger.warning("Adding a company to %s refused: %s", year, exc)
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get("/companies/registry")
def get_year_companies_route(year: int, username: str = Depends(require_user)) -> list[YearCompany]:
    """The year's companies with whether each can be deleted (Edit Company Data, "Obriši firme")."""
    with session_scope() as session:
        return year_companies(session, year)


@router.post("/companies/delete")
def delete_companies_route(year: int, selection: CompanyRows, username: str = Depends(require_user)) -> DeletedCompanies:
    """Deletes the chosen companies from the year permanently, only those without data (user, 2026-11-25)."""
    try:
        with session_scope() as session:
            return delete_companies(session, year, selection.rows, username)
    except MigrationError as exc:
        if exc.status_code < 500:
            logger.warning("Deleting companies from %s refused: %s", year, exc)
        raise HTTPException(exc.status_code, str(exc)) from None
