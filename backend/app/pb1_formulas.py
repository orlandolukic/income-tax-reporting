"""Calculations of the PB-1 form: the formulas of the Excel workbook, applied in the app.

The formulas below are those of "2025 PB-1.xls" (extracted from the workbook with Excel from
a read-only copy, 2026-11-11), keyed by tab and cell address. References are Excel cell
addresses ("C8", "'Poreski bilans'!D3"); the app addresses every form row by its Excel row
too, so they map one to one (the "#" line numbers shown in the tables are not used here).

Left out because they are not calculations of the form: the copies of descriptions and of the
company name in Preliminarni rezultat (B1, F5, F7, F8), the check value in the Konto column of
Poreski bilans (G28) and the cells below the form (rows 105, 108).

A formula cell shown in the form is computed from the current values (edits included; amounts
of another company than the file's are empty) and is read-only. Helper cells outside the form
(columns H..Q) are inputs from the file for the file's company and empty for every other one;
their own formulas are evaluated the same way. The formulas are checked against Excel's stored
results for the file's company whenever a workbook is loaded (verify_formulas); if any result
differs, e.g. because a year's template changed, the formulas are not used for that workbook.

Supported: numbers, cell and range references (also to another sheet), + - * /, unary + -,
comparisons, IF and SUM. Errors (#DIV/0!) propagate like in Excel. Text and empty cells count
as 0 in arithmetic.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.logging_config import get_logger

logger = get_logger(__name__)

# Excel sheet name -> tab key (references to another sheet use the sheet's name).
SHEET_TABS = {
    "poreski bilans": "poreski-bilans",
    "uporedo": "uporedo",
    "preliminarni rezultat": "preliminarni",
}

FORMULAS: dict[str, dict[str, str]] = {
    "poreski-bilans": {
        "F1": '=+E1*2',
        "J1": '=+C3/J2*100',
        "K1": '=+D3/K2*100',
        "C3": '=E3+J15',
        "D3": '=F3+J19',
        "C5": '=IF(D3<C3,D3-C3,0)',
        "C6": '=D3',
        "L6": '=+M3',
        "C7": '=IF(D3>C3,D3-C3,0)',
        "L7": '=+M3-L3',
        "M7": '=+C7/L7*100',
        "J15": '=SUM(J5:J14)',
        "L15": '=+D14*15/100',
        "K25": '=+I25+J25',
        "K26": '=+I26+J26',
        "K28": '=+I28+J28',
        "D29": '=+K29',
        "I29": '=+I25+I28+I26+I27',
        "J29": '=+J25+J28+J26+J27',
        "K29": '=+K25+K28+K26+K27',
        "N29": '=+M28-M29',
        "D30": '=D3*F30',
        "E30": '=IF(C30>D30,C30-D30,0)',
        "D31": '=D3*F31',
        "E31": '=IF(C31>D31,C31-D31,0)',
        "D32": '=D3*F32',
        "E32": '=IF(C32>D32,C32-D32,0)',
        "I32": '=D28-D29',
        "D33": '=D3*F33',
        "E33": '=IF(C33>D33,C33-D33,0)',
        "C70": '=+C67',
        "C74": '=C5+C7+D12+D14+D15+D16+D17+D18+D19+D20+D21+D22+D23+D24+D25-D29+E30+E31+E32+E33+D34+D36+D37+D39+D40+D41+D43+D47+D48+D49+D50+D51+D52+D53+D54+C70+C72-D11-D15-D22-D26-D27+D28-D35-D38-D42-D44-D45-D55-D56-D57-D58-D59-D60',
        "C77": '=+C74-C76',
        "C86": '=C77+C80',
        "J86": '=+C86/I86*100',
        "M86": '=+C86/L86*100',
        "I87": '=+I86*0.15',
        "J87": '=+C87/I87*100',
        "M87": '=+C87/L87*100',
        "C88": '=C87/D1',
        "I88": '=+I87/12',
        "J88": '=+C88/I88*100',
        "M88": '=+C88/L88*100',
    },
    "uporedo": {
        "C6": "=+'Poreski bilans'!D3",
        "E6": '=+C6/D6',
        "C7": "=+'Poreski bilans'!C3",
        "E7": '=+C7/D7',
        "C8": '=C6-C7',
        "D8": '=D6-D7',
        "E8": '=+C8/D8',
        "C9": "='Preliminarni rezultat'!G11",
        "E9": '=+C9/D9',
        "C10": "='Preliminarni rezultat'!G18",
        "C12": '=C8+C9-C10',
        "D12": '=D8+D9-D10',
        "E12": '=+C12/D12',
        "E13": '=+C13/D13',
        "C15": '=IF(C13-C14>0,C13-C14,0)',
        "D15": '=IF(D13-D14>0,D13-D14,0)',
        "E15": '=+C15/D15',
        "C16": "=+'Preliminarni rezultat'!C17",
        "E16": '=+C16/D16',
        "C17": '=IF(C15>C16,C15-C16,0)',
        "D17": '=IF(D15>D16,D15-D16,0)',
        "C18": '=IF(C15<C16,C16-C15,0)',
        "D18": '=IF(D15<D16,D16-D15,0)',
        "C20": "=C15/'Poreski bilans'!D1",
        "D20": '=+D15/12',
        "E20": '=+C20/D20',
        "C23": '=+C8-C15',
        "D23": '=+D8-D15',
        "E23": '=+C23/D23',
        "C25": '=C18/C20',
        "D25": '=D18/D20',
    },
    "preliminarni": {
        "G3": "='Poreski bilans'!E33",
        "H3": "='Poreski bilans'!L33",
        "I3": '=+G3/H3*100',
        "C5": "=+'Poreski bilans'!D3",
        "G5": "='Poreski bilans'!D18",
        "C6": "=+'Poreski bilans'!C3",
        "G6": "=+'Poreski bilans'!D14",
        "C7": '=C5-C6',
        "G7": "=+'Poreski bilans'!D37",
        "H7": "=+'Poreski bilans'!L7",
        "I7": '=+C7/H7*100',
        "G8": "=+'Poreski bilans'!D25",
        "C9": '=C5-C6',
        "C10": '=G11',
        "C11": '=G18',
        "G11": '=SUM(G3:G10)',
        "C13": '=C9+C10-C11+C8',
        "G13": "='Poreski bilans'!C76",
        "H13": "=+'Poreski bilans'!L86",
        "I13": '=+C13/H13*100',
        "G14": "=-'Poreski bilans'!I32",
        "H14": "=+'Poreski bilans'!L87",
        "I14": '=+C14/H14*100',
        "H15": "=+'Poreski bilans'!L88",
        "I15": '=+C21/H15*100',
        "C16": '=IF(C14-C15>0,C14-C15,0)',
        "C18": '=IF(C16>C17,C16-C17,0)',
        "G18": '=SUM(G13:G17)',
        "H18": '=+H17-H14',
        "I18": '=+C18/H18*100',
        "C19": '=IF(C16<C17,C17-C16,0)',
        "C21": "=C16/'Poreski bilans'!D1",
        "H21": '=+H14/12',
        "I21": '=+C21/H21*100',
        "C22": '=G26',
        "C23": '=G27',
        "C24": '=C7-C14-C22+C23',
        "H24": '=H7-H14-H22+H23',
        "I24": '=+C24/H24*100',
        "C25": '=IF(C8+C16-C22+C23<0,C8+C16-C22+C23,0)',
        "G25": '=SUM(G20:G24)',
        "C26": '=C19/C21',
    },
}


class FormulaError(str):
    """An Excel error value, e.g. "#DIV/0!"; propagates through calculations."""


DIV0 = FormulaError("#DIV/0!")
VALUE_ERROR = FormulaError("#VALUE!")

Value = float | FormulaError | None
CellRef = tuple[str, str]  # (tab, address), e.g. ("poreski-bilans", "C7")

_ADDRESS = re.compile(r"^([A-Z]{1,3})(\d+)$")
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
      | (?P<ref>(?:'(?P<qsheet>[^']+)'|(?P<sheet>[A-Za-z_][\w ]*?))?!?(?P<cell>\$?[A-Z]{1,3}\$?\d+)(?::(?P<end>\$?[A-Z]{1,3}\$?\d+))?)
      | (?P<func>[A-Z]+)\(
      | (?P<op><=|>=|<>|[-+*/(),<>=])
    )""",
    re.VERBOSE,
)


def split_address(address: str) -> tuple[str, int]:
    match = _ADDRESS.match(address.replace("$", ""))
    if not match:
        raise ValueError(f"Not a cell address: {address!r}")
    return match.group(1), int(match.group(2))


def _column_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - ord("A") + 1
    return n


def _column_letters(n: int) -> str:
    letters = ""
    while n:
        n, rest = divmod(n - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def _range(start: str, end: str) -> list[str]:
    (c1, r1), (c2, r2) = split_address(start), split_address(end)
    columns = range(_column_number(c1), _column_number(c2) + 1)
    return [f"{_column_letters(c)}{r}" for r in range(r1, r2 + 1) for c in columns]


@dataclass(frozen=True)
class _Ref:
    cells: tuple[CellRef, ...]  # one cell, or the cells of a range


def _tokens(formula: str, tab: str) -> list[object]:
    text = formula.lstrip("=")
    pos, out = 0, []
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise ValueError(f"Unsupported formula {formula!r} at {text[pos:]!r}")
        pos = match.end()
        if match.group("number"):
            out.append(float(match.group("number")))
        elif match.group("cell"):
            sheet = match.group("qsheet") or match.group("sheet")
            ref_tab = SHEET_TABS.get(sheet.strip().lower()) if sheet else tab
            if sheet and ref_tab is None:
                # "Uporedo 2025 i 2024": the year is part of the sheet's name.
                ref_tab = next((t for name, t in SHEET_TABS.items() if sheet.lower().startswith(name)), None)
            if ref_tab is None:
                raise ValueError(f"Unknown sheet {sheet!r} in {formula!r}")
            start, end = match.group("cell").replace("$", ""), match.group("end")
            addresses = _range(start, end.replace("$", "")) if end else [start]
            out.append(_Ref(tuple((ref_tab, a) for a in addresses)))
        elif match.group("func"):
            out.append(("func", match.group("func")))
        else:
            out.append(match.group("op"))
    return out


class _Parser:
    """Recursive descent over the tokens; returns a closure that evaluates the formula."""

    def __init__(self, tokens: list[object], formula: str):
        self.tokens, self.pos, self.formula = tokens, 0, formula

    def peek(self) -> object:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected: str | None = None) -> object:
        token = self.peek()
        if expected is not None and token != expected:
            raise ValueError(f"Expected {expected!r} in {self.formula!r}")
        self.pos += 1
        return token

    def parse(self) -> Callable[["Calculator"], object]:
        node = self.comparison()
        if self.peek() is not None:
            raise ValueError(f"Unexpected {self.peek()!r} in {self.formula!r}")
        return node

    def comparison(self):
        left = self.additive()
        while self.peek() in ("<", ">", "<=", ">=", "=", "<>"):
            op, right, lhs = self.take(), self.additive(), left
            left = lambda calc, op=op, lhs=lhs, right=right: _compare(op, calc.number(lhs(calc)), calc.number(right(calc)))
        return left

    def additive(self):
        left = self.term()
        while self.peek() in ("+", "-"):
            op, right, lhs = self.take(), self.term(), left
            left = lambda calc, op=op, lhs=lhs, right=right: _arith(op, calc.number(lhs(calc)), calc.number(right(calc)))
        return left

    def term(self):
        left = self.unary()
        while self.peek() in ("*", "/"):
            op, right, lhs = self.take(), self.unary(), left
            left = lambda calc, op=op, lhs=lhs, right=right: _arith(op, calc.number(lhs(calc)), calc.number(right(calc)))
        return left

    def unary(self):
        if self.peek() in ("+", "-"):
            op, operand = self.take(), self.unary()
            if op == "+":
                return operand
            return lambda calc, operand=operand: _arith("-", 0.0, calc.number(operand(calc)))
        return self.primary()

    def primary(self):
        token = self.take()
        if isinstance(token, float):
            return lambda calc, token=token: token
        if isinstance(token, _Ref):
            if len(token.cells) == 1:
                return lambda calc, cell=token.cells[0]: calc.value(*cell)
            return lambda calc, token=token: token  # a range: only inside SUM
        if token == "(":
            node = self.comparison()
            self.take(")")
            return node
        if isinstance(token, tuple) and token[0] == "func":
            args = []
            if self.peek() != ")":
                args.append(self.comparison())
                while self.peek() == ",":
                    self.take()
                    args.append(self.comparison())
            self.take(")")
            return _function(token[1], args, self.formula)
        raise ValueError(f"Unexpected {token!r} in {self.formula!r}")


def _compare(op: str, a: object, b: object) -> object:
    if isinstance(a, FormulaError):
        return a
    if isinstance(b, FormulaError):
        return b
    return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b, "=": a == b, "<>": a != b}[op]


def _arith(op: str, a: object, b: object) -> object:
    if isinstance(a, FormulaError):
        return a
    if isinstance(b, FormulaError):
        return b
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    return DIV0 if b == 0 else a / b


def _function(name: str, args: list, formula: str):
    if name == "IF":
        if len(args) not in (2, 3):
            raise ValueError(f"IF needs 2 or 3 arguments in {formula!r}")
        test, then = args[0], args[1]
        other = args[2] if len(args) == 3 else (lambda calc: False)

        def if_(calc):
            condition = test(calc)
            if isinstance(condition, FormulaError):
                return condition
            return then(calc) if calc.number(condition) != 0 else other(calc)

        return if_
    if name == "SUM":

        def sum_(calc):
            total = 0.0
            for arg in args:
                value = arg(calc)
                cells = value.cells if isinstance(value, _Ref) else None
                for item in [calc.value(*c) for c in cells] if cells is not None else [value]:
                    if isinstance(item, FormulaError):
                        return item
                    if isinstance(item, (int, float)) and not isinstance(item, bool):
                        total += item  # SUM skips text and empty cells
            return total

        return sum_
    raise ValueError(f"Unsupported function {name} in {formula!r}")


_compiled: dict[str, Callable] = {}


def _compile(tab: str, formula: str) -> Callable:
    key = f"{tab}\t{formula}"
    if key not in _compiled:
        _compiled[key] = _Parser(_tokens(formula, tab), formula).parse()
    return _compiled[key]


class Calculator:
    """Evaluates the PB-1 formulas of one company's form. `input_value(tab, address)` gives
    the value of a cell without a formula (current value, edits included)."""

    def __init__(self, input_value: Callable[[str, str], object], formulas: dict[str, dict[str, str]] | None = None):
        self.input_value = input_value
        self.formulas = FORMULAS if formulas is None else formulas
        self._memo: dict[CellRef, object] = {}
        self._active: set[CellRef] = set()

    def is_formula(self, tab: str, address: str) -> bool:
        return address in self.formulas.get(tab, {})

    def value(self, tab: str, address: str) -> object:
        """A cell's value: its formula's result, or its input value."""
        key = (tab, address)
        if key in self._memo:
            return self._memo[key]
        formula = self.formulas.get(tab, {}).get(address)
        if formula is None:
            result = self.input_value(tab, address)
        else:
            if key in self._active:
                raise ValueError(f"Circular reference at {tab}!{address}")
            self._active.add(key)
            try:
                result = _compile(tab, formula)(self)
            finally:
                self._active.discard(key)
            if isinstance(result, bool):
                result = 1.0 if result else 0.0
            elif isinstance(result, int):
                result = float(result)  # a formula that only refers to a cell (=+C67)
        self._memo[key] = result
        return result

    @staticmethod
    def number(value: object) -> object:
        """A value as a number for arithmetic: errors stay errors, text and empty count as 0."""
        if isinstance(value, FormulaError):
            return value
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.startswith("#"):
            return FormulaError(value)  # an Excel error stored in the file
        return 0.0


def result_value(value: object) -> float | None:
    """A formula result as shown in the form: a number, or None for an error (shown as 0)."""
    if isinstance(value, FormulaError) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return float(value)


def verify_formulas(raw: dict[str, dict[str, object]], cells: dict[str, set[str]]) -> list[str]:
    """Formulas whose result, computed from the file's own values, differs from the result Excel
    stored in the file. `cells`: the formula cells to check per tab. Empty list = all match."""
    calc = Calculator(lambda tab, address: raw.get(tab, {}).get(address))
    mismatches = []
    for tab, addresses in cells.items():
        for address in sorted(addresses):
            try:
                computed = calc.value(tab, address)
            except ValueError as exc:
                mismatches.append(f"{tab}!{address}: {exc}")
                continue
            stored = raw.get(tab, {}).get(address)
            if isinstance(stored, str) and stored.startswith("#"):
                ok = isinstance(computed, FormulaError)
            elif isinstance(stored, (int, float)) and not isinstance(stored, bool):
                ok = isinstance(computed, float) and math.isclose(computed, stored, rel_tol=1e-9, abs_tol=0.005)
            else:
                ok = stored is None and computed in (0.0, None)
            if not ok:
                mismatches.append(f"{tab}!{address}: computed {computed!r}, Excel {stored!r}")
    return mismatches
