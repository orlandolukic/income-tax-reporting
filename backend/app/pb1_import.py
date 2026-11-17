"""Import a PB-1 workbook ("<year> PB-1.xls") into PostgreSQL.

    cd backend
    .venv\\Scripts\\python -m app.pb1_import 2025 --dry-run   # check everything, save nothing
    .venv\\Scripts\\python -m app.pb1_import 2025             # import
    .venv\\Scripts\\python -m app.pb1_import 2025 --replace   # import again (only without PB-1 edits)

After this the app never reads the PB-1 file again: the form comes from the database.

Steps (one transaction; any problem rolls everything back):
1. Read the workbook (read-only): every sheet of the form's three tabs, every cell with a value
   or a format (value, number format, bold, fill), the used range and the column widths.
2. The year's GFI data must be in the database. If its PB-1 form was imported before, stop,
   unless --replace is given; --replace refuses while any PB-1 edit or company value is stored
   for a year that uses this form (nothing can be lost).
3. Write the snapshot (source_file of kind 'pb1', pb1_sheet, pb1_sheet_column, pb1_source_cell)
   and check that the form built from the database equals the form built from the file.
4. The global comments (pb1_comment, the same for every year and company) are filled from the
   workbook for rows that have none yet; a comment set in the app is never overwritten.
5. Verify: for every year using the form, every company and every tab, the table the app shows
   is built twice, with the form read from the file and with the form from the database (the
   same stored edits and settings), and compared (values, formats, flags, comments, formulas,
   loss).

The Excel file is never written. (The 2025 import of 2026-11-13 also carried over the PB-1 data
saved before PostgreSQL in the old SQLite store, deleted on 2026-11-13.)
"""

import argparse
import getpass
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.settings import load_settings

load_settings()

from sqlalchemy import exists, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import database_enabled, describe_database, session_scope  # noqa: E402
from app.gfi_store import get_gfi_store  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.models import (  # noqa: E402
    CompanyYear,
    Pb1CompanyEdit,
    Pb1SheetColumn,
    Pb1SheetRow,
    Pb1SourceCell,
    Pb1TemplateEdit,
    SourceFile,
)
from app.pb1 import build_pb1_table, computed_cells, load_pb1_form  # noqa: E402
from app.gfi_workbook import get_data_dir  # noqa: E402
from app.pb1_file import find_pb1_workbook, read_pb1_sheets, read_pb1_workbook  # noqa: E402
from app.pb1_store import (  # noqa: E402
    Pb1Store,
    column_letters,
    load_form_snapshot,
    raw_cell_columns,
    seed_comments,
    workbook_comment_defaults,
)
from app.pb1_workbook import PB1_TABS, Pb1Workbook, build_pb1_workbook, match_tab_sheets  # noqa: E402

logger = get_logger("app.pb1_import")

class ImportStopped(Exception):
    """The import can't be done safely; nothing was saved."""


class DryRunDone(Exception):
    """Raised at the end of a dry run to roll the transaction back."""


def _years_using(session: Session, year: int) -> list[int]:
    """The year and every year whose PB-1 form is constructed from it (directly or not)."""
    years, frontier = [year], [year]
    while frontier:
        children = list(session.scalars(
            select(SourceFile.year).where(
                SourceFile.kind == "pb1", SourceFile.origin == "constructed", SourceFile.based_on_year.in_(frontier)
            )
        ))
        children = [y for y in children if y not in years]
        years += children
        frontier = children
    return sorted(years)


def _has_pb1_values(session: Session, years: list[int]) -> bool:
    template = session.scalar(select(exists().where(Pb1TemplateEdit.year.in_(years))))
    company = session.scalar(select(exists().where(
        Pb1CompanyEdit.company_year_id == CompanyYear.id, CompanyYear.year.in_(years)
    )))
    return bool(template or company)


def _remove_previous(session: Session, year: int, replace: bool) -> bool:
    previous = session.scalar(select(SourceFile).where(SourceFile.kind == "pb1", SourceFile.year == year))
    if previous is None:
        return False
    if previous.origin != "workbook":
        raise ImportStopped(
            f"The PB-1 form of {year} was constructed from {previous.based_on_year} ({previous.file_name});"
            " it is not replaced by a workbook."
        )
    if not replace:
        raise ImportStopped(
            f"The PB-1 form of {year} was already imported from {previous.file_name} on"
            f" {previous.imported_at:%Y-%m-%d %H:%M}. Use --replace to import it again."
        )
    years = _years_using(session, year)
    if _has_pb1_values(session, years):
        raise ImportStopped(
            f"PB-1 edits or company values are stored for {', '.join(map(str, years))};"
            " replacing the form could misplace them, so nothing was changed."
        )
    logger.info("Removing the earlier PB-1 import of %s (%s, no PB-1 values stored)", year, previous.file_name)
    session.delete(previous)  # cascades to pb1_sheet, pb1_sheet_column, pb1_source_cell
    session.flush()
    return True


def _write_snapshot(
    session: Session, year: int, path: Path, content: bytes, tab_sheets: dict, user: str, form: Pb1Workbook
) -> SourceFile:
    """Stores the sheets' cells, except those that are not part of the form (Pb1Sheet.dropped)."""
    source = SourceFile(
        kind="pb1", year=year, origin="workbook", file_name=path.name, sheet_name=PB1_TABS[0].sheet_prefix,
        sha256=hashlib.sha256(content).digest(),
        file_mtime=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        imported_at=datetime.now(timezone.utc), imported_by=user,
    )
    session.add(source)
    session.flush()
    cells = 0
    for position, (tab, sheet) in enumerate(tab_sheets.items()):
        session.add(Pb1SheetRow(
            source_file_id=source.id, tab=tab, position=position, name=sheet.name, nrows=sheet.nrows, ncols=sheet.ncols,
        ))
        session.flush()
        for c, width in sheet.widths.items():
            session.add(Pb1SheetColumn(source_file_id=source.id, tab=tab, col=column_letters(c), width=width))
        dropped = form.sheets[tab].dropped if tab in form.sheets else frozenset()
        for (r, c), cell in sheet.cells.items():
            if (r + 1, column_letters(c)) in dropped:
                continue
            session.add(Pb1SourceCell(
                source_file_id=source.id, tab=tab, row=r + 1, col=column_letters(c), kind=cell.kind,
                number_format=cell.number_format, bold=cell.bold, fill=cell.fill, **raw_cell_columns(cell),
            ))
            cells += 1
    session.flush()
    logger.info("Snapshot of %s: %d sheets, %d cells", path.name, len(tab_sheets), cells)
    return source


class _FileForm(Pb1Store):
    """The stored edits and settings (database) with the form as read from the file."""

    def __init__(self, session: Session, pb1: Pb1Workbook, template_year: int, years: list[int]):
        super().__init__(session)
        self._pb1, self._template_year, self._years = pb1, template_year, set(years)

    def template(self, year: int):
        return (self._pb1, self._template_year) if year in self._years else None


def _verify(session: Session, pb1: Pb1Workbook, template_year: int, years: list[int]) -> int:
    """Compares every table of every company of `years`: form from the file vs. from the database."""
    old, new = _FileForm(session, pb1, template_year, years), Pb1Store(session)
    gfi = get_gfi_store()
    differences: list[str] = []
    count = 0
    for year in years:
        source, _ = gfi.load(year)
        for row in sorted(source.rows):
            for spec in PB1_TABS:
                if spec.key not in pb1.sheets:
                    continue
                a = build_pb1_table(load_pb1_form(year, row, spec.key, "pb1_import", old))
                b = build_pb1_table(load_pb1_form(year, row, spec.key, "pb1_import", new))
                if json.dumps(a.model_dump(mode="json"), sort_keys=True) != json.dumps(b.model_dump(mode="json"), sort_keys=True):
                    differences.append(f"{year} row {row} {spec.key}")
                count += 1
        logger.info("Verified %s: %d companies × %d tabs", year, len(source.rows), len(pb1.sheets))
    if differences:
        raise ImportStopped(
            f"{len(differences)} PB-1 table(s) differ between the form from the file and from the database"
            f" ({', '.join(differences[:10])}). Nothing was imported."
        )
    return count


def import_pb1(year: int, replace: bool, dry_run: bool, user: str) -> None:
    path = find_pb1_workbook(get_data_dir(), year)
    if path is None:
        raise ImportStopped(f'No "{year} PB-1.xls" in {get_data_dir()}')
    content = path.read_bytes()
    tab_sheets = match_tab_sheets(path.name, read_pb1_sheets(path))
    expected = build_pb1_workbook(path.name, tab_sheets)
    if repr(expected) != repr(read_pb1_workbook(path)):
        raise ImportStopped("Reading the workbook twice gave different forms")
    logger.info("%s: tabs %s, company %r", path.name, ", ".join(tab_sheets), expected.company_name)
    formulas = computed_cells(expected)
    logger.info("Formulas: %d computed cells", sum(len(c) for c in formulas.values()))

    with session_scope() as session:
        if session.scalar(select(SourceFile.id).where(SourceFile.kind == "gfi", SourceFile.year == year)) is None:
            raise ImportStopped(f"{year} has no GFI data in the database; import the GFI workbook first (app.gfi_import)")
        _remove_previous(session, year, replace)
        source = _write_snapshot(session, year, path, content, tab_sheets, user, expected)
        loaded = load_form_snapshot(session, source)
        if repr(loaded) != repr(expected):
            raise ImportStopped("The form built from the database differs from the form built from the file")
        logger.info("Snapshot check: the form from the database equals the form from the file")

        years = _years_using(session, year)
        added = seed_comments(session, workbook_comment_defaults(expected), "workbook", user)
        logger.info("Global comments filled from the workbook (rows without one): %d added", added)
        count = _verify(session, expected, year, years)
        logger.info("Verified: %d tables equal (form from the file vs. from the database)", count)
        if dry_run:
            raise DryRunDone


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a PB-1 workbook into PostgreSQL.")
    parser.add_argument("year", type=int)
    parser.add_argument("--replace", action="store_true", help="replace an earlier import (only without PB-1 values)")
    parser.add_argument("--dry-run", action="store_true", help="run and verify everything, then roll back")
    parser.add_argument("--user", default=getpass.getuser(), help="recorded as imported_by")
    args = parser.parse_args()

    setup_logging()
    if not database_enabled():
        logger.error("DATABASE_URL is not set (backend/.env). See backend/.env.example.")
        return 2
    logger.info("Database: %s", describe_database())
    try:
        import_pb1(args.year, args.replace, args.dry_run, args.user)
    except DryRunDone:
        logger.info("Dry run: everything checked, nothing was saved")
        return 0
    except ImportStopped as exc:
        logger.error("Import stopped, nothing was saved: %s", exc)
        return 1
    logger.info("PB-1 import of %s committed", args.year)
    return 0


if __name__ == "__main__":
    sys.exit(main())
