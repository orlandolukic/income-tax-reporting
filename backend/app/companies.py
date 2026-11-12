"""Company table API: GFI values (columns A..N) with user edits applied on top.

The data comes from PostgreSQL when DATABASE_URL is set, otherwise from the Excel
workbook with edits in SQLite (see app.gfi_store).
"""

import math

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_user
from app.gfi_store import Edits, clean_text, edit_kind, get_gfi_store
from app.models import FORMULA_FIELDS
from app.gfi_workbook import CellValue, SourceTable
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reporting-years/{year}", tags=["companies"])

# Statistics under the Home table: totals of these fields and their share of the kom total.
STATS_FIELDS = ("preliminarni", "gfi_uradjen", "gfi_za_rad")
STATS_BASE_FIELD = "kom"


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
    share: float | None = None  # total / kom total (0.085 = 8.5 %); omitted when the kom total is 0


class TableStats(BaseModel):
    """Statistics shown under the Home table: column totals and their share of the kom total."""

    base_key: str  # kom column letter
    base_header: str | None
    base_total: int | float
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
    for field, (minuend, subtrahend) in FORMULA_FIELDS.items():
        col, a, b = col_of.get(field), col_of.get(minuend), col_of.get(subtrahend)
        if not (col and a and b) or col not in cells:
            continue
        cell = cells[col]
        cell.value = _number(cells[a].value if a in cells else None) - _number(cells[b].value if b in cells else None)
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
    empty cell counts as 0) and each total's share of the kom total."""
    col_of = {field: col for col, field in source.fields.items()}
    base_col = col_of.get(STATS_BASE_FIELD)
    if base_col is None or any(field not in col_of for field in STATS_FIELDS):
        return None
    base_total = _total(rows, base_col)
    columns = []
    for field in STATS_FIELDS:
        col = col_of[field]
        total = _total(rows, col)
        share = total / base_total if base_total else None
        columns.append(ColumnTotal(key=col, header=source.headers.get(col), total=total, share=share))
    return TableStats(
        base_key=base_col, base_header=source.headers.get(base_col), base_total=base_total, columns=columns
    )


def build_company_table(source: SourceTable, edits: Edits) -> CompanyTable:
    rows = [build_row(source, edits, row_number) for row_number in source.rows]
    columns = [Column(key=key, header=header) for key, header in source.headers.items()]
    return CompanyTable(
        workbook=source.workbook, sheet=source.sheet, columns=columns, rows=rows, stats=build_stats(source, rows)
    )


@router.get("/companies", response_model_exclude_defaults=True)
def get_companies(year: int, username: str = Depends(require_user)) -> CompanyTable:
    store = get_gfi_store()
    source, edits = store.load(year)
    table = build_company_table(source, edits)
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cell {column}{row} not found")
    kind = edit_kind(source, column, src)
    if kind is None:
        logger.warning("Rejected edit of read-only cell %s!%s%d by '%s'", source.workbook, column, row, username)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cell {column}{row} is read-only")
    value = update.value
    if kind == "number":
        if isinstance(value, str) or (value is not None and not math.isfinite(value)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Value must be a finite number")
    else:
        if value is not None and not isinstance(value, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Value must be text")
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
