"""PB-1 form from "<year> PB-1.xls": three tabs, like the three sheets of the workbook.

Every company has one PB-1 form with three tabs (PB1_TABS):
- "Poreski bilans": from the header row ("red.br.PB 1 | Opis | Priznati troskovi |
  Ostvareni troskovi | Prekoracenje | Komentar stopa konto") down to the last form row,
  columns A..F, plus G (konto numbers, shown as "Konto"). Amounts: C, D, E.
- "Uporedo <year> i <year-1>": from the header row ("R.b. | Opis | <year> | <year-1> |
  Index") down, columns A..E. Amounts: C, D, E.
- "Preliminarni rezultat": two tables side by side (A..C: R.b., Opis, RSD; E..G: increase /
  decrease of the tax base and tax reliefs) and the sections below them, rows 2..42,
  columns A..G. Amounts: C and G.
The other columns are the template shared by every company. Helper columns (H..Q in
Poreski bilans, H..J in Preliminarni rezultat), the title rows and company names above the
tables are not part of the form. The amounts belong to one company only (see app.pb1).

The form is built from SheetCells: the sheets as stored in PostgreSQL (app.pb1_store), or, only
in the one-time import, as read from the .xls file (app.pb1_file). No Excel library here.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace


from app.logging_config import get_logger
from app.pb1_formulas import SECTION_SUBTOTALS
from app.pb1_official import OFFICIAL_LINES
from app.pb1_texts import correct_text

logger = get_logger(__name__)

# Legal-form words ignored when comparing company names.
LEGAL_FORMS = {"DOO", "DOOEL", "AD", "OD", "PR", "SZR", "STR", "KD", "JP"}

CellValue = str | int | float | bool | None


@dataclass(frozen=True)
class AmountFix:
    """Corrects the amount fields of one form row where the hand-made Excel form is
    inconsistent: a form line without an amount cell, or a spacer row with stray ones."""

    row: int  # Excel row (1-based)
    label: str  # the row's description (column B) starts with this; "" = the row has no description
    columns: str  # the row's amount columns after the fix ("" = none: a spacer row)


@dataclass(frozen=True)
class Pb1TabSpec:
    key: str  # used in URLs
    sheet_prefix: str  # the Excel sheet's name starts with this (e.g. "Uporedo 2025 i 2024")
    columns: tuple[str, ...]
    value_columns: frozenset[str]  # company amounts; the other columns are template
    wrap_columns: frozenset[str]  # long descriptions that wrap
    header_marker: str | None  # column A of the header row starts with this (lower case)
    first_row: int | None = None  # without a header row: first Excel row (1-based)
    max_empty_rows: int = 0  # empty rows allowed inside the form (0: it ends at the first one)
    # Applied on top of the amount fields found in the file; skipped (WARNING) when the
    # row's description no longer matches, e.g. after the template was changed.
    amount_fixes: tuple[AmountFix, ...] = ()
    # Line-number columns ("R.b.", "red.br.PB 1"): header "#", as narrow as their numbers.
    # A longer text in them (a section heading) overflows into the empty cells to its right.
    narrow_columns: frozenset[str] = frozenset()
    # Header texts replacing the sheet's (column -> header), e.g. a column without one.
    header_overrides: tuple[tuple[str, str], ...] = ()
    # Konto numbers: shown as written (no number format); a 0 is not a konto and is left out.
    konto_columns: frozenset[str] = frozenset()
    # The form's closing rows, shown as a separate summary table below it: from the row whose
    # description (original text) starts with this, to the end. None: no summary table.
    summary_label: str | None = None
    # Read-only in the app (with the line-number columns): descriptions ("Opis") and, per tab,
    # other template texts. Every other field can be edited: amounts per company, template
    # fields (also empty ones) for every company.
    readonly_columns: frozenset[str] = frozenset("B")
    # Read-only block at the top of a sheet without a header row: (last Excel row, columns),
    # e.g. the title and the "R.b. | Opis | RSD" row of Preliminarni rezultat.
    readonly_top: tuple[int, str] | None = None
    # The sheet's first rows above the header (title, company name, class 5/6 totals), shown
    # as a separate table above the form, in the form's columns. Every number in them is the
    # company's amount; their texts are read-only.
    head_rows: int = 0
    # Head cell with the company name written in the file; shown as the company's name.
    company_name_cell: tuple[int, str] | None = None
    # Head cell with the company's number of months in business (Mesecna akontacija = porez /
    # months). Each company has its own, the file's value (12) being every company's default.
    months_cell: tuple[int, str] | None = None
    # Label written in the empty cell left of months_cell (the sheet has none there).
    months_label: str | None = None
    # The comment column ("Komentar, stopa, konto"): not shown in the table but as a list of
    # description-comment pairs beside it; one comment per row and company, with defaults
    # (settings) taken from the workbook. Its head-row cells are not comments.
    comment_column: str | None = None
    # Columns of the head table, aligned one to one with the table's columns (the comment
    # column's head cells take the place of the column after it). None: the table's columns.
    head_columns: tuple[str, ...] | None = None
    # Head-row columns left out of the form (their cells are empty): the head table then ends
    # with the last column that has content (user's decision).
    head_dropped_columns: frozenset[str] = frozenset()
    # Columns of the closing rows (summary) that are not part of the form: not shown, not
    # stored (user, 2026-11-16: the box shows only description and amount).
    summary_dropped_columns: frozenset[str] = frozenset()
    # Section rows (bold description, e.g. "A. ...", "II ...", "B. ..."): only their line number
    # and description; their other cells are not part of the form (user, 2026-11-16: read-only
    # and empty). `section_hidden` lists cells that stay in the data (inputs of formulas, stored)
    # but are not shown in their row (Pb1Cell.hidden).
    section_rows_empty: bool = False
    section_hidden: frozenset[tuple[int, str]] = frozenset()
    # Section cells that stay and are shown, as (row, column): e.g. a computed subtotal.
    section_shown: frozenset[tuple[int, str]] = frozenset()
    # An extra head row below the last one (label, the address whose value it shows, the label's
    # column, the value's column, the value's fill); the label with the fill of the label row
    # above; read-only.
    head_result: tuple[str, str, str, str, str] | None = None
    # Every value-column cell of the form lines (not section / closing rows) is an amount field
    # of the company: numbers only, shown with two decimals, 0,00 when empty (user, 2026-11-16).
    form_values_are_amounts: bool = False
    # Numbers are never bold (only texts keep the sheet's bold), user 2026-11-16.
    plain_numbers: bool = False
    # Single cells shown without the sheet's bold, as (row, column).
    plain_cells: frozenset[tuple[int, str]] = frozenset()
    # Single cells that are not part of the form (not shown, not stored), as (row, column).
    dropped_cells: frozenset[tuple[int, str]] = frozenset()
    # Whole rows that are not part of the form (not shown, not stored), as (row, start of the
    # original description); skipped (WARNING) when the description doesn't match.
    dropped_rows: tuple[tuple[int, str], ...] = ()
    # Column whose positive values are shown red (Poreski bilans: Prekoracenje, an overrun).
    overrun_column: str | None = None
    # Single read-only cells, as (row, column): e.g. value cells of a section heading row.
    readonly_cells: frozenset[tuple[int, str]] = frozenset()
    # Text colour of single cells, as ((row, column), tone): "expense" red, "income" green.
    cell_tones: tuple[tuple[tuple[int, str], str], ...] = ()


PB1_TABS: tuple[Pb1TabSpec, ...] = (
    Pb1TabSpec(
        key="poreski-bilans", sheet_prefix="Poreski bilans", columns=("A", "B", "C", "D", "E", "F", "G"),
        value_columns=frozenset("CDE"), wrap_columns=frozenset("BFG"), header_marker="red.br",
        narrow_columns=frozenset("A"), konto_columns=frozenset("G"),
        # C / D hold amounts of every kind, not only expenses (user, 2026-11-22: "iznosi").
        header_overrides=(("C", "Priznati iznosi"), ("D", "Ostvareni iznosi"), ("G", "Konto")),
        # "V. Poreska osnovica", line 69, Porez 15%, Mesecna akontacija: the total of the form.
        summary_label="B Poreska osnovica",
        # Rows 1-3: "PB 1 <year>", company name with "Klasa 5 | Klasa 6", and the class totals.
        head_rows=3, company_name_cell=(2, "B"),
        months_cell=(1, "D"),  # 12: months in business (Mesecna akontacija = porez / months)
        months_label="Meseci poslovanja",
        comment_column="F", head_columns=("A", "B", "C", "D", "E", "F"),
        # E and F of rows 1-3 are not part of the form (user, 2026-11-15): E1 and its double F1
        # were used by nothing; E3 / F3 were where Klasa 5 / Klasa 6 were typed in. Klasa 5 / 6
        # (C3 / D3) are now amounts entered directly, per company. The head ends with Klasa 6.
        head_dropped_columns=frozenset("EF"),
        summary_dropped_columns=frozenset("ADEG"),
        section_rows_empty=True,
        form_values_are_amounts=True,
        plain_numbers=True,
        overrun_column="E",  # Prekoracenje = Ostvareni - Priznati; an overrun (> 0) is red
        # "V. Poreska osnovica" (row 85) is the heading of the closing rows, without a value
        # (user, 2026-11-17; it was an amount field). The Prekoracenje of lines 57, 59, 62
        # (rows 70, 74, 77; dropped 2026-11-17) is back (user, 2026-11-25): 57 computed, part of
        # the tax base; 59 and 62 a fixed 0,00 (ZERO_OVERRUN_ROWS), for a consistent look.
        dropped_cells=frozenset({(85, "C")}),
        # The workbook's line 32 "Iskoriscena dugorocna rezervisanja koja nisu bila priznata ..."
        # is not a line of the current official form (user, 2026-11-22: removed; 33 follows 32).
        dropped_rows=((41, "Iskoriscena dugorocna rezervisanja koja nisu bila priznata"),),
        # C5 (A. Poslovna dobit i gubitak: the loss Klasa 6 - Klasa 5 when negative, an input of
        # Oporeziva dobit C74) is not shown in its row; it is shown as a fourth head row, under
        # Klasa 5 / Klasa 6 (user, 2026-11-16).
        section_hidden=frozenset({(5, "C")}),
        # The Prekoracenje subtotal of the Roman-numeral sections (user, 2026-11-25; computed,
        # SECTION_SUBTOTALS in app/pb1_formulas.py).
        section_shown=frozenset((r, "E") for r in SECTION_SUBTOTALS),
        head_result=None,  # Saldo (Klasa 6 - 5) dropped (user, 2026-11-25): it is the Knjigovodstveni rezultat tile
        # Klasa 5 (expenses) red, Klasa 6 (revenue) green, without a sign (user, 2026-11-25).
        cell_tones=(((3, "C"), "expense"), ((3, "D"), "income")),
        # Form lines without an amount cell get the column their section uses:
        # I and V..B. Kapitalni dobici -> C (Priznati troskovi), III -> D (Ostvareni troskovi).
        amount_fixes=(
            AmountFix(8, "Prihod nerezidentnog lica", "C"),  # line 2
            AmountFix(13, "III Uskladjivanje rashoda", ""),  # section heading: no amount (like II, IV..IX)
            AmountFix(39, "Rashod banke", "D"),  # line 31 (the first of the two "31")
            AmountFix(43, "Rashodi po osnovu obezvredjenja imovine", "D"),  # line 34
            AmountFix(62, "Obracunati troskovi po osnovu transfernih cena", "C"),  # line 51
            AmountFix(63, "Obracunati troskovi po osnovu transfernih cena", "C"),  # line 52
            AmountFix(64, "Obracunati prihodi po osnovu transfernih cena", "C"),  # line 53
            AmountFix(65, "Obracunati prihodi po osnovu transfernih cena", "C"),  # line 54
            AmountFix(68, "Obracunati prihodi po osnovu kamata", "C"),  # line 56
            AmountFix(72, "Kamata I pripadajuci", "C"),  # line 58
            AmountFix(79, "Ukupni kaptalni dobici", "C"),  # line 63
            AmountFix(81, "Kaptalni dobici", "C"),  # line 65
            AmountFix(82, "Kaptalni gubici", "C"),  # line 66
            AmountFix(83, "Preneti kapitalni gubici", "C"),  # line 67
            AmountFix(84, "Ostatak kapitalnog dobitka", "C"),  # line 68
        ),
    ),
    Pb1TabSpec(
        key="uporedo", sheet_prefix="Uporedo", columns=("A", "B", "C", "D", "E"),
        value_columns=frozenset("CDE"), wrap_columns=frozenset("B"), header_marker="r.b.",
        narrow_columns=frozenset("A"),
        # #, Opis and Index are read-only (user, 2026-11-17: the Index is computed).
        readonly_columns=frozenset("BE"),
        # <year> and <year-1>: every field of a line is a company amount (user, 2026-11-17).
        form_values_are_amounts=True,
        # Every line has <year>, <year-1> and Index; the two unlabelled spacer rows have none.
        amount_fixes=(
            AmountFix(11, "Poreski gubitak", "CDE"),
            AmountFix(19, "", ""),  # spacer after line 14
            AmountFix(21, "Odlozena poreska sredstva", "CDE"),  # line 16
            AmountFix(22, "Odlozene poreske obaveze", "CDE"),  # line 17
            AmountFix(24, "", ""),  # spacer after line 18
        ),
    ),
    Pb1TabSpec(
        key="preliminarni", sheet_prefix="Preliminarni rezultat", columns=("A", "B", "C", "D", "E", "F", "G"),
        value_columns=frozenset("CG"), wrap_columns=frozenset("BF"), header_marker=None,
        first_row=2, max_empty_rows=5, narrow_columns=frozenset("AE"),
        # Opis, and the right table's texts ("Uvecanje poreske osnovice po Poreskom bilansu", ...);
        # everything above Opis (the title) and its "R.b. | Opis | RSD" row.
        # D: the empty spacer column between the two tables, not shown (user, 2026-11-17: only
        # the numbers can change).
        readonly_columns=frozenset("BDF"), readonly_top=(4, "ABC"),
        # The value cells of the section headings (Uvecanje / Umanjenje poreske osnovice po
        # Poreskom bilansu, Poreske olaksice; Podbilansi bilansa uspeha, Troskovi koji se ne
        # priznaju ...): read-only like the headings (user, 2026-11-17).
        readonly_cells=frozenset({(2, "G"), (12, "G"), (19, "G"), (34, "C"), (41, "C")}),
        # The value right of "Prekoracenje reprezentacije" (=Poreski bilans E33): not bold (user).
        plain_cells=frozenset({(3, "G")}),
        # Left table (A..C) like Uporedo: every line has RSD, the unlabelled spacer rows none.
        # The right table (E..G) keeps its amounts.
        amount_fixes=(
            AmountFix(12, "Poreski gubitak", "C"),  # right side: section heading, no amount
            AmountFix(20, "", "G"),  # left spacer after line 14
            AmountFix(25, "", "G"),  # left spacer after line 18
            AmountFix(28, "", ""),  # spacer below both tables
        ),
    ),
)
DEFAULT_TAB = PB1_TABS[0].key


@dataclass(frozen=True)
class Pb1Cell:
    value: CellValue
    number_format: str
    bold: bool
    # Amount field of the form: an amount column cell that holds a number, an Excel error
    # or only spaces in the file (not template text, not an empty cell outside the form).
    # The same for every company; shown as 0 when it has no number.
    amount: bool = False
    # Fill color of the cell in the sheet ("#rrggbb"), read for the head rows only.
    fill: str | None = None
    # Not part of the form (Pb1Sheet.dropped): always empty and read-only, not stored.
    dropped: bool = False
    # Kept in the data (stored, an input of formulas) but not shown in its row: empty, read-only.
    hidden: bool = False


@dataclass(frozen=True)
class Pb1Sheet:
    spec: Pb1TabSpec
    name: str  # Excel sheet name, shown as the tab title
    headers: dict[str, str | None]  # empty when the sheet has no header row
    column_widths: dict[str, int]  # in characters: from the sheet; narrow columns fit their numbers
    rows: dict[int, dict[str, Pb1Cell]]  # Excel row number -> column -> cell (with amounts)
    summary_start: int | None = None  # first Excel row of the summary table (rows from it on)
    head_end: int = 0  # last Excel row of the head table above the form (0: none)
    # Cells of the form's columns that are not part of the form (section rows, the closing rows'
    # hidden columns): left out of `rows` and of the stored snapshot. (Excel row, column).
    dropped: frozenset[tuple[int, str]] = frozenset()


@dataclass(frozen=True)
class Pb1Workbook:
    workbook: str
    company_name: str | None  # company the amounts belong to, as written in the file
    sheets: dict[str, Pb1Sheet]  # tab key -> sheet (tabs whose sheet is missing are left out)
    # Every non-empty cell of each tab's sheet as stored in the file ("C7" -> value; formula
    # cells hold Excel's last result), also the helper columns: inputs of the PB-1 formulas
    # (app.pb1_formulas) and the values they are checked against.
    raw: dict[str, dict[str, CellValue]] = field(default_factory=dict)
    # Which form: "pdp" (the workbook's) or "ppdg" (PPDG-1S, app/pb1_ppdg.py).
    variant: str = "pdp"


def normalize_company_name(name: str) -> str:
    """'FRIGOLAKTA  DOO, BEOGRAD' -> 'FRIGOLAKTA' (no legal form, city, case or diacritics)."""
    name = name.split(",")[0]  # drop the city after the comma
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    name = re.sub(r"\bD\s*\.?\s*O\s*\.?\s*O\b\.?", " DOO ", name)
    tokens = re.sub(r"[^A-Z0-9]+", " ", name).split()
    # The legal form ends the name; anything after it is the seat (e.g. "DOO BEOGRAD-ZEMUN").
    cut = next((i for i, t in enumerate(tokens) if t in LEGAL_FORMS), len(tokens))
    return " ".join(tokens[:cut])


@dataclass(frozen=True)
class RawCell:
    """One cell of a PB-1 sheet as stored in the file (and in the database snapshot)."""

    kind: str  # "empty" (formatting only), "text", "number", "bool" or "error"
    value: CellValue  # None for "empty"; an error as its text ("#DIV/0!")
    number_format: str = "General"
    bold: bool = False
    fill: str | None = None  # solid fill color ("#rrggbb"); None without a fill or for white


EMPTY_CELL = RawCell("empty", None)
CELL_KINDS = ("empty", "text", "number", "bool", "error")


@dataclass(frozen=True)
class SheetCells:
    """A PB-1 sheet independent of where it was read from: the .xls file (xlrd) or the
    PostgreSQL snapshot (app.pb1_store). Cells that are empty and unformatted are left out."""

    name: str
    nrows: int
    ncols: int
    cells: dict[tuple[int, int], RawCell]  # (0-based row, 0-based column) -> cell
    widths: dict[int, int]  # column index -> width from the sheet (1/256 of a character)

    def cell(self, r: int, c: int) -> RawCell:
        return self.cells.get((r, c), EMPTY_CELL)


def _cell_value(sheet: SheetCells, r: int, c: int) -> CellValue:
    if c >= sheet.ncols:
        return None
    return sheet.cell(r, c).value


def _is_amount_field(sheet: SheetCells, r: int, c: int) -> bool:
    """A number, an Excel error (e.g. #DIV/0!) or a blank text (" ") in the file."""
    if c >= sheet.ncols:
        return False
    cell = sheet.cell(r, c)
    if cell.kind in ("number", "error"):
        return True
    return cell.kind == "text" and not str(cell.value).strip()


def _text(sheet: SheetCells, r: int, c: int) -> str:
    """The cell's text like xlrd's cell_value: "" for an empty cell, "1.0" for a number."""
    cell = sheet.cell(r, c) if c < sheet.ncols else EMPTY_CELL
    if cell.kind == "text":
        return str(cell.value)
    if cell.kind == "number":
        return str(float(cell.value))
    return ""


def _label_key(text: CellValue) -> str:
    return " ".join(str(text or "").split()).casefold()


def _apply_amount_fixes(sheet_name: str, spec: Pb1TabSpec, rows: dict[int, dict[str, Pb1Cell]]) -> None:
    """Sets the amount fields of the rows listed in spec.amount_fixes (see AmountFix)."""
    for fix in spec.amount_fixes:
        cells = rows.get(fix.row)
        label = _label_key(cells["B"].value) if cells else None
        matches = label is not None and (label.startswith(_label_key(fix.label)) if fix.label else label == "")
        if not matches:
            logger.warning(
                "PB-1 sheet %r row %d: description %r doesn't match %r; amount fix skipped",
                sheet_name, fix.row, label, fix.label,
            )
            continue
        for key in spec.value_columns:
            cell = cells[key]
            amount = key in fix.columns
            if amount and isinstance(cell.value, str) and cell.value.strip() and not cell.amount:
                logger.warning("PB-1 sheet %r cell %s%d holds text %r; not an amount field", sheet_name, key, fix.row, cell.value)
                continue
            if amount and not cell.amount:
                rows[fix.row][key] = replace(cell, amount=True)
            elif not amount and cell.amount:
                # Not part of the form: its value (a stray 0, " ") is not shown either.
                rows[fix.row][key] = replace(cell, amount=False, value=None)


# "R.b.", "red.br.PB 1": the line-number label, shown as "#".
LINE_NUMBER_LABEL = re.compile(r"^(r\.?\s*b\.?|red\.?\s*br\.?.*)$", re.IGNORECASE)


def _short_text(value: CellValue) -> str | None:
    """Display text of a line number (1, "12", "#"), None for longer texts."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).strip() if value is not None else ""
    return text if text and len(text) <= 4 else None


def _find_summary_start(sheet_name: str, spec: Pb1TabSpec, rows: dict[int, dict[str, Pb1Cell]]) -> int | None:
    """First row of the summary table: the row whose description starts with spec.summary_label."""
    if spec.summary_label is None:
        return None
    target = _label_key(spec.summary_label)
    start = next((r for r, cells in rows.items() if _label_key(cells["B"].value).startswith(target)), None)
    if start is None:
        logger.warning("PB-1 sheet %r: summary row %r not found; no summary table", sheet_name, spec.summary_label)
    return start


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def _raw_values(sheet: SheetCells) -> dict[str, CellValue]:
    """Every non-empty cell of the sheet as stored in the file, keyed by its address ("C7")."""
    values: dict[str, CellValue] = {}
    for r in range(sheet.nrows):
        for c in range(sheet.ncols):
            value = _cell_value(sheet, r, c)
            if value is not None:
                values[f"{_column_letter(c)}{r + 1}"] = value
    return values


def _column_index(key: str) -> int:
    return ord(key) - ord("A")


def _read_sheet(sheet: SheetCells, spec: Pb1TabSpec) -> Pb1Sheet:
    def style(r: int, c: int) -> tuple[str, bool]:
        if c >= sheet.ncols:
            return "General", False
        cell = sheet.cell(r, c)
        return cell.number_format, cell.bold

    indexes = [_column_index(key) for key in spec.columns]
    if spec.header_marker is not None:
        header_index = next(
            (r for r in range(sheet.nrows) if _text(sheet, r, 0).strip().lower().startswith(spec.header_marker)),
            None,
        )
        if header_index is None:
            raise ValueError(f"Header row not found in sheet {sheet.name!r}")
        headers = {
            key: None if (v := _cell_value(sheet, header_index, c)) is None else str(v)
            for key, c in zip(spec.columns, indexes)
        }
        start = header_index + 1
    else:
        headers = {}
        start = (spec.first_row or 1) - 1
    for key, header in spec.header_overrides:
        headers[key] = header
    for key in spec.narrow_columns:
        if headers:
            headers[key] = "#"

    widths = {
        key: sheet.widths[c] // 256 if c in sheet.widths else 10
        for key, c in zip(spec.columns, indexes)
    }

    def fill(r: int, c: int) -> str | None:
        """Solid fill color of a cell ("#rrggbb"), None without a fill or for white."""
        return sheet.cell(r, c).fill if c < sheet.ncols else None

    rows: dict[int, dict[str, Pb1Cell]] = {}
    # Head rows above the header (Poreski bilans: rows 1-3): every number is an amount, except
    # the form's constants; the cells keep their fill colors.
    head_end = min(spec.head_rows, start - 1) if spec.header_marker is not None else 0
    for r in range(head_end):
        cells = {}
        for key, c in zip(spec.columns, indexes):
            if key in spec.head_dropped_columns:
                cells[key] = Pb1Cell(value=None, number_format="General", bold=False)
                continue
            value = _cell_value(sheet, r, c)
            number_format, bold = style(r, c)
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            amount = is_number and (r + 1, key) != spec.months_cell
            cells[key] = Pb1Cell(
                value=value, number_format=number_format, bold=bold, amount=amount, fill=fill(r, c)
            )
        rows[r + 1] = cells
    if spec.months_cell and spec.months_label and spec.months_cell[0] <= head_end:
        # The label of the months in business, in the empty cell left of the number.
        label_row, months_column = spec.months_cell
        label_column = chr(ord(months_column) - 1)
        label_cell = rows[label_row].get(label_column)
        if label_cell is not None and label_cell.value is None:
            rows[label_row][label_column] = replace(label_cell, value=spec.months_label)

    # Form rows: from the start down; the form ends after more than max_empty_rows empty rows.
    empty_run = 0
    removed = _removed_rows(sheet, spec, indexes)
    for r in range(start, sheet.nrows):
        if r + 1 in removed:
            continue  # not part of the form; doesn't end it either (the snapshot has no cells there)
        values = [_cell_value(sheet, r, c) for c in indexes]
        if all(v is None for v in values):
            empty_run += 1
            if empty_run > spec.max_empty_rows:
                break
            continue
        empty_run = 0
        cells = {}
        for key, c, value in zip(spec.columns, indexes, values):
            number_format, bold = style(r, c)
            amount = key in spec.value_columns and _is_amount_field(sheet, r, c)
            if key in spec.narrow_columns and isinstance(value, str) and LINE_NUMBER_LABEL.match(value.strip()):
                value = "#"  # "R.b." inside the sheet (Preliminarni rezultat has no header row)
            if key in spec.konto_columns:
                number_format = "General"
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
                    value = None
            cells[key] = Pb1Cell(value=value, number_format=number_format, bold=bold, amount=amount)
        rows[r + 1] = cells
    _apply_amount_fixes(sheet.name, spec, rows)
    summary_start = _find_summary_start(sheet.name, spec, rows)
    dropped = _drop_cells(spec, rows, head_end, summary_start)
    dropped |= {(r, _column_letter(c)) for r in removed for c in range(sheet.ncols)}
    if spec.form_values_are_amounts:
        _form_values_as_amounts(sheet.name, spec, rows, head_end, summary_start)
    # Typo corrections of the descriptive texts (after the fixes, which check the original texts).
    for cells in rows.values():
        for key, cell in cells.items():
            if isinstance(cell.value, str) and any(ch.isalpha() for ch in cell.value):
                cells[key] = replace(cell, value=correct_text(cell.value))
    headers = {key: correct_text(h) if h else h for key, h in headers.items()}
    _apply_official_lines(sheet.name, spec, rows)
    for key in spec.narrow_columns:
        texts = [t for cells in rows.values() if (t := _short_text(cells[key].value))]
        widths[key] = max((len(t) for t in [*texts, "#"]), default=1)
    # Headers are shown on one line: a column is at least as wide as its header.
    for key, header in headers.items():
        if header and key not in spec.narrow_columns:
            widths[key] = max(widths[key], len(header))
    return Pb1Sheet(
        spec=spec, name=sheet.name, headers=headers, column_widths=widths, rows=rows, summary_start=summary_start,
        head_end=head_end, dropped=dropped,
    )


DESCRIPTION_COLUMN = "B"


def _line_number(value: CellValue) -> int | None:
    """A line number in column A (1, 1.0, "1"); None when blank."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else None
    text = str(value).strip().rstrip(".")
    return int(text) if text.isdigit() else None


def _apply_official_lines(sheet_name: str, spec: Pb1TabSpec, rows: dict[int, dict[str, Pb1Cell]]) -> None:
    """The official line numbers ("#", column A) and descriptions ("Opis", column B) of the
    form (app/pb1_official.py), display only; an entry whose row doesn't hold the expected line
    number of the workbook is skipped (WARNING)."""
    for line in OFFICIAL_LINES.get(spec.key, ()):
        cells = rows.get(line.row)
        if cells is None or "A" not in cells or "B" not in cells:
            logger.warning("%s: row %d for official line %s not found", sheet_name, line.row, line.number)
            continue
        found = _line_number(cells["A"].value)
        if found != line.file_number:
            logger.warning(
                "%s: row %d has line number %s, expected %s; official line not applied",
                sheet_name, line.row, found, line.file_number,
            )
            continue
        if line.file_number is not None and line.number != line.file_number:
            cells["A"] = replace(cells["A"], value=line.number)
        if line.text:
            cells["B"] = replace(cells["B"], value=line.text)


def _form_values_as_amounts(sheet_name: str, spec: Pb1TabSpec, rows: dict[int, dict[str, Pb1Cell]],
                            head_end: int, summary_start: int | None) -> None:
    """Makes every value-column cell of the form lines an amount field (spec.form_values_are_amounts);
    blank text counts as empty. A cell holding real text is left as it is (WARNING)."""
    for r, cells in rows.items():
        if r <= head_end or (summary_start is not None and r >= summary_start):
            continue
        description = cells.get(DESCRIPTION_COLUMN)
        if not str((description.value if description else None) or "").strip() and not any(c.amount for c in cells.values()):
            continue  # a spacer row (no description, no amount): no fields
        for key in spec.value_columns:
            cell = cells.get(key)
            if cell is None or cell.amount or cell.dropped or cell.hidden:
                continue
            if isinstance(cell.value, str) and cell.value.strip():
                logger.warning("PB-1 sheet %r cell %s%d holds text %r; not an amount field", sheet_name, key, r, cell.value)
                continue
            value = None if isinstance(cell.value, str) else cell.value
            cells[key] = replace(cell, value=value, amount=True)


def _drop_cells(spec: Pb1TabSpec, rows: dict[int, dict[str, Pb1Cell]], head_end: int,
                summary_start: int | None) -> frozenset[tuple[int, str]]:
    """Empties the cells that are not part of the form (spec.summary_dropped_columns,
    spec.section_rows_empty) in `rows` (Pb1Cell.dropped); returns them as (row, column)."""
    dropped: set[tuple[int, str]] = set()
    keep = {*spec.narrow_columns, DESCRIPTION_COLUMN, spec.comment_column}
    for r, cells in rows.items():
        if r <= head_end:
            continue
        if summary_start is not None and r >= summary_start:
            gone = [k for k in cells if k in spec.summary_dropped_columns]
        elif spec.section_rows_empty:
            description = cells.get(DESCRIPTION_COLUMN)
            section = description is not None and description.bold and str(description.value or "").strip()
            gone = [
                k for k in cells
                if k not in keep and (r, k) not in spec.section_hidden and (r, k) not in spec.section_shown
            ] if section else []
            if section:
                for key in cells:
                    if (r, key) in spec.section_hidden:
                        cells[key] = replace(cells[key], hidden=True)
        else:
            gone = []
        gone += [k for k in cells if (r, k) in spec.dropped_cells and k not in gone]
        for key in gone:
            cells[key] = Pb1Cell(value=None, number_format="General", bold=False, dropped=True)
            dropped.add((r, key))
    for r, cells in rows.items():
        if r <= head_end:
            dropped.update((r, k) for k in spec.head_dropped_columns)
    return frozenset(dropped)


def _removed_rows(sheet: SheetCells, spec: Pb1TabSpec, indexes: list[int]) -> frozenset[int]:
    """The rows that are not part of the form (spec.dropped_rows; Excel rows). A row that still
    has a description (the workbook) must start with the expected text, else it is kept (WARNING);
    in the stored snapshot the row is already empty."""
    removed: set[int] = set()
    column = indexes[list(spec.columns).index(DESCRIPTION_COLUMN)]
    for r, label in spec.dropped_rows:
        description = _cell_value(sheet, r - 1, column)
        if description is not None and not _label_key(description).startswith(_label_key(label)):
            logger.warning("%s: row %d is not '%s'; not removed", sheet.name, r, label)
            continue
        removed.add(r)
    return frozenset(removed)


def match_tab_sheets(workbook: str, sheets: list[SheetCells]) -> dict[str, SheetCells]:
    """tab key -> the sheet of that tab (by sheet name), in PB1_TABS order."""
    matched: dict[str, SheetCells] = {}
    for spec in PB1_TABS:
        sheet = next((s for s in sheets if s.name.strip().startswith(spec.sheet_prefix)), None)
        if sheet is None:
            logger.warning("PB-1 %s: no sheet %r…; tab %s left out", workbook, spec.sheet_prefix, spec.key)
            continue
        matched[spec.key] = sheet
    return matched


def build_pb1_workbook(workbook: str, tab_sheets: dict[str, SheetCells]) -> Pb1Workbook:
    """The PB-1 form from the sheets of its tabs, read from the file or from the database."""
    sheets: dict[str, Pb1Sheet] = {}
    raw: dict[str, dict[str, CellValue]] = {}
    company_name = None
    for spec in PB1_TABS:
        sheet = tab_sheets.get(spec.key)
        if sheet is None:
            continue
        sheets[spec.key] = _read_sheet(sheet, spec)
        raw[spec.key] = _raw_values(sheet)
        if spec.key == DEFAULT_TAB:
            # The company name is the last text in column B above the header ("PB 1 2025" is the title).
            # Header row (0-based): the row before the first form row (after the head rows).
            read = sheets[spec.key]
            form_rows = [r for r in read.rows if r > read.head_end]
            header_row = min(form_rows) - 2 if form_rows else 0
            company_name = next(
                (_text(sheet, r, 1).strip() for r in range(header_row - 1, -1, -1)
                 if _text(sheet, r, 1).strip() and not _text(sheet, r, 1).strip().upper().startswith("PB")),
                None,
            )
    if DEFAULT_TAB not in sheets:
        raise ValueError(f"Sheet {PB1_TABS[0].sheet_prefix!r} not found")
    return Pb1Workbook(workbook=workbook, company_name=company_name, sheets=sheets, raw=raw)
