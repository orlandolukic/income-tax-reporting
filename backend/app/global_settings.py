"""Global Settings page API: settings for the whole system, the same for every year and company.

For now the PB-1 comments (Poreski bilans, column "Komentar, stopa, konto"): rules for the form's
sections, one comment per form row for every year and every company (user's rule, 2026-11-15:
no year or company comments). Stored in pb1_comment (filled from the workbook by the PB-1 import
for rows without one), shown read-only beside the Poreski bilans table of every company and
edited only here. A rate (a number, e.g. 5 % on lines 22-25) stays a number: the formulas of
every company's form use it.

The rows (line number, description) are taken from the form of the latest year that has one.
"""

import math

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import require_user
from app.db import session_scope
from app.logging_config import get_logger
from app.models import SourceFile
from app.pb1 import Pb1CellOut, Pb1RowOut, shift_years
from app.pb1_store import get_pb1_store
from app.pb1_workbook import DEFAULT_TAB, CellValue, Pb1Sheet

logger = get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

COMMENT_TAB = DEFAULT_TAB  # Poreski bilans: the tab with the comment column
NUMBER_COLUMN, DESCRIPTION_COLUMN = "A", "B"


class Pb1Comments(BaseModel):
    """The PB-1 comments: rows as on the PB-1 page (line number, description, comment)."""

    sheet: str
    comment_column: str
    rows: list[Pb1RowOut]


class CommentUpdate(BaseModel):
    value: float | str | None  # a number for a rate, text otherwise; None, only spaces or "-" removes it


class CommentUpdateResult(BaseModel):
    row: int
    column: str
    value: CellValue
    edited: bool = False


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _form() -> tuple[Pb1Sheet, int]:
    """The Poreski bilans sheet of the latest year with a PB-1 form, and the years its texts move on."""
    with session_scope() as session:
        years = session.scalars(
            select(SourceFile.year).where(SourceFile.kind == "pb1").order_by(SourceFile.year.desc())
        ).all()
    store = get_pb1_store()
    for year in years:
        template = store.template(year)
        if template is not None and COMMENT_TAB in template[0].sheets:
            pb1, template_year = template
            return pb1.sheets[COMMENT_TAB], year - template_year
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Nema PB-1 obrasca.")


def _comment_rows(sheet: Pb1Sheet) -> dict[int, dict]:
    """Form rows that can have a comment: below the head rows, with a description."""
    out = {}
    for row, cells in sheet.rows.items():
        description = cells.get(DESCRIPTION_COLUMN)
        if row > sheet.head_end and description is not None and str(description.value or "").strip():
            out[row] = cells
    return out


def _numeric(sheet: Pb1Sheet, row: int, value: CellValue) -> bool:
    """A rate: the stored comment is a number, or the form's cell has a percent format."""
    cell = sheet.rows.get(row, {}).get(sheet.spec.comment_column)
    return _is_number(value) or bool(cell and "%" in (cell.number_format or ""))


@router.get("/pb1-comments", response_model_exclude_defaults=True)
def get_pb1_comments(username: str = Depends(require_user)) -> Pb1Comments:
    sheet, delta = _form()
    column = sheet.spec.comment_column
    comments = get_pb1_store().comments(COMMENT_TAB)
    rows = []
    for row, cells in _comment_rows(sheet).items():
        number, description = cells.get(NUMBER_COLUMN), cells[DESCRIPTION_COLUMN]
        form_cell = cells.get(column)
        value = comments.get(row)
        out = {
            DESCRIPTION_COLUMN: Pb1CellOut(value=shift_years(description.value, delta), bold=description.bold),
            column: Pb1CellOut(
                value=value,
                format=form_cell.number_format if form_cell is not None and form_cell.number_format != "General" else None,
                editable=True,
                number=_numeric(sheet, row, value),
            ),
        }
        if number is not None:
            out[NUMBER_COLUMN] = Pb1CellOut(value=number.value)
        rows.append(Pb1RowOut(row=row, cells=out, shaded=bool(description.bold)))
    logger.info("PB-1 comments for '%s': %d rows, %d comments", username, len(rows), len(comments))
    return Pb1Comments(sheet=sheet.name, comment_column=column, rows=rows)


@router.put("/pb1-comments/{row}")
def update_pb1_comment(row: int, update: CommentUpdate, username: str = Depends(require_user)) -> CommentUpdateResult:
    """Saves a row's comment for every year and company (empty removes it)."""
    sheet, _ = _form()
    if row not in _comment_rows(sheet):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Red {row} Poreskog bilansa ne postoji ili nema opis.")
    store = get_pb1_store()
    value = update.value
    if _numeric(sheet, row, store.comments(COMMENT_TAB).get(row)):
        if isinstance(value, str) and value.strip() == "":
            value = None
        if isinstance(value, str) or (value is not None and not math.isfinite(value)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Stopa mora biti broj.")
    else:
        if value is not None and not isinstance(value, str):
            value = str(int(value)) if float(value).is_integer() else str(value)
        value = " ".join(value.split()) if value is not None else None
        if value in ("", "-"):
            value = None  # only spaces or "-" is no comment: removed, never stored
    store.save_comment(COMMENT_TAB, row, value, username)
    logger.info("PB-1 comment of row %d %s by '%s' (every year and company)", row,
                "removed" if value is None else "saved", username)
    logger.debug("PB-1 comment of row %d: %r", row, value)
    return CommentUpdateResult(row=row, column=sheet.spec.comment_column, value=value)
