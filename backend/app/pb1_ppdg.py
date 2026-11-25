"""The PB-1 form of PPDG-1S companies (user, 2026-11-25).

Companies are of two types (company_year.form_type): "pdp" files the PB-1 form of the workbook
(every company until then) and "ppdg" files PPDG-1S, whose tax balance is Obrazac PB2 (the tax
balance of self-employed persons' income tax). There is no workbook for PB2: its Poreski bilans
is built here from the lines of the ePorezi form (app/pb1_ppdg_lines.py) on the frame of the PDP
tab (the same columns, head rows with Klasa 5 / Klasa 6 and months, the closing rows), and every
rule of the PDP tab is carried over (user: "very little differs"):

- Prekoracenje (E) = Ostvareni (D) - Priznati (C), never negative, in every line, except the
  lines whose Prekoracenje is a sum: line 51 Oporeziva dobit (the tax base sum), line 52 Gubitak
  (the loss sum) and line 54 (a fixed 0,00), as PDP lines 59, 60, 62.
- Poreska osnovica = the formula of line 51 applied to the overruns:
  1-3+4-5+6 do 18-19-20+21-22+23 do 28-29+30-31+32-33+34-35+36+37+38-39 do 43+50.
  Line 52 = 2+3-4+5-6 do 18+19+20-21+22-23 do 28+29-30+31-32+33-34+35-36-37-38+39 do 43-50
  (line 2 plus the line 51 lines without line 1, every sign inverted).
- Colours from the sign in line 51: a "+" line's overrun red, a "-" line's green; line 2 green
  (as PDP line 3: "+" in the loss formula only).
- Section subtotals in the Roman-numeral headings with a line of that formula (I, II, III, IV,
  VII), signed.
- Limits: Priznati = rate x Klasa 6 in lines 23 (5 %), 25 culture (5 %), 26 membership fees
  (0,1 %), 27 entertainment (0,5 %); line 24 (humanitarian aid in an emergency) has none (user).
- Porez (10%) (income tax; PDP 15 %) and Mesecna akontacija = porez / months.
- Tabs 2 and 3 are the PDP tabs; their references into Poreski bilans are moved to the matching
  PB2 lines (e.g. entertainment PDP line 25 -> PB2 line 27), and their texts name the income tax
  at 10 % ("Porez na dohodak za godinu (10%x8)", user 2026-11-25).

The PB2 rows are numbered from 105 on, and its closing rows 185-188, so they never meet the PDP
rows (1-88): the template fields shared by every company of a year (Konto) and the global
comments are stored per row and stay apart. The head rows (1-3: Klasa 5 / 6, months) are the
same cells as in PDP.
"""

import re
from dataclasses import dataclass, replace

from app.pb1_formulas import FORMULAS
from app.pb1_ppdg_lines import PPDG_LINES
from app.pb1_workbook import DEFAULT_TAB, Pb1Cell, Pb1Sheet, Pb1Workbook

PPDG = "ppdg"
FIRST_ROW = 105  # the first PB2 row (a heading); PDP rows end at 88
SUMMARY_SHIFT = 100  # the closing rows: PDP 85-88 -> PB2 185-188

# Line number -> its row; heading rows in order.
LINE_ROWS: dict[int, int] = {}
SECTION_ROWS: dict[int, str] = {}  # row -> heading text
for _index, (_kind, _number, _text) in enumerate(PPDG_LINES):
    if _kind == "line":
        LINE_ROWS[_number] = FIRST_ROW + _index
    else:
        SECTION_ROWS[FIRST_ROW + _index] = _text
LAST_ROW = FIRST_ROW + len(PPDG_LINES) - 1

# The signs of line 51 (Oporeziva dobit): the lines of the tax base.
_PLUS = {1, 4, *range(6, 19), 21, *range(23, 29), 30, 32, 34, 36, 37, 38, 50}
_MINUS = {3, 5, 19, 20, 22, 29, 31, 33, 35, *range(39, 44)}
BASE_SIGNS: dict[int, int] = {**{n: 1 for n in _PLUS}, **{n: -1 for n in _MINUS}}
# Line 52 (Gubitak): line 2 plus the line 51 lines without line 1, signs inverted.
LOSS_SIGNS: dict[int, int] = {2: 1, **{n: -s for n, s in BASE_SIGNS.items() if n != 1}}
SUM_LINE, LOSS_LINE, ZERO_LINE = 51, 52, 54
LIMITS: dict[int, float] = {23: 0.05, 25: 0.05, 26: 0.001, 27: 0.005}
TAX_RATE = 0.10

BASE = f"C{SUMMARY_SHIFT + 86}"  # Poreska osnovica
TAX = f"C{SUMMARY_SHIFT + 87}"  # Porez (10%)
ADVANCE = f"C{SUMMARY_SHIFT + 88}"  # Mesecna akontacija
CLOSING_TEXTS = {
    SUMMARY_SHIFT + 86: "Poreska osnovica (54+60) ≥ 0",
    SUMMARY_SHIFT + 87: f"Porez ({TAX_RATE:.0%})",
}

# Green overruns: the "-" lines of line 51, and line 2.
GREEN_ROWS = frozenset({LINE_ROWS[n] for n, s in BASE_SIGNS.items() if s < 0} | {LINE_ROWS[2]})
OVERRUN_ROWS = tuple(LINE_ROWS[n] for n in sorted(LINE_ROWS) if n not in (SUM_LINE, LOSS_LINE, ZERO_LINE))


def _signed(signs: dict[int, int]) -> str:
    return "=" + "".join(f"{'+' if s > 0 else '-'}E{LINE_ROWS[n]}" for n, s in sorted(signs.items()))


def _subtotals() -> dict[int, dict[int, int]]:
    """Roman-numeral heading row -> its lines of line 51 with their signs (only headings that
    have some; "A." and "B" are not Roman numerals)."""
    out: dict[int, dict[int, int]] = {}
    heading = None
    for index, (kind, number, text) in enumerate(PPDG_LINES):
        if kind == "section":
            heading = FIRST_ROW + index if re.match(r"^[IVX]+ ", text) else None
        elif heading is not None and number in BASE_SIGNS:
            out.setdefault(heading, {})[number] = BASE_SIGNS[number]
    return out


SUBTOTALS = _subtotals()


# PDP row -> PB2 row for the references of tabs 2 and 3 into Poreski bilans (the matching lines).
_PDP_TO_PPDG_ROW = {
    14: LINE_ROWS[7],  # Troskovi koji nisu dokumentovani (PDP 6 -> PB2 7)
    18: LINE_ROWS[11],  # Kamate zbog neblagovremeno placenih poreza (PDP 10 -> PB2 11)
    25: LINE_ROWS[18],  # Otpremnine ... neisplacene (PDP 17 -> PB2 18)
    33: LINE_ROWS[27],  # Reprezentacija (PDP 25 -> PB2 27)
    37: LINE_ROWS[30],  # Porezi ... koji nisu placeni (PDP 29 -> PB2 30)
    76: LINE_ROWS[53],  # Gubitak iz prethodnih godina (PDP 61 -> PB2 53)
    **{r: r + SUMMARY_SHIFT for r in (85, 86, 87, 88)},
}
_REF = re.compile(r"'Poreski bilans'!([A-Z]+)(\d+)")


def _moved(formula: str) -> str:
    return _REF.sub(lambda m: f"'Poreski bilans'!{m.group(1)}{_PDP_TO_PPDG_ROW.get(int(m.group(2)), int(m.group(2)))}", formula)


def _formulas() -> dict[str, dict[str, str]]:
    balance: dict[str, str] = {}
    for row in OVERRUN_ROWS:
        balance[f"E{row}"] = f"=IF(D{row}-C{row}>0,D{row}-C{row},0)"
    balance[BASE] = _signed(BASE_SIGNS)
    balance[f"E{LINE_ROWS[SUM_LINE]}"] = balance[BASE]
    balance[f"E{LINE_ROWS[LOSS_LINE]}"] = _signed(LOSS_SIGNS)
    balance[f"E{LINE_ROWS[ZERO_LINE]}"] = "=0"
    for heading, signs in SUBTOTALS.items():
        balance[f"E{heading}"] = _signed(signs)
    for number, rate in LIMITS.items():
        balance[f"C{LINE_ROWS[number]}"] = f"=D3*{rate}"
    balance[TAX] = f"=IF({BASE}>0,{BASE}*{TAX_RATE},0)"
    balance[ADVANCE] = f"={TAX}/D1"
    out = {DEFAULT_TAB: balance}
    for tab, formulas in FORMULAS.items():
        if tab != DEFAULT_TAB:
            out[tab] = {address: _moved(formula) for address, formula in formulas.items()}
    # The income tax of tabs 2 and 3 stays typed in, editable as in PDP (user, 2026-11-25: only
    # its texts say 10 %; a computed tax there was tried and taken back the same day).
    return out


PPDG_FORMULAS = _formulas()


def _sheet(pdp: Pb1Sheet) -> Pb1Sheet:
    """The PB2 Poreski bilans on the frame of the PDP tab."""
    line = pdp.rows.get(7, {})  # a PDP form line (line 1): its cells' formats
    amount_format = next((c.number_format for k, c in line.items() if c.amount), "General")
    columns = pdp.spec.columns
    rows: dict[int, dict[str, Pb1Cell]] = {r: cells for r, cells in pdp.rows.items() if r <= pdp.head_end}
    dropped: set[tuple[int, str]] = {(r, k) for (r, k) in pdp.dropped if r <= pdp.head_end}
    empty = Pb1Cell(value=None, number_format="General", bold=False)
    gone = Pb1Cell(value=None, number_format="General", bold=False, dropped=True)
    value_columns = pdp.spec.value_columns
    for index, (kind, number, text) in enumerate(PPDG_LINES):
        row = FIRST_ROW + index
        cells: dict[str, Pb1Cell] = {}
        for key in columns:
            if key == "A":
                cells[key] = Pb1Cell(value=number, number_format="General", bold=False) if kind == "line" else empty
            elif key == "B":
                cells[key] = Pb1Cell(value=text, number_format="General", bold=kind == "section")
            elif key == pdp.spec.comment_column:
                cells[key] = empty
            elif kind == "line":
                amount = key in value_columns
                cells[key] = Pb1Cell(value=None, number_format=amount_format if amount else "General", bold=False, amount=amount)
            elif key == "E" and row in SUBTOTALS:
                cells[key] = Pb1Cell(value=None, number_format=amount_format, bold=False, amount=True)
            else:
                cells[key] = gone
                dropped.add((row, key))
        rows[row] = cells
    start = pdp.summary_start or 85
    for r, cells in pdp.rows.items():
        if r < start:
            continue
        moved = dict(cells)
        if r + SUMMARY_SHIFT in CLOSING_TEXTS and "B" in moved:
            moved["B"] = replace(moved["B"], value=CLOSING_TEXTS[r + SUMMARY_SHIFT])
        rows[r + SUMMARY_SHIFT] = moved
        dropped |= {(r + SUMMARY_SHIFT, k) for (row, k) in pdp.dropped if row == r}
    spec = replace(
        pdp.spec,
        section_shown=frozenset((r, "E") for r in SUBTOTALS),
        section_hidden=frozenset(), dropped_cells=frozenset(), dropped_rows=(), amount_fixes=(), head_result=None,
    )
    return Pb1Sheet(
        spec=spec, name=pdp.name, headers=pdp.headers, column_widths=pdp.column_widths, rows=rows,
        summary_start=start + SUMMARY_SHIFT, head_end=pdp.head_end, dropped=frozenset(dropped),
    )


# Tabs 2 and 3 speak of the income tax at 10 % (user, 2026-11-25): "porez(a) na dobit" ->
# "porez(a) na dohodak", "15%" -> "10%" in their texts ("Dobit perioda", "Neto dobit" stay: they
# are the profit, not the tax).
_TAX_NAME = re.compile(r"\b([Pp]orez[a]?) na dobit\b")


def _income_tax_text(value):
    if not isinstance(value, str):
        return value
    return _TAX_NAME.sub(r"\1 na dohodak", value).replace("15%", f"{TAX_RATE:.0%}")


def _income_tax_texts(sheet: Pb1Sheet) -> Pb1Sheet:
    rows = {
        r: {k: replace(c, value=_income_tax_text(c.value)) if isinstance(c.value, str) else c for k, c in cells.items()}
        for r, cells in sheet.rows.items()
    }
    headers = {k: _income_tax_text(h) for k, h in sheet.headers.items()}
    return replace(sheet, rows=rows, headers=headers)


_cache: dict[int, tuple[Pb1Workbook, Pb1Workbook]] = {}


def ppdg_workbook(pdp: Pb1Workbook) -> Pb1Workbook:
    """The PPDG-1S form of a year: the year's PDP form with its Poreski bilans replaced by PB2."""
    cached = _cache.get(id(pdp))
    if cached is not None and cached[0] is pdp:
        return cached[1]
    sheets = dict(pdp.sheets)
    if DEFAULT_TAB in sheets:
        sheets[DEFAULT_TAB] = _sheet(sheets[DEFAULT_TAB])
    for tab, sheet in sheets.items():
        if tab != DEFAULT_TAB:
            sheets[tab] = _income_tax_texts(sheet)
    form = replace(pdp, sheets=sheets, variant=PPDG)
    _cache[id(pdp)] = (pdp, form)
    return form


@dataclass(frozen=True)
class FormVariant:
    """What differs between the two forms: formulas, the tax base and loss rules, colours."""

    key: str
    formulas: dict[str, dict[str, str]]
    loss_rules: dict[tuple[str, str], tuple[str, str]]
    base: tuple[str, str]  # the tax base (Poreska osnovica)
    green_rows: frozenset[int]  # Prekoracenje rows whose overrun is green
    subtotal_rows: frozenset[int]  # section headings with a subtotal in Prekoracenje
    verified: bool  # its formulas are checked against a workbook's stored results


def ppdg_variant(pdp_loss_rules: dict[tuple[str, str], tuple[str, str]]) -> FormVariant:
    loss_rules = {key: value for key, value in pdp_loss_rules.items() if key[0] != DEFAULT_TAB}
    loss_rules[(DEFAULT_TAB, TAX)] = (DEFAULT_TAB, BASE)
    return FormVariant(
        key=PPDG, formulas=PPDG_FORMULAS, loss_rules=loss_rules, base=(DEFAULT_TAB, BASE),
        green_rows=GREEN_ROWS, subtotal_rows=frozenset(SUBTOTALS), verified=False,
    )
