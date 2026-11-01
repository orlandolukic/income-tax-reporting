"""Reading the company table from a GFI workbook.

The table is on the first sheet: row 1 holds the headers, the following rows hold one
company each. Only columns A..N are used. Headers and values are returned exactly as
stored (formula cells give their last calculated value, as Excel displays them).

The workbook is never written. User edits live in SQLite (app.edits_store) and are
applied on top of the Excel values by the API.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

FIRST_COLUMN = 1  # A
LAST_COLUMN = 14  # N
COLUMN_KEYS = [get_column_letter(i) for i in range(FIRST_COLUMN, LAST_COLUMN + 1)]

CellValue = str | int | float | bool | None


@dataclass(frozen=True)
class SourceCell:
    value: CellValue  # stored value (cached result for formulas)
    number_format: str  # Excel number format, e.g. "#,##0_);[Red](#,##0)"
    is_formula: bool

    @property
    def is_editable(self) -> bool:
        """Only plain numeric cells can be edited; formulas, text and empty cells cannot."""
        return (
            not self.is_formula
            and isinstance(self.value, (int, float))
            and not isinstance(self.value, bool)
        )


@dataclass(frozen=True)
class SourceTable:
    workbook: str
    sheet: str
    headers: dict[str, str | None]  # column letter -> original header
    rows: dict[int, dict[str, SourceCell]]  # Excel row number -> column letter -> cell


def _to_json_value(value: object) -> CellValue:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def read_source_table(path: Path) -> SourceTable:
    # Two passes: data_only=True gives cached formula results (what Excel displays),
    # data_only=False tells which cells hold formulas.
    values_wb = load_workbook(path, read_only=True, data_only=True)
    formulas_wb = load_workbook(path, read_only=True, data_only=False)
    try:
        values_ws = values_wb.worksheets[0]
        formulas_ws = formulas_wb.worksheets[0]
        bounds = dict(min_col=FIRST_COLUMN, max_col=LAST_COLUMN)
        value_rows = values_ws.iter_rows(**bounds)
        formula_rows = formulas_ws.iter_rows(**bounds)

        header_cells = next(value_rows, ())
        next(formula_rows, None)
        header_values = [c.value for c in header_cells] + [None] * (len(COLUMN_KEYS) - len(header_cells))
        headers = {key: None if h is None else str(h) for key, h in zip(COLUMN_KEYS, header_values)}

        rows: dict[int, dict[str, SourceCell]] = {}
        for row_number, (value_cells, formula_cells) in enumerate(zip(value_rows, formula_rows), start=2):
            # Skip rows that are completely empty in A..N.
            if all(c.value is None for c in value_cells):
                continue
            cells = {}
            for key, value_cell, formula_cell in zip(COLUMN_KEYS, value_cells, formula_cells):
                cells[key] = SourceCell(
                    value=_to_json_value(value_cell.value),
                    number_format=getattr(value_cell, "number_format", None) or "General",
                    is_formula=getattr(formula_cell, "data_type", None) == "f",
                )
            rows[row_number] = cells

        return SourceTable(workbook=path.name, sheet=values_ws.title, headers=headers, rows=rows)
    finally:
        values_wb.close()
        formulas_wb.close()


_cache: dict[Path, tuple[float, SourceTable]] = {}


def load_source_table(path: Path) -> SourceTable:
    """read_source_table with a cache that is invalidated when the file changes."""
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    table = read_source_table(path)
    _cache[path] = (mtime, table)
    return table
