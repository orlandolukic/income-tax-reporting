"""Reading a PB-1 workbook ("<year> PB-1.xls") with xlrd. Used only by the one-time import
(app.pb1_import); the app itself never opens the file (the form is in PostgreSQL).
The file is never written.
"""

import re
from pathlib import Path

import xlrd

from app.logging_config import get_logger
from app.pb1_workbook import EMPTY_CELL, Pb1Workbook, RawCell, SheetCells, build_pb1_workbook, match_tab_sheets

logger = get_logger(__name__)

PB1_FILE_PATTERN = re.compile(r"^(\d{4}) PB-1\.xls$", re.IGNORECASE)


def find_pb1_workbook(data_dir: Path, year: int) -> Path | None:
    if not data_dir.is_dir():
        return None
    matches = sorted(
        p for p in data_dir.iterdir()
        if not p.name.startswith("~$") and (m := PB1_FILE_PATTERN.match(p.name)) and int(m.group(1)) == year
    )
    if len(matches) > 1:
        logger.warning("Multiple PB-1 workbooks for %s, using %s", year, matches[0].name)
    return matches[0] if matches else None


def sheet_cells_from_xlrd(book: xlrd.book.Book, sheet: xlrd.sheet.Sheet) -> SheetCells:
    """Every cell of an xlrd sheet with a value or a non-default format."""
    cells: dict[tuple[int, int], RawCell] = {}
    for r in range(sheet.nrows):
        for c in range(sheet.ncols):
            ctype, value = sheet.cell_type(r, c), sheet.cell_value(r, c)
            if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                kind, value = "empty", None
            elif ctype == xlrd.XL_CELL_NUMBER:
                kind, value = "number", int(value) if float(value).is_integer() else value
            elif ctype == xlrd.XL_CELL_BOOLEAN:
                kind, value = "bool", bool(value)
            elif ctype == xlrd.XL_CELL_ERROR:
                kind, value = "error", xlrd.error_text_from_code.get(value, "#ERR")
            else:
                kind = "text"  # dates do not occur in these sheets
            xf = book.xf_list[sheet.cell_xf_index(r, c)]
            fmt = book.format_map.get(xf.format_key)
            background = xf.background
            rgb = book.colour_map.get(background.pattern_colour_index) if background.fill_pattern == 1 else None
            cell = RawCell(
                kind=kind,
                value=value,
                number_format=fmt.format_str if fmt else "General",
                bold=bool(book.font_list[xf.font_index].bold),
                fill=None if rgb is None or rgb == (255, 255, 255) else "#{:02x}{:02x}{:02x}".format(*rgb),
            )
            if cell != EMPTY_CELL:
                cells[(r, c)] = cell
    widths = {c: info.width for c, info in sheet.colinfo_map.items()}
    return SheetCells(name=sheet.name, nrows=sheet.nrows, ncols=sheet.ncols, cells=cells, widths=widths)


def read_pb1_sheets(path: Path) -> list[SheetCells]:
    """Every sheet of a PB-1 workbook with its cells (the file is only read)."""
    book = xlrd.open_workbook(path, formatting_info=True, on_demand=True)
    try:
        return [sheet_cells_from_xlrd(book, book.sheet_by_name(name)) for name in book.sheet_names()]
    finally:
        book.release_resources()


def read_pb1_workbook(path: Path) -> Pb1Workbook:
    """The PB-1 form from a "<year> PB-1.xls" file (the PB-1 import only)."""
    return build_pb1_workbook(path.name, match_tab_sheets(path.name, read_pb1_sheets(path)))
