"""Values of earlier tasks inside a text param: "$2.1.Dokument$" and similar tokens, filled in when the task runs
(runner.resolve_params). A task is named by its number on the job page; in a loop, a sibling's value is the one for
the current row, the loop's own value has all rows.

    $2.1.Kolona$        column of the first row of #2.1 (or a field of its value, e.g. $2.2.nalog$); inside a loop
                        that goes through #2.1 (#2.1 is the "Petlja", its data set, or a task whose subtasks run
                        per row): the row the loop is at
    $2.1[i].Kolona$     row i, i = the current pass of the loop (of #2.1's loop if it is one, else the innermost)
    $2.1[3].Kolona$     row 3
    $2.1[*].Kolona$     that column of every row, joined with ", "
    $2.1[#]$            number of rows
    $2.1.ukupno.Virman$ a total ("Ukupan iznos")
    $2.1$               the whole value as text (a single value, or the number of rows)
    $red.Kolona$        column of the current row of the loop
    $i$                 the current pass of the loop
    $$                  a "$" sign
"""
import re

_TOKEN = re.compile(r"\$([^$]*)\$")
_TASK = re.compile(r"(\d+(?:\.\d+)*)(?:\[(\*|#|i|\d+)\])?(?:\.(.+))?")
ROW_WORDS = ("red", "Trenutni red")
# Key in the outputs (set by the runner for each row of a loop): {task id: {"red": row, "prolaz": i}} for every loop
# the task is in, and for the data set a "Petlja" goes through.
LOOPS = "@petlje"


class TemplateError(ValueError):
    pass


def has_tokens(text) -> bool:
    return isinstance(text, str) and "$" in text


def render(text: str, outputs: dict, numbers: dict, row: dict | None, index: int | None) -> str:
    """`text` with every token replaced by its value (as text)."""
    by_number = {number: task_id for task_id, number in numbers.items()}

    def replace(match: re.Match) -> str:
        body = match.group(1).strip()
        if body == "":
            return "$"  # "$$"
        return _text(_value(body, outputs, by_number, row, index))

    return _TOKEN.sub(replace, text)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "da" if value else "ne"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _rows(value):
    if isinstance(value, dict) and isinstance(value.get("redovi"), list):
        return value["redovi"]
    if isinstance(value, list):
        return value
    return None


def _cell(row, column: str, token: str):
    if not isinstance(row, dict):
        return row
    if column not in row:
        raise TemplateError(f"${token}$: kolona „{column}“ ne postoji. Kolone: {', '.join(row)}.")
    return row[column]


def _value(body: str, outputs: dict, by_number: dict, row: dict | None, index: int | None):
    if body == "i":
        if index is None:
            raise TemplateError("$i$ postoji samo u petlji (podzadaci koji se izvršavaju za svaki red).")
        return index
    head, _, column = body.partition(".")
    if head in ROW_WORDS:
        if row is None:
            raise TemplateError(f"${body}$: „Trenutni red“ postoji samo u petlji.")
        if not column:
            raise TemplateError(f"${body}$: navedite kolonu, npr. $red.Dokument$.")
        return _cell(row, column, body)
    m = _TASK.fullmatch(body)
    if not m:
        raise TemplateError(f"${body}$ nije ispravna oznaka (npr. $2.1.Dokument$ ili $2.1[i].Dokument$).")
    number, pick, rest = m.groups()
    task_id = by_number.get(number)
    if task_id is None:
        raise TemplateError(f"${body}$: zadatak #{number} ne postoji u ovom poslu.")
    if task_id not in outputs:
        raise TemplateError(f"${body}$: zadatak #{number} (još) nije vratio vrednost.")
    value = outputs[task_id]
    rows = _rows(value)
    here = (outputs.get(LOOPS) or {}).get(task_id)  # a loop this task is in goes through #number's rows
    if here is not None and pick is None and rest and not rest.startswith("ukupno."):
        if isinstance(here["red"], dict) and rest in here["red"]:
            return here["red"][rest]
    if pick == "#":
        if rows is None:
            raise TemplateError(f"${body}$: zadatak #{number} nije vratio redove.")
        return len(rows)
    if rest and rest.startswith("ukupno.") and pick is None:
        totals = value.get("ukupno") if isinstance(value, dict) else None
        name = rest[len("ukupno."):]
        if not isinstance(totals, dict) or name not in totals:
            known = ", ".join(totals) if isinstance(totals, dict) else "nema ih"
            raise TemplateError(f"${body}$: zadatak #{number} nema ukupan iznos „{name}“ (ukupni iznosi: {known}).")
        return totals[name]
    if pick is None and not rest:
        return len(rows) if rows is not None and isinstance(value, dict) and "uslov" not in value else value
    if pick is None and rest and isinstance(value, dict) and rest in value and rest not in ("redovi", "kolone"):
        return value[rest]  # a field of the value, e.g. $2.2.nalog$
    if rows is None:
        raise TemplateError(f"${body}$: zadatak #{number} nije vratio redove.")
    if not rest:
        raise TemplateError(f"${body}$: navedite kolonu, npr. ${number}[{pick or 1}].Dokument$.")
    if pick == "*":
        return ", ".join(_text(_cell(r, rest, body)) for r in rows)
    if pick == "i":
        if here is not None:
            k = here["prolaz"]
        elif index is None:
            raise TemplateError(f"${body}$: [i] postoji samo u petlji.")
        else:
            k = index
    else:
        k = int(pick) if pick else 1
    if not 1 <= k <= len(rows):
        raise TemplateError(f"${body}$: zadatak #{number} ima {len(rows)} redova; red {k} ne postoji.")
    return _cell(rows[k - 1], rest, body)
