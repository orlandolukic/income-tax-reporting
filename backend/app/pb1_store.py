"""The PB-1 form, its edits and its settings in PostgreSQL (no file is ever read).

A year's form is the imported snapshot of its "<year> PB-1.xls" (pb1_sheet /
pb1_sheet_column / pb1_source_cell, imported once with app.pb1_import), or, for a year
constructed on the Migracija page, the form of the year it was built from (followed back to an
imported one). Edits shared by every company: pb1_template_edit; a company's own values
(amounts, months): pb1_company_edit (by company_year and report: the preliminary and the final
report are kept separately; the final one is a full copy made from the preliminary one,
pb1_report_state); the comments, global for every year and company: pb1_comment. Numbers of
edits and comments are returned as floats.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.logging_config import get_logger
from app.models import (
    CompanyYear,
    Pb1Comment,
    Pb1CompanyEdit,
    Pb1ReportEvent,
    Pb1ReportState,
    Pb1SheetColumn,
    Pb1SheetRow,
    Pb1SourceCell,
    Pb1TemplateEdit,
    SourceFile,
)
from app.pb1_workbook import (
    CellValue,
    Pb1Cell,
    Pb1Workbook,
    RawCell,
    SheetCells,
    build_pb1_workbook,
)

logger = get_logger(__name__)

# (row, col) -> (value, value shown before the first edit)
Pb1Edits = dict[tuple[int, str], tuple[CellValue, CellValue]]
# Per tab: (template edits shared by every company, the company's own edits, global comments row -> value)
TabEdits = tuple[Pb1Edits, Pb1Edits, dict[int, CellValue]]
# A company's identity for its PB-1 values: (GFI source name, GFI row) of the year; None = the template.
CompanyKey = tuple[str, int]
# One of a company's two PB-1 reports (app.models.PB1_REPORTS).
PRELIMINARY, FINAL = "preliminary", "final"


@dataclass(frozen=True)
class ReportState:
    """Where a company year's PB-1 reports stand (pb1_report_state; no row = nothing done)."""

    preliminary_done: bool = False
    gfi_done: bool = False  # GFI (annual financial statements) done: the final report can be made
    final_created: bool = False
    final_done: bool = False  # the final report is marked as done (locked until unlocked)
    submitted_at: datetime | None = None  # the report is submitted (since then)


@dataclass(frozen=True)
class ReportEvent:
    """One step of the reports (pb1_report_event)."""

    event: str
    at: datetime
    by: str


def _event(session: Session, company_year_id: int, event: str, user: str, at: datetime) -> None:
    session.add(Pb1ReportEvent(company_year_id=company_year_id, event=event, happened_at=at, happened_by=user))


class Pb1StoreError(LookupError):
    """A PB-1 value that can't be stored (e.g. the company is not in the year)."""


def _is_number(value: CellValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def comment_value(cell: Pb1Cell) -> CellValue:
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


def workbook_comment_defaults(pb1: Pb1Workbook) -> dict[str, dict[int, CellValue]]:
    """The comments written in the workbook (tab -> row -> value): the defaults of a new form."""
    out: dict[str, dict[int, CellValue]] = {}
    for key, sheet in pb1.sheets.items():
        column = sheet.spec.comment_column
        if column is None:
            continue
        out[key] = {
            row: comment_value(cells[column])
            for row, cells in sheet.rows.items()
            if row > sheet.head_end and column in cells and comment_value(cells[column]) is not None
        }
    return out


def to_decimal(value: CellValue | Decimal) -> Decimal | None:
    """A number for a Numeric column, exactly (floats through their shortest repr)."""
    if isinstance(value, Decimal):
        return value
    if not _is_number(value):
        return None
    return Decimal(value) if isinstance(value, int) else Decimal(repr(float(value)))


def _file_number(value: Decimal) -> int | float:
    """A number of the workbook snapshot as read from the file: int when whole, else float."""
    return int(value) if value == value.to_integral_value() else float(value)


def split_value(value: CellValue) -> tuple[Decimal | None, str | None]:
    """(number, text) columns of an edit or a comment."""
    if isinstance(value, str):
        return None, value
    return to_decimal(value), None


def _joined(number: Decimal | None, text: str | None) -> CellValue:
    """The value of (number, text) columns; numbers as floats (as the API has always returned them)."""
    if text is not None:
        return text
    return float(number) if number is not None else None


def column_index(letters: str) -> int:
    """'A' -> 0, 'Q' -> 16, 'AA' -> 26."""
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - ord("A") + 1
    return n - 1


def column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def raw_cell_columns(cell: RawCell) -> dict:
    """The value columns of a pb1_source_cell row for a cell read from the file."""
    if cell.kind == "number":
        return {"value_number": to_decimal(cell.value)}
    if cell.kind in ("text", "error"):
        return {"value_text": cell.value}
    if cell.kind == "bool":
        return {"value_bool": cell.value}
    return {}


def _raw_cell(row: Pb1SourceCell) -> RawCell:
    if row.kind == "number":
        value: CellValue = _file_number(row.value_number)
    elif row.kind == "bool":
        value = row.value_bool
    else:
        value = row.value_text  # text, error; None for "empty"
    return RawCell(kind=row.kind, value=value, number_format=row.number_format, bold=row.bold, fill=row.fill)


def load_form_snapshot(session: Session, source_file: SourceFile) -> Pb1Workbook:
    """The PB-1 form from the imported workbook snapshot (no file is read)."""
    sheets = list(session.scalars(
        select(Pb1SheetRow).where(Pb1SheetRow.source_file_id == source_file.id).order_by(Pb1SheetRow.position)
    ))
    widths: dict[str, dict[int, int]] = {}
    for c in session.scalars(select(Pb1SheetColumn).where(Pb1SheetColumn.source_file_id == source_file.id)):
        widths.setdefault(c.tab, {})[column_index(c.col)] = c.width
    cells: dict[str, dict[tuple[int, int], RawCell]] = {}
    for c in session.scalars(select(Pb1SourceCell).where(Pb1SourceCell.source_file_id == source_file.id)):
        cells.setdefault(c.tab, {})[(c.row - 1, column_index(c.col))] = _raw_cell(c)
    tab_sheets = {
        s.tab: SheetCells(name=s.name, nrows=s.nrows, ncols=s.ncols, cells=cells.get(s.tab, {}), widths=widths.get(s.tab, {}))
        for s in sheets
    }
    return build_pb1_workbook(source_file.file_name, tab_sheets)


@dataclass(frozen=True)
class _CachedForm:
    imported_at: datetime
    form: Pb1Workbook


# source_file id -> its form. The snapshot never changes; a re-import is a new source_file.
_form_cache: dict[int, _CachedForm] = {}


def form_source(session: Session, year: int) -> tuple[SourceFile, int] | None:
    """The imported PB-1 workbook (source_file) used as the form of `year`, and its year: the
    year's own, or for a constructed year the form of the year it was built from."""
    seen: set[int] = set()
    while year not in seen:
        seen.add(year)
        source = session.scalar(select(SourceFile).where(SourceFile.kind == "pb1", SourceFile.year == year))
        if source is None:
            return None
        if source.origin == "workbook":
            return source, year
        if source.based_on_year is None:
            return None
        year = source.based_on_year
    return None


def seed_comments(session: Session, values: dict[str, dict[int, CellValue]], source: str, user: str) -> int:
    """Stores global comments for rows that have none yet (never overwrites one set in the app).
    Returns the count added."""
    existing = set(session.execute(select(Pb1Comment.tab, Pb1Comment.row)).all())
    now = datetime.now(timezone.utc)
    added = 0
    for tab, rows in values.items():
        for row, value in rows.items():
            if (tab, row) in existing:
                continue
            number, text = split_value(value)
            session.add(Pb1Comment(
                tab=tab, row=row, value_number=number, value_text=text, source=source,
                updated_by=user, updated_at=now,
            ))
            added += 1
    session.flush()
    return added


def copy_form_settings(session: Session, from_year: int, to_year: int, user: str) -> int:
    """For a constructed year's form: the form-level settings of the year it is built from, as
    they are in the app: the shared template edits (the comments are global, nothing to copy).
    Company values are not copied; rows the new year already has are kept. Returns the edits copied."""
    now = datetime.now(timezone.utc)
    have = set(session.execute(
        select(Pb1TemplateEdit.tab, Pb1TemplateEdit.row, Pb1TemplateEdit.col).where(Pb1TemplateEdit.year == to_year)
    ).all())
    edits = 0
    for e in session.scalars(select(Pb1TemplateEdit).where(Pb1TemplateEdit.year == from_year)):
        if (e.tab, e.row, e.col) in have:
            continue
        session.add(Pb1TemplateEdit(
            year=to_year, tab=e.tab, row=e.row, col=e.col, value_number=e.value_number, value_text=e.value_text,
            original_number=e.original_number, original_text=e.original_text, updated_by=user, updated_at=now,
        ))
        edits += 1
    session.flush()
    return edits


class Pb1Store:
    """The PB-1 forms, edits and settings in PostgreSQL."""

    name = "PostgreSQL"

    def __init__(self, session: Session | None = None) -> None:
        # With a session: work inside it (the PB-1 import verifies its rows before committing).
        self._session = session

    @contextmanager
    def _scope(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
        else:
            with session_scope() as session:
                yield session

    def template(self, year: int) -> tuple[Pb1Workbook, int] | None:
        """The form of `year` and the year of the workbook it comes from, or None."""
        with self._scope() as session:
            found = form_source(session, year)
            if found is None:
                return None
            source, template_year = found
            cached = _form_cache.get(source.id)
            if cached is None or cached.imported_at != source.imported_at:
                cached = _CachedForm(source.imported_at, load_form_snapshot(session, source))
                _form_cache[source.id] = cached
                logger.info("PB-1 form %s loaded from the database", source.file_name)
            return cached.form, template_year

    @staticmethod
    def _company_year(session: Session, year: int, company: CompanyKey) -> CompanyYear | None:
        return session.scalar(
            select(CompanyYear).where(
                CompanyYear.year == year, CompanyYear.source_row == company[1], CompanyYear.active
            )
        )

    def form_edits(
        self, year: int, pb1: Pb1Workbook, company: CompanyKey, user: str, report: str = PRELIMINARY
    ) -> dict[str, TabEdits]:
        """The edits and the global comments of every tab of a company's form; the company's own
        values of the given report."""
        out: dict[str, TabEdits] = {tab: ({}, {}, {}) for tab in pb1.sheets}
        with self._scope() as session:
            for e in session.scalars(select(Pb1TemplateEdit).where(Pb1TemplateEdit.year == year)):
                if e.tab in out:
                    out[e.tab][0][(e.row, e.col)] = (
                        _joined(e.value_number, e.value_text), _joined(e.original_number, e.original_text)
                    )
            company_year = self._company_year(session, year, company)
            if company_year is not None:
                for e in session.scalars(
                    select(Pb1CompanyEdit).where(
                        Pb1CompanyEdit.company_year_id == company_year.id, Pb1CompanyEdit.report == report
                    )
                ):
                    if e.tab in out:
                        out[e.tab][1][(e.row, e.col)] = (
                            _joined(e.value_number, e.value_text), _joined(e.original_number, e.original_text)
                        )
            for d in session.scalars(select(Pb1Comment)):
                if d.tab in out and pb1.sheets[d.tab].spec.comment_column:
                    out[d.tab][2][d.row] = _joined(d.value_number, d.value_text)
        return out

    def save_edit(self, year, pb1, tab, row, col, company, value, original, user, report: str = PRELIMINARY) -> None:
        number, text = split_value(value)
        now = datetime.now(timezone.utc)
        with self._scope() as session:
            if company is None:
                key = {"year": year, "tab": tab, "row": row, "col": col}
                edit = session.get(Pb1TemplateEdit, key)
                if edit is None:
                    edit = Pb1TemplateEdit(**key)
            else:
                company_year = self._company_year(session, year, company)
                if company_year is None:
                    raise Pb1StoreError(f"U redu {company[1]} za godinu {year} nema firme.")
                key = {"company_year_id": company_year.id, "report": report, "tab": tab, "row": row, "col": col}
                edit = session.get(Pb1CompanyEdit, key)
                if edit is None:
                    edit = Pb1CompanyEdit(**key)
            if edit.updated_at is None:
                # The value shown before the first edit is kept from the first save on.
                edit.original_number, edit.original_text = split_value(original)
            edit.value_number, edit.value_text = number, text
            edit.updated_by, edit.updated_at = user, now
            session.add(edit)
            session.flush()

    def delete_edit(self, year, pb1, tab, row, col, company, report: str = PRELIMINARY) -> None:
        with self._scope() as session:
            if company is None:
                edit = session.get(Pb1TemplateEdit, {"year": year, "tab": tab, "row": row, "col": col})
            else:
                company_year = self._company_year(session, year, company)
                edit = company_year and session.get(
                    Pb1CompanyEdit,
                    {"company_year_id": company_year.id, "report": report, "tab": tab, "row": row, "col": col},
                )
            if edit is not None:
                session.delete(edit)
                session.flush()

    # --- the two reports (preliminary, final) ---

    def report_state(self, year: int, company: CompanyKey) -> ReportState:
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            state = company_year and session.get(Pb1ReportState, company_year.id)
            if not state:
                return ReportState()
            return ReportState(
                preliminary_done=state.preliminary_done_at is not None,
                gfi_done=state.gfi_done_at is not None,
                final_created=state.final_created_at is not None,
                final_done=state.final_done_at is not None,
                submitted_at=state.submitted_at,
            )

    def report_history(self, year: int, company: CompanyKey) -> list[ReportEvent]:
        """The steps of the company year's reports, oldest first."""
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            if company_year is None:
                return []
            return [
                ReportEvent(e.event, e.happened_at, e.happened_by)
                for e in session.scalars(
                    select(Pb1ReportEvent)
                    .where(Pb1ReportEvent.company_year_id == company_year.id)
                    .order_by(Pb1ReportEvent.happened_at, Pb1ReportEvent.id)
                )
            ]

    def mark_preliminary_done(self, year: int, company: CompanyKey, user: str) -> None:
        """Marks the preliminary report as done (it is locked from then on)."""
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            if company_year is None:
                raise Pb1StoreError(f"U redu {company[1]} za godinu {year} nema firme.")
            state = session.get(Pb1ReportState, company_year.id) or Pb1ReportState(company_year_id=company_year.id)
            if state.preliminary_done_at is None:
                now = datetime.now(timezone.utc)
                state.preliminary_done_by, state.preliminary_done_at = user, now
                session.add(state)
                _event(session, company_year.id, "preliminary_done", user, now)
                session.flush()

    def create_final(
        self, year: int, company: CompanyKey, values: dict[tuple[str, int, str], CellValue], user: str
    ) -> int:
        """Creates the final report as a full copy of the preliminary one in the database: every
        value of the company, (tab, row, col) -> value, stored for the final report (its value
        before any edit is the copied one). Returns the number of values copied."""
        now = datetime.now(timezone.utc)
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            state = company_year and session.get(Pb1ReportState, company_year.id)
            if not state or state.preliminary_done_at is None:
                raise Pb1StoreError("Preliminarni izveštaj još nije označen kao gotov.")
            if state.final_created_at is not None:
                raise Pb1StoreError("Konačni izveštaj je već napravljen.")
            if state.gfi_done_at is None:
                raise Pb1StoreError("GFI još nije označen kao gotov.")
            for (tab, row, col), value in values.items():
                number, text = split_value(value)
                session.add(Pb1CompanyEdit(
                    company_year_id=company_year.id, report=FINAL, tab=tab, row=row, col=col,
                    value_number=number, value_text=text, original_number=number, original_text=text,
                    updated_by=user, updated_at=now,
                ))
            state.final_created_by, state.final_created_at = user, now
            _event(session, company_year.id, "final_created", user, now)
            session.flush()
        return len(values)

    def set_gfi_done(self, year: int, company: CompanyKey, done: bool, user: str) -> None:
        """Marks GFI as done (after the preliminary report) or reopens it (only before the final
        report is created)."""
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            state = company_year and session.get(Pb1ReportState, company_year.id)
            if not state or state.preliminary_done_at is None:
                raise Pb1StoreError("Preliminarni izveštaj još nije označen kao gotov.")
            if state.final_created_at is not None:
                raise Pb1StoreError("Konačni izveštaj je već napravljen; GFI se više ne otvara.")
            now = datetime.now(timezone.utc)
            if done:
                state.gfi_done_by, state.gfi_done_at = user, now
            else:
                state.gfi_done_by, state.gfi_done_at = None, None
            _event(session, company_year.id, "gfi_done" if done else "gfi_reopened", user, now)
            session.flush()

    def set_final_done(self, year: int, company: CompanyKey, done: bool, user: str) -> None:
        """Marks the final report as done (locked) or unlocks it again."""
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            state = company_year and session.get(Pb1ReportState, company_year.id)
            if not state or state.final_created_at is None:
                raise Pb1StoreError("Konačni izveštaj još nije napravljen.")
            if state.submitted_at is not None:
                raise Pb1StoreError("Izveštaj je predat; prvo povucite predaju.")
            now = datetime.now(timezone.utc)
            if done:
                state.final_done_by, state.final_done_at = user, now
            else:
                state.final_done_by, state.final_done_at = None, None
            _event(session, company_year.id, "final_done" if done else "final_unlocked", user, now)
            session.flush()

    def set_submitted(self, year: int, company: CompanyKey, submitted: bool, user: str) -> None:
        """Marks the report as submitted (now) or withdraws the submission."""
        with self._scope() as session:
            company_year = self._company_year(session, year, company)
            state = company_year and session.get(Pb1ReportState, company_year.id)
            if submitted and (not state or state.final_done_at is None):
                raise Pb1StoreError("Predaje se samo konačni izveštaj označen kao gotov.")
            if not submitted and (not state or state.submitted_at is None):
                raise Pb1StoreError("Izveštaj nije predat.")
            now = datetime.now(timezone.utc)
            if submitted:
                state.submitted_by, state.submitted_at = user, now
            else:
                state.submitted_by, state.submitted_at = None, None
            _event(session, company_year.id, "submitted" if submitted else "submission_withdrawn", user, now)
            session.flush()

    # --- global comments (Global Settings) ---

    def comments(self, tab: str) -> dict[int, CellValue]:
        """The comments of a tab (row -> value), the same for every year and company."""
        with self._scope() as session:
            return {
                d.row: _joined(d.value_number, d.value_text)
                for d in session.scalars(select(Pb1Comment).where(Pb1Comment.tab == tab))
            }

    def save_comment(self, tab: str, row: int, value: CellValue, user: str) -> None:
        """Stores a row's comment for every year and company; None removes it."""
        with self._scope() as session:
            comment = session.get(Pb1Comment, {"tab": tab, "row": row})
            if value is None:
                if comment is not None:
                    session.delete(comment)
                    session.flush()
                return
            if comment is None:
                comment = Pb1Comment(tab=tab, row=row, source="app")
            comment.value_number, comment.value_text = split_value(value)
            comment.updated_by, comment.updated_at = user, datetime.now(timezone.utc)
            session.add(comment)
            session.flush()


def get_pb1_store() -> Pb1Store:
    return Pb1Store()

