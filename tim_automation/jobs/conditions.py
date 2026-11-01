"""Conditions on table rows, checked here instead of on the site (e.g. "Pretraga stavki").

A condition has the shape of an advanced filter: {"polje": column, "operator": ..., "vrednost": ..., "do": ...}.
The value may be a list (a reference to all rows of an earlier task): the condition then holds when it holds
for any of the values. Text is compared ignoring case and diacritics, amounts as numbers ("4.764,86"),
dates as dates (DD/MM/YYYY).
"""
import re
from datetime import date

from tim_automation.pages.app_page import normalize

ANY_COLUMN = "*"  # "Bilo koja kolona": the condition holds if it holds for some column
EMPTY, NOT_EMPTY = "Je prazno", "Nije prazno"  # operators without a value
TEXT_ONLY = ("Sadrži", "Ne sadrži", "Počinje sa", "Ne počinje sa", "Završava se na", "Ne završava se na")
NEGATIVE = ("Različito od", "Ne sadrži", "Ne počinje sa", "Ne završava se na", EMPTY)


def number(value) -> float | None:
    """794.16 / "794,16" / "4.764,86" / "1 000" -> float; "" or text -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text:  # the site's format: "." groups thousands, "," is the decimal point
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1 or re.fullmatch(r"-?\d{1,3}\.\d{3}", text):
        text = text.replace(".", "")  # "1.000.000" or "4.764" = thousands
    try:
        return float(text)
    except ValueError:
        return None


def day(value) -> date | None:
    """ "06/10/2026", "6.10.2026", "2026-10-06" -> date."""
    text = str(value).strip().rstrip(".")
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text)
    if m:
        d, mo, y = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if not m:
            return None
        y, mo, d = map(int, m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _compare(kind: str, cell, operator: str, wanted, upto=None) -> bool:
    if kind == "number":
        convert = number
    elif kind == "date":
        convert = day
    else:
        convert = None

    if convert:
        a, b = convert(cell if cell != "" or kind != "number" else 0), convert(wanted)
        if b is None:
            raise ValueError(f"„{wanted}“ nije {'broj' if kind == 'number' else 'datum (DD/MM/YYYY)'}.")
        if a is None:
            return operator == "Različito od"
        if operator == "Između":
            c = convert(upto)
            if c is None:
                raise ValueError(f"Za „Između“ upišite i drugu vrednost (do).")
            return b <= a <= c
        return _order(operator, a, b)

    a, b = normalize(str(cell)), normalize(str(wanted))
    if operator == "Sadrži":
        return b in a
    if operator == "Ne sadrži":
        return b not in a
    if operator == "Počinje sa":
        return a.startswith(b)
    if operator == "Ne počinje sa":
        return not a.startswith(b)
    if operator == "Završava se na":
        return a.endswith(b)
    if operator == "Ne završava se na":
        return not a.endswith(b)
    if operator == "Između":
        return b <= a <= normalize(str(upto))
    return _order(operator, a, b)


def _order(operator: str, a, b) -> bool:
    if operator == "Jednako":
        return a == b
    if operator == "Različito od":
        return a != b
    if operator == "Veće od":
        return a > b
    if operator == "Veće ili jednako":
        return a >= b
    if operator == "Manje od":
        return a < b
    if operator == "Manje ili jednako":
        return a <= b
    raise ValueError(f"Nepoznat operator „{operator}“.")


def _values(value) -> list:
    return value if isinstance(value, list) else [value]


def _blank(value) -> bool:
    return value is None or str(value).strip() == "" or value == []


def guess_kind(*values) -> str:
    """ "number" if every non-empty value is a number, "date" if every one is a date, else "text"."""
    flat = [v for value in values for v in _values(value) if not _blank(v)]
    if flat and all(number(v) is not None for v in flat):
        return "number"
    if flat and all(day(v) is not None for v in flat):
        return "date"
    return "text"


ORDERING = ("Veće od", "Veće ili jednako", "Manje od", "Manje ili jednako", "Između")
KIND_WORDS = {"number": "brojevi", "date": "datumi", "text": "tekst"}


def _same_kinds(lefts: list, rights: list, operator: str) -> None:
    """ "Veće od" / "Manje od" / "Između" on values of different kinds (e.g. amounts from one data set, document numbers
    from another) would compare them as text: say so instead."""
    left, right = guess_kind(lefts), guess_kind(rights)
    if left != right and any(not _blank(v) for v in lefts) and any(not _blank(v) for v in rights):
        show = lambda values: ", ".join(f"„{v}“" for v in values if not _blank(v))[:80]
        raise ValueError(f"„{operator}“ poredi različite vrste podataka: levo su {KIND_WORDS[left]} ({show(lefts)}), "
                         f"desno {KIND_WORDS[right]} ({show(rights)}).")


def compare(left, operator: str, right=None, upto=None, kind: str = "auto") -> bool:
    """One check of a "Uslov" task: left (a value or a list of values from an earlier task), operator,
    right (typed or from a task; a list = any of them) and `upto` for "Između". With a list on either
    side, a positive operator holds if it holds for some pair, a negative one if it holds for all."""
    return explain(left, operator, right, upto, kind)["ok"]


MAX_SHOWN_PAIRS = 10


def explain(left, operator: str, right=None, upto=None, kind: str = "auto") -> dict:
    """compare() with how it was decided: {"ok", "kind" (number / date / text / "" for Je prazno), "pairs" (how many
    left × right pairs were compared), "matched" / "failed" (up to MAX_SHOWN_PAIRS pairs [left, right] that met / did
    not meet the operator), "rule"} (for the run report of a "Uslov")."""
    lefts = _values(left)
    if operator in (EMPTY, NOT_EMPTY):
        empty = all(_blank(v) for v in lefts)
        filled = [v for v in lefts if not _blank(v)]
        return {"ok": empty if operator == EMPTY else not empty, "kind": "", "pairs": len(lefts),
                "matched": [[v, ""] for v in filled[:MAX_SHOWN_PAIRS]], "failed": [],
                "rule": "sve leve vrednosti su prazne" if empty else f"{len(filled)} nepraznih levih vrednosti"}
    rights = [v for v in _values(right) if v is not None]
    if not rights:
        raise ValueError("Upišite vrednost sa kojom se poredi.")
    upto = _values(upto)[0] if _values(upto) else ""
    if operator in TEXT_ONLY:
        kind = "text"
    elif kind in ("", "auto"):
        kind = guess_kind(lefts, rights, upto if operator == "Između" else "")
        if kind == "text" and operator in ORDERING:
            _same_kinds(lefts, rights + ([upto] if operator == "Između" else []), operator)
    pairs = [(a, b) for a in (lefts or [""]) for b in rights]
    hits = [_compare(kind, a, operator, b, upto) for a, b in pairs]
    negative = operator in NEGATIVE
    ok = all(hits) if negative else any(hits)
    matched = [[a, b] for (a, b), hit in zip(pairs, hits) if hit]
    failed = [[a, b] for (a, b), hit in zip(pairs, hits) if not hit]
    rule = ("mora da važi za svaki par" if negative else "dovoljno je da važi za jedan par") if len(pairs) > 1 else ""
    return {"ok": ok, "kind": kind, "pairs": len(pairs), "matched": matched[:MAX_SHOWN_PAIRS],
            "failed": failed[:MAX_SHOWN_PAIRS], "rule": rule}


def matches(row: dict, condition: dict, kinds: dict[str, str]) -> bool:
    """Whether the row meets the condition. kinds: column -> "text" / "number" / "date"."""
    column = condition.get("polje", "")
    operator = condition.get("operator") or "Jednako"
    if operator in ("Je u listi", "Nije u listi"):  # a select field: one of the ticked options
        if column not in row:
            raise LookupError(f"Kolona „{column}“ ne postoji u tabeli. Kolone: {', '.join(row)}.")
        chosen = {normalize(str(v)) for v in condition.get("izbor") or []}
        inside = normalize(str(row[column])) in chosen
        return inside if operator == "Je u listi" else not inside
    negative = operator in ("Različito od", "Ne sadrži", "Ne počinje sa", "Ne završava se na")
    wanted = [v for v in _values(condition.get("vrednost", "")) if v is not None]
    if not wanted:
        return False
    upto = condition.get("do", "")
    upto = _values(upto)[0] if _values(upto) else ""

    if column == ANY_COLUMN:
        cells = [(kinds.get(c, "text"), v) for c, v in row.items()]
        hits = [_compare("text", v, operator, w, upto) for _, v in cells for w in wanted]
        return all(hits) if negative else any(hits)
    if column not in row:
        raise LookupError(f"Kolona „{column}“ ne postoji u tabeli. Kolone: {', '.join(row)}.")
    hits = [_compare(kinds.get(column, "text"), row[column], operator, w, upto) for w in wanted]
    # "Različito od [a, b]" = different from all of them; positive operators = any of them.
    return all(hits) if negative else any(hits)


def describe(condition: dict) -> str:
    value = condition.get("vrednost", "")
    shown = f"[{len(value)} vrednosti]" if isinstance(value, list) else repr(value)
    if condition.get("operator") == "Između":
        shown += f" .. {condition.get('do', '')!r}"
    column = "bilo koja kolona" if condition.get("polje") == ANY_COLUMN else condition.get("polje")
    return f"{column} {condition.get('operator')} {shown}"


def show(value) -> str:
    """A short text for a value in a check's description."""
    if isinstance(value, list):
        return f"[{', '.join(map(show, value[:5]))}{', …' if len(value) > 5 else ''}] ({len(value)})"
    if isinstance(value, dict):
        return "{…}"
    return repr(value) if isinstance(value, str) else str(value)
