"""PB-1 (Poreski bilans) template and values from "<year> PB-1.xls".

The PB-1 table is the "Poreski bilans" sheet, from the header row ("red.br.PB 1 | Opis |
Priznati troskovi | Ostvareni troskovi | Prekoracenje | Komentar stopa konto") down to
the last form row, columns A..F. Columns A, B and F (line number, description,
rate/konto comment) form the template shared by every company; columns C, D and E hold
the amounts, which belong to the company named above the table (e.g. "FRIGOLAKTA  DOO,
BEOGRAD"). Helper columns G..Q, the rows above the header and the other sheets are not
part of the PB-1 table.

The .xls file is read with xlrd and never written.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import xlrd

from app.logging_config import get_logger

logger = get_logger(__name__)

PB1_FILE_PATTERN = re.compile(r"^(\d{4}) PB-1\.xls$", re.IGNORECASE)
TEMPLATE_SHEET = "Poreski bilans"
HEADER_MARKER = "red.br"  # column A of the header row starts with this
COLUMN_KEYS = ["A", "B", "C", "D", "E", "F"]
VALUE_COLUMNS = {"C", "D", "E"}  # company amounts; the other columns are template

# Legal-form words ignored when comparing company names.
LEGAL_FORMS = {"DOO", "DOOEL", "AD", "OD", "PR", "SZR", "STR", "KD", "JP"}

CellValue = str | int | float | bool | None


@dataclass(frozen=True)
class Pb1Cell:
    value: CellValue
    number_format: str
    bold: bool


@dataclass(frozen=True)
class Pb1Workbook:
    workbook: str
    sheet: str
    company_name: str | None  # company the amounts belong to, as written in the file
    headers: dict[str, str | None]
    column_widths: dict[str, int]  # in characters, from the sheet
    rows: dict[int, dict[str, Pb1Cell]]  # Excel row number -> column -> cell (with amounts)


def normalize_company_name(name: str) -> str:
    """'FRIGOLAKTA  DOO, BEOGRAD' -> 'FRIGOLAKTA' (no legal form, city, case or diacritics)."""
    name = name.split(",")[0]  # drop the city after the comma
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    name = re.sub(r"\bD\s*\.?\s*O\s*\.?\s*O\b\.?", " DOO ", name)
    tokens = re.sub(r"[^A-Z0-9]+", " ", name).split()
    # The legal form ends the name; anything after it is the seat (e.g. "DOO BEOGRAD-ZEMUN").
    cut = next((i for i, t in enumerate(tokens) if t in LEGAL_FORMS), len(tokens))
    return " ".join(tokens[:cut])


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


def _cell_value(sheet: xlrd.sheet.Sheet, r: int, c: int) -> CellValue:
    ctype, value = sheet.cell_type(r, c), sheet.cell_value(r, c)
    if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    if ctype == xlrd.XL_CELL_NUMBER:
        return int(value) if float(value).is_integer() else value
    if ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    if ctype == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(value, "#ERR")
    return value  # text (dates do not occur in this table)


def read_pb1_workbook(path: Path) -> Pb1Workbook:
    book = xlrd.open_workbook(path, formatting_info=True, on_demand=True)
    try:
        sheet = book.sheet_by_name(TEMPLATE_SHEET)
        ncols = len(COLUMN_KEYS)

        def style(r: int, c: int) -> tuple[str, bool]:
            xf = book.xf_list[sheet.cell_xf_index(r, c)]
            fmt = book.format_map.get(xf.format_key)
            return (fmt.format_str if fmt else "General"), bool(book.font_list[xf.font_index].bold)

        header_index = next(
            (r for r in range(sheet.nrows)
             if str(sheet.cell_value(r, 0)).strip().lower().startswith(HEADER_MARKER)),
            None,
        )
        if header_index is None:
            raise ValueError(f"PB-1 header row not found in sheet {TEMPLATE_SHEET!r}")

        # The company name is the last text in column B above the header ("PB 1 2025" is the title).
        company_name = next(
            (str(sheet.cell_value(r, 1)).strip() for r in range(header_index - 1, -1, -1)
             if isinstance(sheet.cell_value(r, 1), str) and sheet.cell_value(r, 1).strip()
             and not sheet.cell_value(r, 1).strip().upper().startswith("PB")),
            None,
        )

        headers = {
            key: (None if (v := _cell_value(sheet, header_index, i)) is None else str(v))
            for i, key in enumerate(COLUMN_KEYS)
        }
        widths = {
            key: sheet.colinfo_map[i].width // 256 if i in sheet.colinfo_map else 10
            for i, key in enumerate(COLUMN_KEYS)
        }

        # Form rows: everything below the header until the first row that is empty in A..F.
        rows: dict[int, dict[str, Pb1Cell]] = {}
        for r in range(header_index + 1, sheet.nrows):
            values = [_cell_value(sheet, r, c) for c in range(min(ncols, sheet.ncols))]
            if all(v is None for v in values):
                break
            cells = {}
            for i, key in enumerate(COLUMN_KEYS):
                number_format, bold = style(r, i) if i < sheet.ncols else ("General", False)
                cells[key] = Pb1Cell(value=values[i] if i < len(values) else None,
                                     number_format=number_format, bold=bold)
            rows[r + 1] = cells

        return Pb1Workbook(
            workbook=path.name, sheet=sheet.name, company_name=company_name,
            headers=headers, column_widths=widths, rows=rows,
        )
    finally:
        book.release_resources()


_cache: dict[Path, tuple[float, Pb1Workbook]] = {}


def load_pb1_workbook(path: Path) -> Pb1Workbook:
    """read_pb1_workbook with a cache that is invalidated when the file changes."""
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    workbook = read_pb1_workbook(path)
    _cache[path] = (mtime, workbook)
    return workbook
