"""Reading the company table from a GFI workbook.

The table is on the first sheet: row 1 holds the headers, the following rows hold one
company each. Only columns A..N are used. Headers and values are returned exactly as
stored (formula cells give their last calculated value, as Excel displays them).

The workbook is never written. User edits live in SQLite (app.edits_store) and are
applied on top of the Excel values by the API.
"""

import datetime
from dataclasses import dataclass, field
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
    locked: bool = False  # not editable as a number regardless of content (e.g. company details in the database)

    @property
    def is_editable(self) -> bool:
        """Only plain numeric cells can be edited; formulas, text and empty cells cannot."""
        return (
            not self.locked
            and not self.is_formula
            and isinstance(self.value, (int, float))
            and not isinstance(self.value, bool)
        )


@dataclass(frozen=True)
class SourceTable:
    workbook: str
    sheet: str
    headers: dict[str, str | None]  # column letter -> original header
    rows: dict[int, dict[str, SourceCell]]  # Excel row number -> column letter -> cell
    # Column letter -> GFI field (name, pib, kom, ...), found by header; set by app.gfi_store.
    fields: dict[str, str] = field(default_factory=dict)


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


RB_HEADER = "R.B."


def _is_rb(header: str | None) -> bool:
    return header is not None and header.strip().upper() == RB_HEADER


def main_list_rows(table: SourceTable) -> list[int]:
    """Excel rows of the company list: from the top while R.B. (first "R.B." column)
    continues the sequence 1, 2, 3, ... (2025: 165 companies, ending with DAGOTTA).
    Empty if there is no such sequence."""
    rb_col = next((k for k, h in table.headers.items() if _is_rb(h)), None)
    rows: list[int] = []
    if rb_col is None:
        return rows
    for row_number, cells in table.rows.items():
        value = cells[rb_col].value
        if isinstance(value, bool) or value != len(rows) + 1:
            break
        rows.append(row_number)
    return rows


def company_list(table: SourceTable) -> SourceTable:
    """The company list as the app uses it: only the main_list_rows (all rows if the
    workbook has no R.B. sequence), without the R.B. columns. R.B. is used only here, to
    find the list; it is not shown, returned by the API or stored. The app numbers the
    companies itself ("#" = position in the list)."""
    rows = main_list_rows(table) or list(table.rows)
    keep = [key for key, header in table.headers.items() if not _is_rb(header)]
    return SourceTable(
        workbook=table.workbook,
        sheet=table.sheet,
        headers={key: table.headers[key] for key in keep},
        rows={row: {key: table.rows[row][key] for key in keep} for row in rows},
        fields=table.fields,
    )


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
