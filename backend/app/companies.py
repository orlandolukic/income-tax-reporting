"""Company table API: Excel values (columns A..N) with user edits from SQLite applied on top."""

import math

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_user
from app.edits_store import delete_edit, get_edits, save_edit
from app.gfi_workbook import COLUMN_KEYS, CellValue, SourceTable, load_source_table
from app.logging_config import get_logger
from app.reporting_years import get_workbook_path

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reporting-years/{year}", tags=["companies"])


class Column(BaseModel):
    key: str  # Excel column letter, e.g. "A"
    header: str | None  # original header text (may be empty or duplicated)


class Cell(BaseModel):
    value: CellValue = None  # effective value: the edit if there is one, else the Excel value
    format: str | None = None  # Excel number format; omitted for "General"
    formula: bool = False  # formula cell (read-only, shows Excel's cached result)
    editable: bool = False
    edited: bool = False
    original: CellValue = None  # Excel value, only sent for edited cells


class Row(BaseModel):
    row: int  # Excel row number
    cells: dict[str, Cell]  # column letter -> cell


class CompanyTable(BaseModel):
    workbook: str
    sheet: str
    columns: list[Column]
    rows: list[Row]


class CellUpdate(BaseModel):
    value: float | None  # None clears the cell


class CellUpdateResult(BaseModel):
    row: int
    column: str
    value: float | None
    edited: bool


def _load(year: int) -> SourceTable:
    path = get_workbook_path(year)
    try:
        return load_source_table(path)
    except Exception:
        logger.exception("Failed to read GFI workbook %s", path.name)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to read the workbook")


@router.get("/companies", response_model_exclude_defaults=True)
def get_companies(year: int, username: str = Depends(require_user)) -> CompanyTable:
    source = _load(year)
    edits = get_edits(source.workbook, source.sheet)

    rows = []
    for row_number, source_cells in source.rows.items():
        cells = {}
        for key, src in source_cells.items():
            cell = Cell(
                value=src.value,
                format=None if src.number_format == "General" else src.number_format,
                formula=src.is_formula,
                editable=src.is_editable,
            )
            edit = edits.get((row_number, key))
            if edit is not None and src.is_editable:
                value, original_at_edit = edit
                if original_at_edit != src.value:
                    logger.warning(
                        "Excel value of %s!%s%d changed since it was edited (%r -> %r); keeping the edit",
                        source.workbook, key, row_number, original_at_edit, src.value,
                    )
                cell.value, cell.edited, cell.original = value, True, src.value
            cells[key] = cell
        rows.append(Row(row=row_number, cells=cells))

    columns = [Column(key=key, header=source.headers[key]) for key in COLUMN_KEYS]
    logger.info(
        "Loaded %d company rows for %s from %s (%d edits)", len(rows), year, source.workbook, len(edits)
    )
    return CompanyTable(workbook=source.workbook, sheet=source.sheet, columns=columns, rows=rows)


@router.put("/cells/{column}/{row}")
def update_cell(
    year: int, column: str, row: int, update: CellUpdate, username: str = Depends(require_user)
) -> CellUpdateResult:
    source = _load(year)
    src = source.rows.get(row, {}).get(column)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cell {column}{row} not found")
    if not src.is_editable:
        logger.warning("Rejected edit of read-only cell %s!%s%d by '%s'", source.workbook, column, row, username)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cell {column}{row} is read-only")
    if update.value is not None and not math.isfinite(update.value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Value must be a finite number")

    if update.value is not None and update.value == src.value:
        # Back to the Excel value: drop the override instead of storing a copy.
        delete_edit(source.workbook, source.sheet, row, column)
        edited = False
    else:
        save_edit(source.workbook, source.sheet, row, column, update.value, src.value, username)
        edited = True
    logger.info("Cell %s!%s%d %s by '%s'", source.workbook, column, row, "edited" if edited else "reverted", username)
    logger.debug("Cell %s!%s%d new value: %r", source.workbook, column, row, update.value)
    return CellUpdateResult(row=row, column=column, value=update.value, edited=edited)
