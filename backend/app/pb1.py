"""PB-1 detail page API.

Every company gets the same PB-1 table (template from "<year> PB-1.xls"). The amounts
from the file are shown only for the company the file belongs to.

That company is found through a stored link to its identity (pb1_link: the company-list
row; in the database the company_year), never through its current name or PIB, which can
be edited in the Company Registry. The link is made once from the company name written in
the PB-1 file (the file has no PIB), compared with the ORIGINAL GFI names without legal
form / city / case; exactly one company of the list must match. It is made again only if
the PB-1 file is replaced by one for a different company.

Fields can be edited (save_pb1_cell, used by the API and meant for automated filling too),
except the read-only ones (pb1_edit_kind) and the computed ones. Amounts are saved for the
company; template fields (comments, konto, ...) are shared by every company. Edits are kept in
SQLite (edits.db, also in PostgreSQL mode for now); the PB-1 workbook is never written.

Cells that hold a formula in the workbook are computed with that formula from the current
values (app.pb1_formulas), across the three tabs, and are read-only.

Tax loss (LOSS_RULES): when a tax base (Poreska osnovica) is negative, the company has a tax
loss: the tax of that base is 0 and read-only, so the monthly advance (a formula of the tax)
is 0 too. The Poreski bilans base decides the "Gubitak!" banner (Pb1Table.loss).

Comments (Poreski bilans, column "Komentar, stopa, konto"): one per row and company, shown
beside the table. The defaults come from the settings (pb1_comment_defaults, filled once from
the workbook); a company's own comment replaces its default for that company only. Numeric
comments (the rates of lines 22-25) are inputs of the formulas.
"""

import math
import re
from dataclasses import dataclass
from typing import Literal

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app import edits_store
from app.auth import require_user
from app.db import database_enabled, session_scope
from app.gfi_store import Edits, GfiStore, get_gfi_store
from app.gfi_workbook import SourceTable
from app.logging_config import get_logger
from app.models import SourceFile
from app.pb1_formulas import FORMULAS, Calculator, result_value, split_address, verify_formulas
from app.pb1_pdf import build_pb1_pdf
from app.pb1_workbook import (
    DEFAULT_TAB,
    PB1_TABS,
    CellValue,
    Pb1Cell,
    Pb1Sheet,
    Pb1Workbook,
    find_pb1_workbook,
    load_pb1_workbook,
    normalize_company_name,
)
from app.reporting_years import get_data_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reporting-years/{year}/companies/{row}", tags=["pb1"])

NAME_HEADER = "NAZIV"
PIB_HEADER = "PIB"


class Company(BaseModel):
    row: int  # Excel row in the GFI workbook
    name: str
    pib: str | None


class Pb1Column(BaseModel):
    key: str
    header: str | None
    width: int  # characters, from the Excel sheet
    wrap: bool = False  # long descriptions wrap
    amount: bool = False  # amount column (company values; right-aligned)
    narrow: bool = False  # line-number column ("#"); longer text overflows into empty cells to the right


class Pb1CellOut(BaseModel):
    value: CellValue = None
    format: str | None = None  # omitted for "General"
    bold: bool = False
    # Amount field of the form (same for every company): shown with 2 decimals, 0 when empty.
    amount: bool = False
    editable: bool = False  # every field except the line numbers
    number: bool = False  # edited as a number (amounts, numeric template fields); else as text
    edited: bool = False  # changed in the app (amount: for this company; template: for all companies)
    fill: str | None = None  # fill color from the sheet ("#rrggbb"; head rows only)
    formula: bool = False  # computed with the workbook's formula (read-only)


class Pb1RowOut(BaseModel):
    row: int
    cells: dict[str, Pb1CellOut]
    # Section row: its description (column B) is bold in the sheet; shown with a grey background.
    shaded: bool = False


class Pb1Tab(BaseModel):
    key: str  # "poreski-bilans" | "uporedo" | "preliminarni"
    title: str  # Excel sheet name


class Pb1Table(BaseModel):
    company: Company
    workbook: str
    tab: str  # key of the tab returned
    tabs: list[Pb1Tab]  # the form's tabs (same for every company)
    sheet: str  # Excel sheet name of this tab
    has_values: bool  # True when the file's amounts belong to this company (same for all tabs)
    entered: int = 0  # amounts of this tab entered in the app for this company
    columns: list[Pb1Column]  # header is null for every column when the sheet has no header row
    rows: list[Pb1RowOut]
    # The form's closing rows (Poreski bilans: Poreska osnovica, Porez 15%, Mesecna akontacija),
    # shown as a separate table below the form, with the same columns.
    summary: list[Pb1RowOut] = []
    # The sheet's first rows (Poreski bilans: title, company name, class 5/6 totals), shown as a
    # separate table above the form, with the same columns.
    head: list[Pb1RowOut] = []
    head_columns: list[Pb1Column] = []  # the head table's columns, one to one with `columns`
    # Column of the comments (in the rows' cells, not in `columns`): shown beside the table as
    # description-comment pairs, one per row, each company its own.
    comment_column: str | None = None
    loss: Pb1Loss | None = None  # tax loss: the Poreski bilans tax base is negative ("Gubitak!")


class Pb1CellUpdate(BaseModel):
    value: float | str | None  # number for amounts / numeric fields, text otherwise; None clears


class Pb1ComputedCell(BaseModel):
    row: int  # Excel row of the form
    column: str
    value: CellValue


class Pb1Loss(BaseModel):
    """A tax loss: the Poreski bilans tax base (Poreska osnovica) is negative."""

    base: float  # the negative tax base


class Pb1CellUpdateResult(BaseModel):
    row: int  # Excel row of the form
    column: str
    value: CellValue
    edited: bool
    shared: bool  # template field: the change applies to every company
    # The tab's computed cells after the change (formulas follow their inputs at once).
    computed: list[Pb1ComputedCell] = []
    loss: Pb1Loss | None = None  # tax loss after the change (the page reloads when it changes)


Pb1EditKind = Literal["amount", "number", "text", "comment", "months"]
# A company's number of months in business: whole months of one year.
MONTHS_RANGE = range(1, 13)
# For now the months in business are fixed (the file's 12, read-only for every company); they
# may be calculated automatically later. True: each company's own value, edited like an amount.
MONTHS_EDITABLE = False


class Pb1EditError(ValueError):
    """A PB-1 form that can't be loaded or a value that can't be saved; status_code is the
    matching HTTP status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Pb1Form:
    """One tab of a company's PB-1 form with everything needed to show or edit it."""

    year: int
    tab: str
    company: "Company"
    company_key: tuple[str, int]  # (GFI workbook, GFI row): the company's identity for its amounts
    pb1: Pb1Workbook
    sheet: Pb1Sheet
    has_values: bool
    # Year of the PB-1 workbook used as the form: the year itself, or (a year constructed on the
    # Migracija page) the year it was built from; then the form is empty for every company and
    # the years written in its texts are moved on by the difference.
    template_year: int = 0


def _is_number(value: CellValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def pb1_edit_kind(sheet: Pb1Sheet, row: int, column: str, cell: Pb1Cell) -> Pb1EditKind | None:
    """How a field can be edited: an amount (per company), a numeric or text template field
    (shared by every company), or None. Read-only: line numbers (#), descriptions (Opis) and
    the tab's other read-only columns and top rows. Empty template fields in the amount
    columns are numbers, elsewhere texts."""
    spec = sheet.spec
    if column == spec.comment_column and row > sheet.head_end:
        return "comment"  # the company's own comment (a number for a rate)
    if row <= sheet.head_end:
        # Head rows above the form: only their numbers can be edited (amounts per company; the
        # form's constants, e.g. 12 months, for every company).
        if cell.amount:
            return "amount"
        return "months" if MONTHS_EDITABLE and (row, column) == spec.months_cell else None
    if column in spec.narrow_columns or column in spec.readonly_columns:
        return None
    if spec.readonly_top is not None and row <= spec.readonly_top[0] and column in spec.readonly_top[1]:
        return None
    if cell.amount:
        return "amount"
    if _is_number(cell.value) or (cell.value is None and column in spec.value_columns):
        return "number"
    return "text"


def _same_value(kind: Pb1EditKind, value: CellValue, original: CellValue) -> bool:
    """Whether a saved value equals the value shown before any edit (then there is no edit).
    Amounts are compared as shown: to two decimals (the file may hold more), and an amount
    field without a number (" ", #DIV/0!) is empty."""
    if kind == "amount":
        value, original = (v if _is_number(v) else None for v in (value, original))
    if _is_number(value) and _is_number(original):
        if kind == "amount":
            return round(float(value), 2) == round(float(original), 2)
        return math.isclose(value, original, rel_tol=1e-9, abs_tol=1e-12)
    return value == original


def _shown_original(cell: Pb1Cell, has_values: bool) -> CellValue:
    """The value shown before any edit: the file's amounts only for the file's company."""
    return cell.value if (not cell.amount or has_values) else None


def _column_for(source: SourceTable, header: str) -> str | None:
    return next((k for k, h in source.headers.items() if h and h.strip().upper() == header), None)


def _company_at(source: SourceTable, edits: Edits, row: int) -> Company:
    """The company in a GFI row, with its current details (edits included) for display."""
    name_col, pib_col = _column_for(source, NAME_HEADER), _column_for(source, PIB_HEADER)
    cells = source.rows.get(row)
    original_name = cells[name_col].value if cells and name_col else None
    if not isinstance(original_name, str) or not original_name.strip():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No company in row {row}")

    def current(col: str | None) -> CellValue:
        if col is None:
            return None
        edit = edits.get((row, col))
        return edit[0] if edit is not None else cells[col].value

    name = current(name_col)
    return Company(row=row, name=str(name).strip() if name else original_name.strip(), pib=_pib(current(pib_col)))


def _pib(value: CellValue) -> str | None:
    return None if value in (None, "") else str(value).strip()


def _match_by_original_name(source: SourceTable, pb1: Pb1Workbook) -> int | None:
    """Row of the company named in the PB-1 file, compared with the ORIGINAL GFI names
    (as imported; never the edited ones). Exactly one company of the list must match."""
    if not pb1.company_name:
        return None
    target = normalize_company_name(pb1.company_name)
    name_col = _column_for(source, NAME_HEADER)
    rows = [
        row for row, cells in source.rows.items()
        if name_col and isinstance(cells[name_col].value, str) and normalize_company_name(cells[name_col].value) == target
    ]
    if len(rows) != 1:
        logger.warning("PB-1 company %r in %s matches %d GFI companies; not linked", pb1.company_name, pb1.workbook, len(rows))
        return None
    return rows[0]


def pb1_owner_row(store: GfiStore, year: int, source: SourceTable, pb1: Pb1Workbook, user: str) -> int | None:
    """The company (Excel row of the company list) the PB-1 file belongs to.

    Found through the stored link (pb1_link), i.e. by company identity: editing the
    company's name or PIB doesn't affect it. The link is made once, from the company name
    in the PB-1 file, and is made again only if the PB-1 file now names a different company
    or the linked company is no longer in the list."""
    link = store.pb1_link(year, pb1.workbook)
    if link is not None and link.pb1_company == pb1.company_name and link.row in source.rows:
        return link.row
    row = _match_by_original_name(source, pb1)
    if row is None:
        if link is not None:
            store.delete_pb1_link(year, pb1.workbook)
            logger.warning("PB-1 link of %s removed: no matching company in the list", pb1.workbook)
        return None
    store.save_pb1_link(year, pb1.workbook, pb1.company_name or "", row, user)
    logger.info("PB-1 %s linked to GFI row %d (%r)", pb1.workbook, row, pb1.company_name)
    return row


def load_pb1_form(year: int, row: int, tab: str, user: str) -> Pb1Form:
    """The company's PB-1 form tab; raises Pb1EditError (404/500) when it can't be loaded."""
    if tab not in {spec.key for spec in PB1_TABS}:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"Unknown PB-1 tab {tab!r}")
    # Company details come from the GFI data (PostgreSQL or Excel); PB-1 itself is still read from Excel.
    store = get_gfi_store()
    source, edits = store.load(year)
    try:
        company = _company_at(source, edits, row)
    except HTTPException as exc:
        raise Pb1EditError(exc.status_code, str(exc.detail)) from None

    template = pb1_template(year)
    if template is None:
        logger.warning("No PB-1 form for reporting year %s", year)
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"No PB-1 form for reporting year {year}")
    path, template_year = template
    try:
        pb1 = load_pb1_workbook(path)
    except Exception:
        logger.exception("Failed to read PB-1 workbook %s", path.name)
        raise Pb1EditError(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to read the PB-1 workbook") from None

    sheet = pb1.sheets.get(tab)
    if sheet is None:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"The PB-1 workbook has no {tab!r} sheet")
    # The file's amounts belong to one company of the file's own year, found by its identity
    # (stored link). A form built from another year's file has no amounts for anyone.
    has_values = template_year == year and pb1_owner_row(store, year, source, pb1, user) == row
    return Pb1Form(
        year=year, tab=tab, company=company, company_key=(source.workbook, row),
        pb1=pb1, sheet=sheet, has_values=has_values, template_year=template_year,
    )


def pb1_template(year: int) -> tuple[Path, int] | None:
    """The PB-1 workbook used as the form of `year` and the year of that workbook: the year's
    own "<year> PB-1.xls", or, for a year constructed on the Migracija page (a constructed
    'pb1' source_file), the form of the year it was built from (followed back to a workbook)."""
    seen: set[int] = set()
    while year not in seen:
        seen.add(year)
        path = find_pb1_workbook(get_data_dir(), year)
        if path is not None:
            return path, year
        if not database_enabled():
            return None
        with session_scope() as session:
            based_on = session.scalar(
                select(SourceFile.based_on_year).where(
                    SourceFile.kind == "pb1", SourceFile.year == year, SourceFile.origin == "constructed"
                )
            )
        if based_on is None:
            return None
        year = based_on
    return None


_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")


def shift_years(value: CellValue, delta: int) -> CellValue:
    """A template text of a form built from another year's workbook, with its years moved on
    ("PB 1 2025" -> "PB 1 2026" for a 2026 form built from 2025)."""
    if not delta or not isinstance(value, str):
        return value
    return _YEAR.sub(lambda m: str(int(m.group(1)) + delta), value)


# (template edits shared by every company, this company's edits: amounts and comments,
#  the default comments of the tab: row -> value) of one tab
TabEdits = tuple[edits_store.Pb1Edits, edits_store.Pb1Edits, dict[int, CellValue]]

_seeded_comments: set[tuple[int, str]] = set()  # (year, PB-1 workbook) whose defaults are stored


def _comment_value(cell: Pb1Cell) -> CellValue:
    """A comment as stored in the settings: a rate (number in a percent format) stays a number,
    the formulas use it; anything else is text (konto numbers such as 670 included)."""
    value = cell.value
    if _is_number(value):
        if "%" in cell.number_format:
            return value
        return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def comment_defaults(year: int, pb1: Pb1Workbook, tab: str, user: str) -> dict[int, CellValue]:
    """The default comments of a tab (settings). The first time a workbook is used, the comments
    written in it are stored as the defaults of the rows that have none yet."""
    if (year, pb1.workbook) not in _seeded_comments:
        for key, sheet in pb1.sheets.items():
            column = sheet.spec.comment_column
            if column is None:
                continue
            values = {
                row: _comment_value(cells[column])
                for row, cells in sheet.rows.items()
                if row > sheet.head_end and column in cells and _comment_value(cells[column]) is not None
            }
            added = edits_store.seed_pb1_comment_defaults(year, pb1.workbook, key, values, user)
            if added:
                logger.info("PB-1 comment defaults of %s (%s) stored from the workbook: %d", pb1.workbook, key, added)
        _seeded_comments.add((year, pb1.workbook))
    if pb1.sheets.get(tab) is None or pb1.sheets[tab].spec.comment_column is None:
        return {}
    return edits_store.get_pb1_comment_defaults(year, pb1.workbook, tab)

# PB-1 workbook name -> (the loaded workbook, its computed cells per tab: {(row, column)})
_computed_cache: dict[str, tuple[Pb1Workbook, dict[str, set[tuple[int, str]]]]] = {}


def computed_cells(pb1: Pb1Workbook) -> dict[str, set[tuple[int, str]]]:
    """The form cells computed with the workbook's formulas, per tab: amount fields that hold a
    formula. Empty when the formulas don't reproduce Excel's stored results for this workbook
    (then the file's values are shown and can be edited, as without formulas)."""
    cached = _computed_cache.get(pb1.workbook)
    if cached is not None and cached[0] is pb1:
        return cached[1]
    cells: dict[str, set[tuple[int, str]]] = {}
    for tab, formulas in FORMULAS.items():
        sheet = pb1.sheets.get(tab)
        if sheet is None:
            continue
        for address in formulas:
            column, row = split_address(address)
            cell = sheet.rows.get(row, {}).get(column)
            if cell is not None and cell.amount and column in sheet.spec.columns:
                cells.setdefault(tab, set()).add((row, column))
    mismatches = verify_formulas(pb1.raw, {tab: set(FORMULAS[tab]) for tab in pb1.sheets if tab in FORMULAS})
    if mismatches:
        logger.error(
            "PB-1 formulas don't match %s (%d differences, e.g. %s); computed cells are off for this workbook",
            pb1.workbook, len(mismatches), "; ".join(mismatches[:3]),
        )
        cells = {}
    else:
        logger.info(
            "PB-1 formulas verified against %s: %d computed cells", pb1.workbook, sum(len(c) for c in cells.values())
        )
    _computed_cache[pb1.workbook] = (pb1, cells)
    return cells


def _all_edits(form: Pb1Form, user: str = "system") -> dict[str, TabEdits]:
    """The edits and default comments of every tab of the form (the formulas reach across tabs)."""
    return {
        tab: (
            edits_store.get_pb1_edits(form.year, form.pb1.workbook, tab, *edits_store.TEMPLATE_COMPANY),
            edits_store.get_pb1_edits(form.year, form.pb1.workbook, tab, *form.company_key),
            comment_defaults(form.year, form.pb1, tab, user),
        )
        for tab in form.pb1.sheets
    }


def _cell_view(
    form: Pb1Form, tab: str, row: int, column: str, cell: Pb1Cell, edits: TabEdits
) -> tuple[CellValue, Pb1EditKind | None, tuple[CellValue, CellValue] | None]:
    """(value shown, how it can be edited, the edit applied) of a form cell without a formula."""
    sheet = form.pb1.sheets[tab]
    template_edits, company_edits, defaults = edits
    kind = pb1_edit_kind(sheet, row, column, cell)
    # Amount fields are empty for every company except the owner of the file; template
    # text in the amount columns (e.g. "RSD" in Preliminarni rezultat) stays for everyone.
    value = _shown_original(cell, form.has_values)
    if kind == "comment":
        value = defaults.get(row)  # the default comment (settings), for every company
    if (row, column) == sheet.spec.company_name_cell:
        value = form.company.name  # the name written in the file belongs to the file's company
    own = kind in ("amount", "comment", "months")  # saved for the company
    edit = (company_edits if own else template_edits).get((row, column)) if kind else None
    if edit is not None and _same_value(kind, edit[0], value):
        edit = None  # stored, but equal to what is shown (e.g. an empty amount over " ")
    if edit is not None:
        value = edit[0]
    return value, kind, edit


# Tax loss: tax cell -> its tax base. When the base is negative, the tax is 0 and read-only
# (in Excel the tax is typed in; the monthly advance is a formula of it and follows).
LOSS_RULES: dict[tuple[str, str], tuple[str, str]] = {
    ("poreski-bilans", "C87"): ("poreski-bilans", "C86"),  # Porez 15% <- Poreska osnovica (69)
    ("uporedo", "C13"): ("uporedo", "C12"),  # Porez na dobit za godinu <- Poreska osnovica (8), year
    ("uporedo", "D13"): ("uporedo", "D12"),  # the same for the previous year
    ("preliminarni", "C14"): ("preliminarni", "C13"),  # Porez na dobit <- Poreska osnovica (8)
}
LOSS_BANNER_BASE = ("poreski-bilans", "C86")


def _negative(value: object) -> bool:
    return isinstance(value, float) and value < 0


def _loss_zeroed(calc: Calculator, tab: str, address: str) -> bool:
    """Whether a tax cell is 0 because its tax base is negative (a tax loss)."""
    base = LOSS_RULES.get((tab, address))
    return base is not None and _negative(calc.value(*base))


def _loss(calc: Calculator) -> Pb1Loss | None:
    base = calc.value(*LOSS_BANNER_BASE)
    return Pb1Loss(base=base) if _negative(base) else None


def _calculator(form: Pb1Form, edits: dict[str, TabEdits]) -> Calculator:
    """Evaluates the formulas of this company's form. Inputs: form cells as shown (edits
    included); helper cells outside the form from the file for the file's company, else empty;
    a tax with a negative tax base is 0 (LOSS_RULES)."""
    calc: Calculator

    def input_value(tab: str, address: str) -> CellValue:
        if (tab, address) in LOSS_RULES and _loss_zeroed(calc, tab, address):
            return 0.0
        column, row = split_address(address)
        sheet = form.pb1.sheets.get(tab)
        cell = sheet.rows.get(row, {}).get(column) if sheet and column in sheet.spec.columns else None
        if cell is not None:
            return _cell_view(form, tab, row, column, cell, edits[tab])[0]
        return form.pb1.raw.get(tab, {}).get(address) if form.has_values else None

    calc = Calculator(input_value)
    return calc


def _computed_values(form: Pb1Form, calc: Calculator) -> list[Pb1ComputedCell]:
    cells = set(computed_cells(form.pb1).get(form.tab, set()))
    cells |= {
        (split_address(a)[1], split_address(a)[0])
        for (t, a) in LOSS_RULES if t == form.tab and _loss_zeroed(calc, t, a)
    }
    return [
        Pb1ComputedCell(row=row, column=column, value=result_value(calc.value(form.tab, f"{column}{row}")))
        for row, column in sorted(cells)
    ]


def build_pb1_table(form: Pb1Form) -> Pb1Table:
    sheet = form.sheet
    # A form built from another year's workbook: its texts name that year; move them on.
    delta = form.year - form.template_year if form.template_year else 0
    edits = _all_edits(form)
    calc = _calculator(form, edits)
    computed = computed_cells(form.pb1).get(form.tab, set())
    company_edits = edits[form.tab][1]
    comment_column = sheet.spec.comment_column
    rows = []
    for row_number, cells in sheet.rows.items():
        out = {}
        for key, cell in cells.items():
            formula = (row_number, key) in computed or _loss_zeroed(calc, form.tab, f"{key}{row_number}")
            if formula:
                # Computed with the workbook's formula from the current values; read-only.
                value, kind, edit = result_value(calc.value(form.tab, f"{key}{row_number}")), None, None
            else:
                value, kind, edit = _cell_view(form, form.tab, row_number, key, cell, edits[form.tab])
                if kind is None and (row_number, key) != sheet.spec.company_name_cell:
                    value = shift_years(value, delta)
                if kind == "comment":
                    # A rate is edited as a number (the formulas use it), any other comment as text.
                    kind = "number" if _is_number(value) or _is_number(edits[form.tab][2].get(row_number)) else "text"
            out[key] = Pb1CellOut(
                value=value,
                format=None if cell.number_format == "General" else cell.number_format,
                bold=cell.bold,
                amount=cell.amount,
                editable=kind is not None,
                number=kind in ("amount", "number", "months"),
                edited=edit is not None,
                fill=cell.fill,
                formula=formula,
            )
        description = cells.get("B")
        shaded = row_number > sheet.head_end and bool(
            description and description.bold and str(description.value or "").strip()
        )
        rows.append(Pb1RowOut(row=row_number, cells=out, shaded=shaded))
    start = sheet.summary_start
    head = [r for r in rows if r.row <= sheet.head_end]
    summary = [r for r in rows if start is not None and r.row >= start]
    rows = [r for r in rows if r.row > sheet.head_end and (start is None or r.row < start)]

    def column_out(k: str) -> Pb1Column:
        return Pb1Column(
            key=k, header=shift_years(sheet.headers.get(k), delta), width=sheet.column_widths[k],
            wrap=k in sheet.spec.wrap_columns, amount=k in sheet.spec.value_columns,
            narrow=k in sheet.spec.narrow_columns,
        )

    # The comment column is shown beside the table (description-comment pairs), not in it.
    columns = [column_out(k) for k in sheet.spec.columns if k != comment_column]
    head_columns = [column_out(k) for k in sheet.spec.head_columns] if sheet.spec.head_columns else []
    tabs = [Pb1Tab(key=key, title=shift_years(s.name, delta)) for key, s in form.pb1.sheets.items()]
    return Pb1Table(
        company=form.company, workbook=form.pb1.workbook, tab=form.tab, tabs=tabs, sheet=shift_years(sheet.name, delta),
        has_values=form.has_values,
        entered=len({k for k in company_edits if k[1] != comment_column} - computed),
        columns=columns, rows=rows, summary=summary, head=head, head_columns=head_columns,
        comment_column=comment_column, loss=_loss(calc),
    )


def save_pb1_cell(
    year: int, row: int, tab: str, cell_row: int, column: str, value: float | str | None, user: str
) -> Pb1CellUpdateResult:
    """Saves one field of a company's PB-1 form: the service behind the API, also meant for
    automated filling. Amounts are saved for the company, template fields for every company.
    Saving the value shown before any edit removes the edit. Raises Pb1EditError."""
    form = load_pb1_form(year, row, tab, user)
    cell = form.sheet.rows.get(cell_row, {}).get(column)
    if cell is None:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"PB-1 field {column}{cell_row} not found in {tab!r}")
    if (cell_row, column) in computed_cells(form.pb1).get(tab, set()):
        raise Pb1EditError(status.HTTP_409_CONFLICT, f"PB-1 field {column}{cell_row} is computed by a formula")
    kind = pb1_edit_kind(form.sheet, cell_row, column, cell)
    if kind is None:
        raise Pb1EditError(status.HTTP_409_CONFLICT, f"PB-1 field {column}{cell_row} is read-only")
    edits = _all_edits(form, user)
    if _loss_zeroed(_calculator(form, edits), tab, f"{column}{cell_row}"):
        raise Pb1EditError(status.HTTP_409_CONFLICT, f"PB-1 field {column}{cell_row} is 0: the tax base is negative (tax loss)")
    original = (
        _cell_view(form, tab, cell_row, column, cell, (*edits[tab][:1], {}, edits[tab][2]))[0]
        if kind == "comment" else _shown_original(cell, form.has_values)
    )
    # A comment is a number when its default is (a rate), else text.
    value_kind = ("number" if _is_number(original) else "text") if kind == "comment" else kind
    if kind == "months":
        # Monthly advance = tax / months in business: whole months of one year (empty = default).
        if value is not None and (isinstance(value, str) or not float(value).is_integer() or int(value) not in MONTHS_RANGE):
            raise Pb1EditError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Months in business must be a whole number from 1 to 12")
        value = int(value) if value is not None else original
    elif value_kind in ("amount", "number"):
        if isinstance(value, str) or (value is not None and not math.isfinite(value)):
            raise Pb1EditError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Value must be a finite number")
        if value is not None and float(value).is_integer():
            value = int(value)
    else:
        if value is not None and not isinstance(value, str):
            raise Pb1EditError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Value must be text")
        value = (" ".join(value.split()) or None) if value is not None else None

    shared = kind not in ("amount", "comment", "months")  # the company's own values
    company = edits_store.TEMPLATE_COMPANY if shared else form.company_key
    key = (year, form.pb1.workbook, tab, cell_row, column, *company)
    edited = not _same_value(kind, value, original)
    if edited:
        edits_store.save_pb1_edit(*key, value, original, user)
    else:
        edits_store.delete_pb1_edit(*key)
    logger.info(
        "PB-1 %s %s%d %s by '%s' (%s)", tab, column, cell_row, "edited" if edited else "reverted", user,
        "all companies" if shared else f"company row {row}",
    )
    logger.debug("PB-1 %s %s%d new value: %r", tab, column, cell_row, value)
    calc = _calculator(form, _all_edits(form))
    return Pb1CellUpdateResult(
        row=cell_row, column=column, value=value, edited=edited, shared=shared,
        computed=_computed_values(form, calc), loss=_loss(calc),
    )


@router.get("/pb1", response_model_exclude_defaults=True)
@router.get("/pb1/{tab}", response_model_exclude_defaults=True)
def get_pb1(year: int, row: int, tab: str = DEFAULT_TAB, username: str = Depends(require_user)) -> Pb1Table:
    """One tab of the company's PB-1 form (default: Poreski bilans), with the edits applied."""
    try:
        form = load_pb1_form(year, row, tab, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    table = build_pb1_table(form)
    logger.info(
        "PB-1 %s for '%s' (row %d, %s): %s, %d entered", tab, form.company.name, row, year,
        "values" if form.has_values else "empty template", table.entered,
    )
    return table


@router.put("/pb1/{tab}/cells/{column}/{cell_row}")
def update_pb1_cell(
    year: int, row: int, tab: str, column: str, cell_row: int, update: Pb1CellUpdate,
    username: str = Depends(require_user),
) -> Pb1CellUpdateResult:
    """Saves one field of the company's PB-1 form (see save_pb1_cell)."""
    try:
        return save_pb1_cell(year, row, tab, cell_row, column, update.value, username)
    except Pb1EditError as exc:
        if exc.status_code < 500:
            logger.warning("Rejected PB-1 edit %s %s%d by '%s': %s", tab, column, cell_row, username, exc)
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get("/pb1-pdf")
def get_pb1_pdf(year: int, row: int, inline: bool = False, username: str = Depends(require_user)) -> Response:
    """The company's PB-1 form as a PDF: the three tabs with their current values (edits,
    formulas, comments). `inline`: shown in the browser (for printing) instead of downloaded."""
    tables = []
    try:
        for spec in PB1_TABS:
            form = load_pb1_form(year, row, spec.key, username)
            tables.append(build_pb1_table(form))
    except Pb1EditError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND and spec.key != DEFAULT_TAB and tables:
            logger.warning("PB-1 PDF: tab %s left out: %s", spec.key, exc)
        else:
            raise HTTPException(exc.status_code, str(exc)) from None
    company = tables[0].company
    try:
        pdf = build_pb1_pdf(tables, company.name, company.pib, year)
    except Exception:
        logger.exception("Failed to build the PB-1 PDF for row %d (%s)", row, year)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to build the PDF") from None
    name = re.sub(r'[\/:*?"<>|]+', " ", f"PB-1 {year} {company.name}").strip() + ".pdf"
    disposition = "inline" if inline else "attachment"
    logger.info("PB-1 PDF for '%s' (row %d, %s) by '%s': %d bytes", company.name, row, year, username, len(pdf))
    return Response(
        pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}"},
    )
