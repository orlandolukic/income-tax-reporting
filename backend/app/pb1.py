"""PB-1 detail page API.

Every company gets the same PB-1 table: the year's form (app.pb1_store: the imported snapshot
of "<year> PB-1.xls" in PostgreSQL, or the form of the year a constructed year was built from).
The amounts from the file are shown only for the company the file belongs to.

That company is found through a stored link to its identity (pb1_link: the company-list
row; in the database the company_year), never through its current name or PIB, which can
be edited in the Company Registry. The link is made once from the company name written in
the PB-1 file (the file has no PIB), compared with the ORIGINAL GFI names without legal
form / city / case; exactly one company of the list must match. It is made again only if
the PB-1 file is replaced by one for a different company.

Fields can be edited (save_pb1_cell, used by the API and meant for automated filling too),
except the read-only ones (pb1_edit_kind) and the computed ones. Amounts are saved for the
company; template fields (comments, konto, ...) are shared by every company. Edits and settings
are kept by app.pb1_store in PostgreSQL; no workbook is read or written.

Cells that hold a formula in the workbook are computed with that formula from the current
values (app.pb1_formulas), across the three tabs, and are read-only.

Tax loss (LOSS_RULES): when a tax base (Poreska osnovica) is negative, the company has a tax
loss: the tax of that base is 0 and read-only, so the monthly advance (a formula of the tax)
is 0 too. The Poreski bilans base decides the "Gubitak!" banner (Pb1Table.loss).

Comments (Poreski bilans, column "Komentar, stopa, konto"): global only (user's rule,
2026-11-15): one comment per form row, the same for every year and company (pb1_comment,
filled once from the workbook), shown beside the table read-only and edited only on the Global
Settings page (app.global_settings). There are no year or company comments. Numeric comments (the rates
of lines 22-25) are inputs of the formulas, so they are the same for every company too.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from app.auth import require_user
from app.gfi_store import Edits, GfiStore, get_gfi_store
from app.gfi_table import SourceTable
from app.logging_config import get_logger
from app.pb1_ppdg import PPDG, FormVariant, ppdg_variant, ppdg_workbook
from app.pb1_formulas import FORMULAS, GREEN_OVERRUN_ROWS, SECTION_SUBTOTALS, Calculator, result_value, split_address, unverified_formulas, verify_formulas
from app.pb1_pdf import build_pb1_pdf
from app.pb1_workbook import (
    DEFAULT_TAB,
    PB1_TABS,
    CellValue,
    Pb1Cell,
    Pb1Sheet,
    Pb1Workbook,
    normalize_company_name,
)
from app.pb1_store import FINAL, PRELIMINARY, CompanyKey, Pb1Store, Pb1StoreError, ReportState, TabEdits, get_pb1_store

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
    dash_empty: bool = False  # an empty field is shown as "-" (Konto); "-" entered means empty
    overrun: bool = False  # a positive value is an overrun, shown red (Prekoracenje)
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
    # Text colour: "expense" red, "income" green (Klasa 5 / Klasa 6), "balance" by its sign
    # (Saldo Klasa 6 - 5: above 0 green, below 0 red with the minus).
    tone: str | None = None
    formula: bool = False  # computed with the workbook's formula (read-only)
    red: bool = False  # shown red although positive (an overrun in Prekoracenje)
    # Prekoracenje of a line with "-" in the line 59 formula: an overrun shown green, not red.
    minus: bool = False
    # Signed subtotal of a section's overruns (Prekoracenje of a Roman-numeral heading): > 0 red,
    # < 0 green with its minus; bold on a soft background of its own (user, 2026-11-25).
    subtotal: bool = False
    green: bool = False  # shown green (such an overrun > 0, a negative subtotal; for the PDF)


class Pb1RowOut(BaseModel):
    row: int
    cells: dict[str, Pb1CellOut]
    # Section row: its description (column B) is bold in the sheet; shown with a grey background.
    shaded: bool = False


class Pb1Tab(BaseModel):
    key: str  # "poreski-bilans" | "uporedo" | "preliminarni"
    title: str  # Excel sheet name


class Pb1HeadFigure(BaseModel):
    label: str
    row: int  # the value's cell in `head` (row, column)
    column: str


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
    # The head as labelled values (user, 2026-11-25: one 2 x 4 table, labels over values, no
    # company name, no sheet colours): Klasa 5, Klasa 6, Saldo (Klasa 6 - 5), Meseci poslovanja.
    head_figures: list[Pb1HeadFigure] = []
    # Column of the comments (in the rows' cells, not in `columns`): shown beside the table as
    # description-comment pairs, one per row, each company its own.
    comment_column: str | None = None
    loss: Pb1Loss | None = None  # tax loss: the Poreski bilans tax base is negative ("Gubitak!")
    results: Pb1Results | None = None  # accounting and tax result (Poreski bilans)
    # The company's two reports (user, 2026-11-17): which one this is, and where they stand.
    report: Literal["preliminary", "final"] = "preliminary"
    preliminary_done: bool = False  # the preliminary report is done (locked, still viewable)
    gfi_done: bool = False  # GFI is done: the final report can be created
    final_created: bool = False  # the final report has been created from the preliminary one
    final_done: bool = False  # the final report is done (locked until unlocked)
    submitted_at: datetime | None = None  # the report is submitted (date and time)
    locked: bool = False  # nothing can be changed in this report (done, or not created yet)


class Pb1CellUpdate(BaseModel):
    value: float | str | None  # number for amounts / numeric fields, text otherwise; None clears


class Pb1ComputedCell(BaseModel):
    row: int  # Excel row of the form
    column: str
    value: CellValue


class Pb1Result(BaseModel):
    """A result of the form: its amount and whether it is a profit, a loss or zero."""

    value: float  # rounded to two decimals
    status: Literal["profit", "loss", "zero"]


class Pb1Results(BaseModel):
    """The two results shown beside the closing rows of Poreski bilans (user, 2026-11-17)."""

    accounting: Pb1Result  # Knjigovodstveni rezultat: Klasa 6 - Klasa 5
    tax: Pb1Result  # Poreski rezultat: Poreska osnovica (its loss: tax and monthly advance are 0)


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
    results: Pb1Results | None = None  # the results after the change


Pb1EditKind = Literal["amount", "number", "text", "months"]
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
    company_key: CompanyKey  # (GFI workbook, GFI row): the company's identity for its amounts
    pb1: Pb1Workbook
    sheet: Pb1Sheet
    has_values: bool
    # Year of the PB-1 workbook used as the form: the year itself, or (a year constructed on the
    # Migracija page) the year it was built from; then the form is empty for every company and
    # the years written in its texts are moved on by the difference.
    template_year: int = 0
    store: Pb1Store | None = None  # where the form's edits and settings are kept
    # Which of the company's two reports (preliminary, final), and where they stand.
    report: str = PRELIMINARY
    state: ReportState = ReportState()

    @property
    def locked(self) -> bool:
        """Nothing can be changed: the preliminary report once done, the final one until created
        and while marked as done."""
        if self.report == PRELIMINARY:
            return self.state.preliminary_done
        return not self.state.final_created or self.state.final_done


def _is_number(value: CellValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def pb1_edit_kind(sheet: Pb1Sheet, row: int, column: str, cell: Pb1Cell) -> Pb1EditKind | None:
    """How a field can be edited: an amount (per company), a numeric or text template field
    (shared by every company), or None. Read-only: line numbers (#), descriptions (Opis) and
    the tab's other read-only columns and top rows. Empty template fields in the amount
    columns are numbers, elsewhere texts."""
    spec = sheet.spec
    if column == spec.comment_column and row > sheet.head_end:
        return None  # a global comment: edited only on the Global Settings page
    if cell.dropped or cell.hidden:
        return None  # not part of the form / not shown (section rows, hidden columns of the closing rows)
    if column in spec.konto_columns and row > sheet.head_end:
        return "text"  # Konto: any text or number, kept as typed (shared by every company)
    if sheet.summary_start is not None and row >= sheet.summary_start:
        # The closing rows (the box at the top): only their amount fields (user, 2026-11-16:
        # the field of "V. Poreska osnovica"; the others are formulas).
        return "amount" if cell.amount else None
    if row <= sheet.head_end:
        # Head rows above the form: only their numbers can be edited (amounts per company; the
        # form's constants, e.g. 12 months, for every company).
        if cell.amount:
            return "amount"
        return "months" if MONTHS_EDITABLE and (row, column) == spec.months_cell else None
    if column in spec.narrow_columns or column in spec.readonly_columns or (row, column) in spec.readonly_cells:
        return None
    if spec.readonly_top is not None and row <= spec.readonly_top[0] and column in spec.readonly_top[1]:
        return None
    if cell.amount:
        return "amount"
    if _is_number(cell.value) or (cell.value is None and column in spec.value_columns):
        return "number"
    return "text"


CENT = Decimal("0.01")


# An amount whose format writes negatives in parentheses, e.g. "#,##0.00_);[Red](#,##0.00)":
# shown like every other amount, with a minus sign (user, 2026-11-16).
PARENTHESES_NEGATIVE = re.compile(r";[^;]*\(")
AMOUNT_FORMAT = "#,##0.00;[Red]-#,##0.00"


def _shown_format(cell: Pb1Cell) -> str | None:
    """The cell's number format as sent to the page (None for General); amounts never use
    parentheses for negatives."""
    if cell.amount and PARENTHESES_NEGATIVE.search(cell.number_format or ""):
        return AMOUNT_FORMAT
    return None if cell.number_format == "General" else cell.number_format


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
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"U redu {row} nema firme.")

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


def load_pb1_form(
    year: int, row: int, tab: str, user: str, store: Pb1Store | None = None, report: str | None = None
) -> Pb1Form:
    """The company's PB-1 form tab in one of its reports (None: the final one once the
    preliminary one is done, else the preliminary one); raises Pb1EditError (404/500) when it
    can't be loaded."""
    if tab not in {spec.key for spec in PB1_TABS}:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"Nepoznat PB-1 tab: {tab}.")
    if report not in (None, PRELIMINARY, FINAL):
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"Nepoznat PB-1 izveštaj: {report}.")
    store = store or get_pb1_store()
    # Company details come from the GFI data.
    gfi = get_gfi_store()
    source, edits = gfi.load(year)
    try:
        company = _company_at(source, edits, row)
    except HTTPException as exc:
        raise Pb1EditError(exc.status_code, str(exc.detail)) from None

    try:
        template = store.template(year)
    except Exception:
        logger.exception("Failed to load the PB-1 form of %s (%s)", year, store.name)
        raise Pb1EditError(status.HTTP_500_INTERNAL_SERVER_ERROR, "PB-1 obrazac nije mogao da se učita.") from None
    if template is None:
        logger.warning("No PB-1 form for reporting year %s", year)
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"Za godinu {year} nema PB-1 obrasca.")
    pb1, template_year = template
    # The company's type picks the form: PPDG-1S companies file PB2 (app/pb1_ppdg.py).
    if store.form_type(year, (source.workbook, row)) == PPDG:
        pb1 = ppdg_workbook(pb1)

    sheet = pb1.sheets.get(tab)
    if sheet is None:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"PB-1 obrazac nema tab {tab}.")
    # The file's amounts belong to one company of the file's own year, found by its identity
    # (stored link). A form built from another year's file has no amounts for anyone.
    company_key = (source.workbook, row)
    state = store.report_state(year, company_key)
    if report is None:
        report = FINAL if state.preliminary_done else PRELIMINARY
    # The final report holds only its own copy (pb1_company_edit), never the file's amounts.
    has_values = (
        report == PRELIMINARY and template_year == year and pb1.variant != PPDG
        and pb1_owner_row(gfi, year, source, pb1, user) == row
    )
    return Pb1Form(
        year=year, tab=tab, company=company, company_key=company_key,
        pb1=pb1, sheet=sheet, has_values=has_values, template_year=template_year, store=store,
        report=report, state=state,
    )


def pb1_template(year: int) -> tuple[Pb1Workbook, int] | None:
    """The PB-1 form of `year` and the year of the workbook it comes from (see app.pb1_store)."""
    return get_pb1_store().template(year)


_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")


def shift_years(value: CellValue, delta: int) -> CellValue:
    """A template text of a form built from another year's workbook, with its years moved on
    ("PB 1 2025" -> "PB 1 2026" for a 2026 form built from 2025)."""
    if not delta or not isinstance(value, str):
        return value
    return _YEAR.sub(lambda m: str(int(m.group(1)) + delta), value)


# id of a loaded form -> (the form, its computed cells per tab: {(row, column)}). A form is
# loaded once and kept (app.pb1_store caches it), so this holds only a few entries.
_computed_cache: dict[int, tuple[Pb1Workbook, dict[str, set[tuple[int, str]]]]] = {}


def computed_cells(pb1: Pb1Workbook) -> dict[str, set[tuple[int, str]]]:
    """The form cells computed with the workbook's formulas, per tab: amount fields that hold a
    formula. Empty when the formulas don't reproduce Excel's stored results for this workbook
    (then the file's values are shown and can be edited, as without formulas)."""
    cached = _computed_cache.get(id(pb1))
    if cached is not None and cached[0] is pb1:
        return cached[1]
    cells: dict[str, set[tuple[int, str]]] = {}
    variant = variant_of(pb1)
    for tab, formulas in variant.formulas.items():
        sheet = pb1.sheets.get(tab)
        if sheet is None:
            continue
        for address in formulas:
            column, row = split_address(address)
            cell = sheet.rows.get(row, {}).get(column)
            if cell is not None and cell.amount and column in sheet.spec.columns:
                cells.setdefault(tab, set()).add((row, column))
    unverified = unverified_formulas()
    # The PPDG-1S form has no workbook: nothing to check its formulas against.
    mismatches = verify_formulas(
        pb1.raw,
        {tab: set(FORMULAS[tab]) - unverified.get(tab, set()) for tab in pb1.sheets if tab in FORMULAS},
    ) if variant.verified else []
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
    _computed_cache[id(pb1)] = (pb1, cells)
    return cells


def _all_edits(form: Pb1Form, user: str = "system") -> dict[str, TabEdits]:
    """The edits and the comments of every tab of the form (the formulas reach across tabs)."""
    return form.store.form_edits(form.year, form.pb1, form.company_key, user, form.report)


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
    if column == sheet.spec.comment_column and row > sheet.head_end:
        return defaults.get(row), None, None  # the global comment of the row, for every company
    if (row, column) == sheet.spec.company_name_cell:
        value = form.company.name  # the name written in the file belongs to the file's company
    own = kind in ("amount", "months")  # saved for the company
    edit = (company_edits if own else template_edits).get((row, column)) if kind else None
    if own and form.report == FINAL:
        # The final report: its own stored copy; changed = differs from the copied value.
        if edit is None:
            return None, kind, None
        return edit[0], kind, (None if _same_value(kind, edit[0], edit[1]) else edit)
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

# The two forms (company_year.form_type): PDP, the workbook's, and PPDG-1S (app/pb1_ppdg.py).
PDP_VARIANT = FormVariant(
    key="pdp", formulas=FORMULAS, loss_rules=LOSS_RULES, base=LOSS_BANNER_BASE,
    green_rows=frozenset(GREEN_OVERRUN_ROWS), subtotal_rows=frozenset(SECTION_SUBTOTALS), verified=True,
)
PPDG_VARIANT = ppdg_variant(LOSS_RULES)


def variant_of(pb1: Pb1Workbook) -> FormVariant:
    return PPDG_VARIANT if pb1.variant == PPDG else PDP_VARIANT


def _negative(value: object) -> bool:
    return isinstance(value, float) and value < 0


def _loss_zeroed(calc: Calculator, tab: str, address: str) -> bool:
    """Whether a tax cell is 0 because its tax base is negative (a tax loss)."""
    base = calc.variant.loss_rules.get((tab, address))
    return base is not None and _negative(calc.value(*base))


def _loss(calc: Calculator) -> Pb1Loss | None:
    base = calc.value(*calc.variant.base)
    return Pb1Loss(base=base) if _negative(base) else None


# Knjigovodstveni rezultat = Klasa 6 (D3) - Klasa 5 (C3); Poreski rezultat = Poreska osnovica.
RESULT_CLASS_6 = ("poreski-bilans", "D3")
RESULT_CLASS_5 = ("poreski-bilans", "C3")


def _result(value: float) -> Pb1Result:
    value = round(value, 2) + 0.0  # + 0.0: no "-0.0"
    return Pb1Result(value=value, status="profit" if value > 0 else "loss" if value < 0 else "zero")


def _results(calc: Calculator) -> Pb1Results:
    def number(tab: str, address: str) -> float:
        return result_value(calc.value(tab, address)) or 0.0

    return Pb1Results(
        accounting=_result(number(*RESULT_CLASS_6) - number(*RESULT_CLASS_5)),
        tax=_result(number(*calc.variant.base)),
    )


def _calculator(form: Pb1Form, edits: dict[str, TabEdits]) -> Calculator:
    """Evaluates the formulas of this company's form. Inputs: form cells as shown (edits
    included); helper cells outside the form from the file for the file's company, else empty;
    a tax with a negative tax base is 0 (LOSS_RULES)."""
    calc: Calculator

    def input_value(tab: str, address: str) -> CellValue:
        if (tab, address) in variant.loss_rules and _loss_zeroed(calc, tab, address):
            return 0.0
        column, row = split_address(address)
        sheet = form.pb1.sheets.get(tab)
        cell = sheet.rows.get(row, {}).get(column) if sheet and column in sheet.spec.columns else None
        if cell is not None:
            # A cell that is not part of the form (e.g. a section row's amount) is empty.
            return None if cell.dropped else _cell_view(form, tab, row, column, cell, edits[tab])[0]
        return form.pb1.raw.get(tab, {}).get(address) if form.has_values else None

    variant = variant_of(form.pb1)
    calc = Calculator(input_value, variant.formulas)
    calc.variant = variant  # the form's loss rules and tax base (_loss_zeroed, _loss, _results)
    return calc


def _computed_values(form: Pb1Form, calc: Calculator) -> list[Pb1ComputedCell]:
    cells = set(computed_cells(form.pb1).get(form.tab, set()))
    cells |= {
        (split_address(a)[1], split_address(a)[0])
        for (t, a) in calc.variant.loss_rules if t == form.tab and _loss_zeroed(calc, t, a)
    }
    computed = [
        Pb1ComputedCell(row=row, column=column, value=result_value(calc.value(form.tab, f"{column}{row}")))
        for row, column in sorted(cells)
    ]
    if form.sheet.spec.head_result:
        # The extra head row (Saldo Klasa 6 - 5) follows Klasa 5 / Klasa 6 at once.
        computed.append(Pb1ComputedCell(
            row=form.sheet.head_end + 1, column=form.sheet.spec.head_result[3], value=_head_result_value(form, calc),
        ))
    return computed


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
            if cell.dropped or cell.hidden:
                out[key] = Pb1CellOut()  # not part of the form / not shown here: empty, read-only
                continue
            formula = (row_number, key) in computed or _loss_zeroed(calc, form.tab, f"{key}{row_number}")
            if formula:
                # Computed with the workbook's formula from the current values; read-only.
                value, kind, edit = result_value(calc.value(form.tab, f"{key}{row_number}")), None, None
            else:
                value, kind, edit = _cell_view(form, form.tab, row_number, key, cell, edits[form.tab])
                is_comment = key == comment_column and row_number > sheet.head_end
                if kind is None and not is_comment and (row_number, key) != sheet.spec.company_name_cell:
                    value = shift_years(value, delta)
            is_overrun = key == sheet.spec.overrun_column and row_number > sheet.head_end
            minus = is_overrun and form.tab == "poreski-bilans" and row_number in calc.variant.green_rows
            positive = is_overrun and _is_number(value) and float(value) > 0
            subtotal = is_overrun and form.tab == "poreski-bilans" and row_number in calc.variant.subtotal_rows
            out[key] = Pb1CellOut(
                value=value,
                format=_shown_format(cell),
                # Numbers in normal weight where the tab says so (Poreski bilans); texts keep bold.
                # A section subtotal is bold, to stand apart from the lines (user, 2026-11-25).
                bold=subtotal or (
                    cell.bold
                    and not (sheet.spec.plain_numbers and (cell.amount or _is_number(value)))
                    and (row_number, key) not in sheet.spec.plain_cells
                ),
                amount=cell.amount,
                editable=kind is not None and not form.locked,
                number=kind in ("amount", "number", "months"),
                edited=edit is not None,
                fill=cell.fill,
                tone=dict(sheet.spec.cell_tones).get((row_number, key)),
                formula=formula,
                red=positive and not minus,
                minus=minus,
                subtotal=subtotal,
                green=(positive and minus) or (subtotal and _is_number(value) and float(value) < 0),
            )
        description = cells.get("B")
        shaded = row_number > sheet.head_end and bool(
            description and description.bold and str(description.value or "").strip()
        )
        rows.append(Pb1RowOut(row=row_number, cells=out, shaded=shaded))
    start = sheet.summary_start
    head = [r for r in rows if r.row <= sheet.head_end]
    if sheet.spec.head_result and len(head) >= 2:
        head.append(_head_result_row(form, calc, head))
    summary = [r for r in rows if start is not None and r.row >= start]
    rows = [r for r in rows if r.row > sheet.head_end and (start is None or r.row < start)]

    def column_out(k: str) -> Pb1Column:
        return Pb1Column(
            key=k, header=shift_years(sheet.headers.get(k), delta), width=sheet.column_widths[k],
            wrap=k in sheet.spec.wrap_columns, amount=k in sheet.spec.value_columns,
            narrow=k in sheet.spec.narrow_columns, dash_empty=k in sheet.spec.konto_columns,
            overrun=k == sheet.spec.overrun_column,
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
        head_figures=_head_figures(head, head_columns or columns, sheet.spec),
        comment_column=comment_column, loss=_loss(calc), results=_results(calc),
        report=form.report, preliminary_done=form.state.preliminary_done, gfi_done=form.state.gfi_done,
        final_created=form.state.final_created, final_done=form.state.final_done,
        submitted_at=form.state.submitted_at, locked=form.locked,
    )


def _head_result_row(form: Pb1Form, calc: Calculator, head: list[Pb1RowOut]) -> Pb1RowOut:
    """The extra head row (spec.head_result): a label under the first class label (fill of the
    label row above) and the computed value under the second (its own fill); read-only."""
    label, address, label_column, value_column, value_fill = form.sheet.spec.head_result
    labels, values = head[-2].cells, head[-1].cells
    value_cell = values.get(value_column) or Pb1CellOut()
    value = _head_result_value(form, calc)
    return Pb1RowOut(
        row=form.sheet.head_end + 1,
        cells={
            label_column: Pb1CellOut(value=label, fill=(labels.get(label_column) or Pb1CellOut()).fill),
            value_column: Pb1CellOut(
                value=value, format=value_cell.format, amount=True, formula=True, fill=value_fill,
                # The balance (user, 2026-11-25): a profit green, a loss red with its minus.
                tone="balance",
            ),
        },
    )


def _head_figures(head: list[Pb1RowOut], columns: list[Pb1Column], spec) -> list[Pb1HeadFigure]:
    """The head rows' labelled values: a text with an amount (or number) to its right or right
    below it. The title and company name (the first two columns) are left out. Months in business
    last (user, 2026-11-25: Klasa 5, Klasa 6, Saldo, Meseci poslovanja)."""
    keys = [c.key for c in columns]
    figures: list[Pb1HeadFigure] = []
    for i, row in enumerate(head):
        for j, key in enumerate(keys[2:], start=2):
            cell = row.cells.get(key)
            text = str(cell.value).strip() if cell is not None and isinstance(cell.value, str) else ""
            if not text or cell.amount:
                continue
            candidates = [(row.row, keys[j + 1], row.cells.get(keys[j + 1]))] if j + 1 < len(keys) else []
            if i + 1 < len(head):
                candidates.append((head[i + 1].row, key, head[i + 1].cells.get(key)))
            for value_row, value_key, value in candidates:
                if value is not None and (value.amount or _is_number(value.value)):
                    figures.append(Pb1HeadFigure(label=text, row=value_row, column=value_key))
                    break
    months = spec.months_cell
    return sorted(figures, key=lambda f: months is not None and (f.row, f.column) == tuple(months))


def _head_result_value(form: Pb1Form, calc: Calculator) -> CellValue:
    """The value of the extra head row: a form address, or "A-B" (the difference of two)."""
    address = form.sheet.spec.head_result[1]
    if "-" in address:
        left, right = (calc.value(form.tab, a.strip()) for a in address.split("-", 1))
        num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0  # noqa: E731
        return round(num(left) - num(right), 2)
    return result_value(calc.value(form.tab, address))


def save_pb1_cell(
    year: int, row: int, tab: str, cell_row: int, column: str, value: float | str | None, user: str,
    report: str | None = None,
) -> Pb1CellUpdateResult:
    """Saves one field of a company's PB-1 form in one of its reports (see load_pb1_form): the
    service behind the API, also meant for automated filling. Amounts are saved for the company
    and report, template fields for every company. Saving the value shown before any edit
    removes the edit (in the final report the copied value is kept). Raises Pb1EditError."""
    form = load_pb1_form(year, row, tab, user, report=report)
    if form.locked:
        raise Pb1EditError(
            status.HTTP_409_CONFLICT,
            "Preliminarni izveštaj je gotov i više se ne menja." if form.report == PRELIMINARY
            else "Konačni izveštaj je gotov i zaključan; otključajte ga za izmene." if form.state.final_done
            else "Konačni izveštaj još nije napravljen.",
        )
    cell = form.sheet.rows.get(cell_row, {}).get(column)
    if cell is None:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, f"PB-1 polje {column}{cell_row} ne postoji na tabu {tab}.")
    if (cell_row, column) in computed_cells(form.pb1).get(tab, set()):
        raise Pb1EditError(status.HTTP_409_CONFLICT, f"PB-1 polje {column}{cell_row} se računa formulom.")
    kind = pb1_edit_kind(form.sheet, cell_row, column, cell)
    if kind is None:
        raise Pb1EditError(status.HTTP_409_CONFLICT, f"PB-1 polje {column}{cell_row} je samo za čitanje.")
    edits = _all_edits(form, user)
    if _loss_zeroed(_calculator(form, edits), tab, f"{column}{cell_row}"):
        raise Pb1EditError(status.HTTP_409_CONFLICT, f"PB-1 polje {column}{cell_row} je 0: poreska osnovica je negativna (gubitak).")
    original = _shown_original(cell, form.has_values)
    shared = kind not in ("amount", "months")  # the company's own values
    stored = None
    if not shared and form.report == FINAL:
        # The final report's own copy: its value before any edit is the copied one.
        stored = edits[tab][1].get((cell_row, column))
        original = stored[1] if stored is not None else None
    value_kind = kind
    konto = column in form.sheet.spec.konto_columns
    if konto:
        # Konto: any text or number, kept as typed (user, 2026-11-16); "-" or only spaces is empty.
        value_kind = "text"
        if _is_number(original):
            original = str(int(original)) if float(original).is_integer() else str(original)
    if kind == "months":
        # Monthly advance = tax / months in business: whole months of one year (empty = default).
        if value is not None and (isinstance(value, str) or not float(value).is_integer() or int(value) not in MONTHS_RANGE):
            raise Pb1EditError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Broj meseci poslovanja mora biti ceo broj od 1 do 12.")
        value = int(value) if value is not None else original
    elif value_kind in ("amount", "number"):
        if isinstance(value, str) or (value is not None and not math.isfinite(value)):
            raise Pb1EditError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Vrednost mora biti broj.")
        if value is not None and value_kind == "amount":
            # Amounts are kept with two decimals (user, 2026-11-16), half up as in the editor
            # (round() would give 1000.55 for 1000.555: binary floats).
            value = float(Decimal(repr(float(value))).quantize(CENT, rounding=ROUND_HALF_UP))
        if value is not None and float(value).is_integer():
            value = int(value)
    else:
        if konto and _is_number(value):
            value = str(int(value)) if float(value).is_integer() else str(value)
        if value is not None and not isinstance(value, str):
            raise Pb1EditError(status.HTTP_422_UNPROCESSABLE_CONTENT, "Vrednost mora biti tekst.")
        value = (" ".join(value.split()) or None) if value is not None else None
        if konto and value == "-":
            value = None

    company = None if shared else form.company_key
    key = (year, form.pb1, tab, cell_row, column, company)
    edited = not _same_value(kind, value, original)
    report_of = {} if shared else {"report": form.report}
    try:
        if edited or stored is not None:
            # A final report value stays stored (it is the report's copy), also when changed back.
            form.store.save_edit(*key, value, original, user, **report_of)
        else:
            form.store.delete_edit(*key, **report_of)
    except Pb1StoreError as exc:
        raise Pb1EditError(status.HTTP_404_NOT_FOUND, str(exc)) from None
    logger.info(
        "PB-1 %s %s%d %s by '%s' (%s)", tab, column, cell_row, "edited" if edited else "reverted", user,
        "all companies" if shared else f"company row {row}, {form.report} report",
    )
    logger.debug("PB-1 %s %s%d new value: %r", tab, column, cell_row, value)
    calc = _calculator(form, _all_edits(form))
    return Pb1CellUpdateResult(
        row=cell_row, column=column, value=value, edited=edited, shared=shared,
        computed=_computed_values(form, calc), loss=_loss(calc), results=_results(calc),
    )


@router.get("/pb1", response_model_exclude_defaults=True)
@router.get("/pb1/{tab}", response_model_exclude_defaults=True)
def get_pb1(
    year: int, row: int, tab: str = DEFAULT_TAB, report: str | None = None, username: str = Depends(require_user)
) -> Pb1Table:
    """One tab of the company's PB-1 form (default: Poreski bilans) in one of its reports
    (default: see load_pb1_form), with the edits applied."""
    try:
        form = load_pb1_form(year, row, tab, username, report=report)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    table = build_pb1_table(form)
    logger.info(
        "PB-1 %s %s for '%s' (row %d, %s): %s, %d entered", form.report, tab, form.company.name, row, year,
        "values" if form.has_values else "empty template", table.entered,
    )
    return table


@router.put("/pb1/{tab}/cells/{column}/{cell_row}")
def update_pb1_cell(
    year: int, row: int, tab: str, column: str, cell_row: int, update: Pb1CellUpdate,
    report: str | None = None, username: str = Depends(require_user),
) -> Pb1CellUpdateResult:
    """Saves one field of the company's PB-1 form (see save_pb1_cell)."""
    try:
        return save_pb1_cell(year, row, tab, cell_row, column, update.value, username, report=report)
    except Pb1EditError as exc:
        if exc.status_code < 500:
            logger.warning("Rejected PB-1 edit %s %s%d by '%s': %s", tab, column, cell_row, username, exc)
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get("/pb1-pdf")
def get_pb1_pdf(
    year: int, row: int, inline: bool = False, report: str | None = None, username: str = Depends(require_user)
) -> Response:
    """The company's PB-1 form as a PDF: the three tabs with their current values (edits,
    formulas; no comments). `inline`: shown in the browser ("Generate PDF report" opens it in a new
    tab) instead of downloaded."""
    tables = []
    try:
        for spec in PB1_TABS:
            form = load_pb1_form(year, row, spec.key, username, report=report)
            tables.append(build_pb1_table(form))
    except Pb1EditError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND and spec.key != DEFAULT_TAB and tables:
            logger.warning("PB-1 PDF: tab %s left out: %s", spec.key, exc)
        else:
            raise HTTPException(exc.status_code, str(exc)) from None
    company = tables[0].company
    try:
        pdf = build_pb1_pdf(tables, company.name, company.pib, year, tables[0].report)
    except Exception:
        logger.exception("Failed to build the PB-1 PDF for row %d (%s)", row, year)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "PDF nije mogao da se napravi.") from None
    kind = "preliminarni" if tables[0].report == PRELIMINARY else "konačni"  # file name shown to the user
    name = re.sub(r'[\/:*?"<>|]+', " ", f"PB-1 {year} {company.name} {kind}").strip() + ".pdf"
    disposition = "inline" if inline else "attachment"
    logger.info("PB-1 PDF for '%s' (row %d, %s) by '%s': %d bytes", company.name, row, year, username, len(pdf))
    return Response(
        pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}"},
    )


# --- the two reports: preliminary done, final created (user, 2026-11-17) --------------------

class Pb1ReportStateOut(BaseModel):
    preliminary_done: bool
    gfi_done: bool = False
    final_created: bool
    final_done: bool = False
    submitted_at: datetime | None = None


class Pb1ReportEventOut(BaseModel):
    event: str  # preliminary_done, final_created, final_done, final_unlocked, submitted, submission_withdrawn
    at: datetime
    by: str


# Home status columns the reports set (0 / 1): "Preliminarni" when the preliminary report is
# done; "PB-1, PB-2" when the final report is done (back to 0 when it is unlocked).
PRELIMINARY_FIELD = "preliminarni"
GFI_FIELD = "gfi_uradjen"  # Home "GFI uradjen": 1 while GFI is marked as done
FINAL_FIELD = "pb"
SUBMITTED_FIELD = "pb_predat"  # Home "PB-1, PB-2 Predat": 1 while the report is submitted


def _set_home_status(year: int, row: int, field: str, value: int, user: str) -> None:
    """Sets one of the company's Home status columns (as an edit on Home would, with history)."""
    gfi = get_gfi_store()
    source, edits = gfi.load(year)
    column = next((c for c, f in source.fields.items() if f == field), None)
    src = source.rows.get(row, {}).get(column) if column else None
    if src is None:
        logger.warning("No %s cell for row %d (%s); Home not updated", field, row, year)
        return
    current = edits[(row, column)][0] if (row, column) in edits else src.value
    if _is_number(current) and float(current) == value:
        return
    gfi.save(year, row, column, "number", value, src.value, user)
    logger.info("Home %s of row %d (%s) set to %d by '%s' (PB-1 report)", field, row, year, value, user)


def _state_out(state: ReportState) -> Pb1ReportStateOut:
    return Pb1ReportStateOut(
        preliminary_done=state.preliminary_done, gfi_done=state.gfi_done, final_created=state.final_created,
        final_done=state.final_done,
        submitted_at=state.submitted_at,
    )


def mark_preliminary_done(year: int, row: int, user: str) -> Pb1ReportStateOut:
    """Marks the company's preliminary PB-1 report as done: locked from then on (still viewable),
    the final report can be created, and Home "Preliminarni" becomes 1. Raises Pb1EditError."""
    form = load_pb1_form(year, row, DEFAULT_TAB, user, report=PRELIMINARY)
    if not form.state.preliminary_done:
        try:
            form.store.mark_preliminary_done(year, form.company_key, user)
        except Pb1StoreError as exc:
            raise Pb1EditError(status.HTTP_404_NOT_FOUND, str(exc)) from None
        logger.info("PB-1 preliminary report of '%s' (row %d, %s) marked as done by '%s'", form.company.name, row, year, user)
        _set_home_status(year, row, PRELIMINARY_FIELD, 1, user)
    return _state_out(form.store.report_state(year, form.company_key))


def set_gfi_done(year: int, row: int, done: bool, user: str) -> Pb1ReportStateOut:
    """Marks the company's GFI as done (after the preliminary report; Home "GFI uradjen" = 1; the
    final report can then be created) or reopens it (only before the final report exists; Home
    "GFI uradjen" = 0). Raises Pb1EditError."""
    form = load_pb1_form(year, row, DEFAULT_TAB, user, report=PRELIMINARY)
    if not form.state.preliminary_done:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Preliminarni izveštaj još nije označen kao gotov.")
    if form.state.final_created:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Konačni izveštaj je već napravljen; GFI se više ne otvara.")
    if form.state.gfi_done != done:
        try:
            form.store.set_gfi_done(year, form.company_key, done, user)
        except Pb1StoreError as exc:
            raise Pb1EditError(status.HTTP_409_CONFLICT, str(exc)) from None
        logger.info(
            "GFI of '%s' (row %d, %s) %s by '%s'", form.company.name, row, year, "marked as done" if done else "reopened", user
        )
        _set_home_status(year, row, GFI_FIELD, 1 if done else 0, user)
    return _state_out(form.store.report_state(year, form.company_key))


def set_final_done(year: int, row: int, done: bool, user: str) -> Pb1ReportStateOut:
    """Marks the company's final PB-1 report as done (locked; Home "PB-1, PB-2" = 1) or unlocks it
    again for changes (Home "PB-1, PB-2" = 0): the inverse operation. Raises Pb1EditError."""
    form = load_pb1_form(year, row, DEFAULT_TAB, user, report=FINAL)
    if not form.state.final_created:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Konačni izveštaj još nije napravljen.")
    if form.state.submitted_at is not None:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Izveštaj je predat; prvo povucite predaju.")
    if form.state.final_done != done:
        try:
            form.store.set_final_done(year, form.company_key, done, user)
        except Pb1StoreError as exc:
            raise Pb1EditError(status.HTTP_409_CONFLICT, str(exc)) from None
        logger.info(
            "PB-1 final report of '%s' (row %d, %s) %s by '%s'", form.company.name, row, year,
            "marked as done" if done else "unlocked", user,
        )
        _set_home_status(year, row, FINAL_FIELD, 1 if done else 0, user)
    return _state_out(form.store.report_state(year, form.company_key))


def _preliminary_values(year: int, row: int, user: str) -> dict[tuple[str, int, str], CellValue]:
    """Every value of the company's own in the preliminary report, as shown: (tab, row, col) ->
    value; formulas (computed) and empty fields left out."""
    values: dict[tuple[str, int, str], CellValue] = {}
    for spec in PB1_TABS:
        try:
            form = load_pb1_form(year, row, spec.key, user, report=PRELIMINARY)
        except Pb1EditError as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND and spec.key != DEFAULT_TAB:
                continue  # a form without this tab
            raise
        edits = _all_edits(form, user)
        computed = computed_cells(form.pb1).get(spec.key, set())
        for cell_row, cells in form.sheet.rows.items():
            for column, cell in cells.items():
                if cell.dropped or cell.hidden or (cell_row, column) in computed:
                    continue
                value, kind, _ = _cell_view(form, spec.key, cell_row, column, cell, edits[spec.key])
                if kind not in ("amount", "months"):
                    continue
                if kind == "amount" and not _is_number(value):
                    continue  # an empty amount (also " " or an error in the file)
                if value is None:
                    continue
                values[(spec.key, cell_row, column)] = value
    return values


def create_final_report(year: int, row: int, user: str) -> Pb1ReportStateOut:
    """Creates the company's final PB-1 report from its preliminary one: every value is copied
    into the database for the final report, which is separate from then on. Raises Pb1EditError."""
    form = load_pb1_form(year, row, DEFAULT_TAB, user, report=PRELIMINARY)
    if not form.state.preliminary_done:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Preliminarni izveštaj još nije označen kao gotov.")
    if form.state.final_created:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Konačni izveštaj je već napravljen.")
    if not form.state.gfi_done:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "GFI još nije označen kao gotov.")
    values = _preliminary_values(year, row, user)
    try:
        copied = form.store.create_final(year, form.company_key, values, user)
    except Pb1StoreError as exc:
        raise Pb1EditError(status.HTTP_409_CONFLICT, str(exc)) from None
    logger.info("PB-1 final report of '%s' (row %d, %s) created by '%s': %d values copied", form.company.name, row, year, user, copied)
    return _state_out(form.store.report_state(year, form.company_key))


@router.post("/pb1-report/preliminary-done")
def post_preliminary_done(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return mark_preliminary_done(year, row, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/pb1-report/final")
def post_final_report(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return create_final_report(year, row, username)
    except Pb1EditError as exc:
        if exc.status_code < 500:
            logger.warning("Rejected creating the final PB-1 report of row %d (%s) by '%s': %s", row, year, username, exc)
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/pb1-report/final-done")
def post_final_done(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return set_final_done(year, row, True, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/pb1-report/final-unlock")
def post_final_unlock(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return set_final_done(year, row, False, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


def set_submitted(year: int, row: int, submitted: bool, user: str) -> Pb1ReportStateOut:
    """Marks the company's PB-1 report as submitted now (only a final report marked as done; Home
    "PB-1, PB-2 Predat" = 1; unlocking is not possible while submitted) or withdraws the
    submission (Home "PB-1, PB-2 Predat" = 0). Raises Pb1EditError."""
    form = load_pb1_form(year, row, DEFAULT_TAB, user, report=FINAL)
    if submitted and not form.state.final_done:
        raise Pb1EditError(status.HTTP_409_CONFLICT, "Predaje se samo konačni izveštaj označen kao gotov.")
    if (form.state.submitted_at is not None) != submitted:
        try:
            form.store.set_submitted(year, form.company_key, submitted, user)
        except Pb1StoreError as exc:
            raise Pb1EditError(status.HTTP_409_CONFLICT, str(exc)) from None
        logger.info(
            "PB-1 report of '%s' (row %d, %s) %s by '%s'", form.company.name, row, year,
            "submitted" if submitted else "submission withdrawn", user,
        )
        _set_home_status(year, row, SUBMITTED_FIELD, 1 if submitted else 0, user)
    return _state_out(form.store.report_state(year, form.company_key))


def report_history(year: int, row: int, user: str) -> list[Pb1ReportEventOut]:
    """The steps of the company's PB-1 reports with date, time and user, newest first."""
    form = load_pb1_form(year, row, DEFAULT_TAB, user, report=PRELIMINARY)
    events = form.store.report_history(year, form.company_key)
    return [Pb1ReportEventOut(event=e.event, at=e.at, by=e.by) for e in reversed(events)]


@router.post("/pb1-report/submitted")
def post_submitted(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return set_submitted(year, row, True, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/pb1-report/submission-withdrawn")
def post_submission_withdrawn(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return set_submitted(year, row, False, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get("/pb1-report/history")
def get_report_history(year: int, row: int, username: str = Depends(require_user)) -> list[Pb1ReportEventOut]:
    try:
        return report_history(year, row, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/pb1-report/gfi-done")
def post_gfi_done(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return set_gfi_done(year, row, True, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/pb1-report/gfi-reopen")
def post_gfi_reopen(year: int, row: int, username: str = Depends(require_user)) -> Pb1ReportStateOut:
    try:
        return set_gfi_done(year, row, False, username)
    except Pb1EditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None

