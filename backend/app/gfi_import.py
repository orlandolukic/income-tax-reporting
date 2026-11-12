"""Import a GFI workbook into PostgreSQL (one reporting year at a time).

    cd backend
    .venv\\Scripts\\python -m app.gfi_import 2025 --dry-run   # check everything, save nothing
    .venv\\Scripts\\python -m app.gfi_import 2025             # import
    .venv\\Scripts\\python -m app.gfi_import 2025 --replace   # import again over an earlier import

Steps (all in one transaction; any problem rolls everything back):
1. Read "<year> GFI *.xlsx" (read-only) and keep only the company list: the rows while
   R.B. continues 1, 2, 3, ... (2025: 165 companies, ending with DAGOTTA). R.B. is used
   only for this; the R.B. columns are not stored.
2. If the year was imported before, stop, unless --replace is given. --replace removes the
   earlier import only if none of its values were changed in the database (no edit can
   be lost); its change_log history is kept.
3. First import of a year: read the user edits for that workbook from SQLite (read-only).
   Every edit must belong to an editable numeric GFI cell in the kept rows; otherwise the
   import stops, so no edit is ever dropped. A --replace does not apply them again: they
   were carried over by the first import and the database is the source of truth since.
4. Write the snapshot (source_file, gfi_column, source_cell), companies, company years,
   referents, offices and import issues, then apply the SQLite edits (with change_log
   entries). Companies, referents and offices no longer used are removed.
5. Verify: build the GFI table from the database and compare every cell with the table
   built from Excel + SQLite (value, format, formula, editable, edited, original).

The Excel file and the SQLite database are never written.
"""

import argparse
import collections
import dataclasses
import getpass
import hashlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.settings import load_settings

load_settings()

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.companies import CompanyTable, build_company_table  # noqa: E402
from app.db import database_enabled, describe_database, session_scope  # noqa: E402
from app.edits_store import get_database_path  # noqa: E402
from app.gfi_store import (  # noqa: E402
    OFFICE_FIELD,
    TEXT_FIELDS,
    Edits,
    current_text,
    edit_kind,
    load_table,
    map_columns,
    set_text,
    to_decimal,
)
from app.gfi_workbook import SourceTable, company_list, main_list_rows, read_source_table  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.models import (  # noqa: E402
    NUMERIC_FIELDS,
    ChangeLog,
    Company,
    CompanyYear,
    GfiColumn,
    ImportIssue,
    Office,
    Pb1Link,
    Referent,
    ReportingYear,
    SourceCell,
    SourceFile,
)
from app.reporting_years import find_workbooks, get_data_dir  # noqa: E402

logger = get_logger("gfi_import")

PIB_PATTERN = re.compile(r"^\d{9}$")


class ImportStopped(Exception):
    """The import cannot continue safely; nothing is saved."""


class DryRunDone(Exception):
    """Raised at the end of a dry run to roll the transaction back."""


def _workbook_path(year: int) -> Path:
    paths = find_workbooks(get_data_dir()).get(year)
    if not paths:
        raise ImportStopped(f"No '{year} GFI *.xlsx' workbook in {get_data_dir()}")
    if len(paths) > 1:
        raise ImportStopped(f"Several GFI workbooks for {year}: {[p.name for p in paths]}; keep only one")
    return paths[0]


def _read_sqlite_edits(source: SourceTable) -> list[tuple]:
    """(row, col, value, original_value, updated_by, updated_at) for this workbook, read-only.
    Text edits (company details) are returned as text values."""
    path = get_database_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(cell_edits)")}
        text = "value_text" in columns
        rows = conn.execute(
            "SELECT row, col, value, original_value, updated_by, updated_at"
            + (", value_text, original_text" if text else ", NULL, NULL")
            + " FROM cell_edits WHERE workbook = ? AND sheet = ? ORDER BY row, col",
            (source.workbook, source.sheet),
        ).fetchall()
    finally:
        conn.close()
    return [
        (row, col, value_text if value_text is not None else value,
         original_text if original_text is not None else original, user, at)
        for row, col, value, original, user, at, value_text, original_text in rows
    ]


def _read_sqlite_pb1_links(year: int, gfi_workbook: str) -> list[tuple]:
    """(pb1_workbook, pb1_company, gfi_row, linked_by, linked_at) for links to this GFI workbook, read-only."""
    path = get_database_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pb1_links'").fetchone():
            return []
        return conn.execute(
            "SELECT pb1_workbook, pb1_company, gfi_row, linked_by, linked_at FROM pb1_links"
            " WHERE year = ? AND gfi_workbook = ?",
            (year, gfi_workbook),
        ).fetchall()
    finally:
        conn.close()


def _remove_previous_import(session: Session, year: int, replace: bool) -> bool:
    """Remove an earlier import of the year (see the module docstring). True if one was removed."""
    previous = session.scalar(select(SourceFile).where(SourceFile.kind == "gfi", SourceFile.year == year))
    if previous is None:
        return False
    if not replace:
        raise ImportStopped(
            f"{year} was already imported from {previous.file_name} on {previous.imported_at:%Y-%m-%d %H:%M}."
            " Use --replace to import it again."
        )
    _, edits = load_table(session, year)
    if edits:
        listed = ", ".join(f"{col}{row}" for row, col in sorted(edits))
        raise ImportStopped(
            f"The earlier {year} import has {len(edits)} value(s) changed in the database ({listed})."
            " Replacing it would lose them, so nothing was changed."
        )
    logger.info("Removing the earlier %s import (%s, no changed values)", year, previous.file_name)
    session.delete(previous)  # cascades to gfi_column, source_cell, company_year, import_issue
    session.flush()
    return True


def _remove_unused(session: Session) -> None:
    used_companies = select(CompanyYear.company_id)
    removed = session.execute(delete(Company).where(Company.id.not_in(used_companies))).rowcount
    removed_ref = session.execute(
        delete(Referent).where(Referent.id.not_in(select(CompanyYear.referent_id).where(CompanyYear.referent_id.is_not(None))))
    ).rowcount
    removed_off = session.execute(
        delete(Office).where(Office.id.not_in(select(CompanyYear.office_id).where(CompanyYear.office_id.is_not(None))))
    ).rowcount
    if removed or removed_ref or removed_off:
        logger.info("Removed unused records: %d companies, %d referents, %d offices", removed, removed_ref, removed_off)


def _lookup(session: Session, model: type[Referent] | type[Office], cache: dict[str, int], name: str) -> int:
    if name not in cache:
        existing = session.scalar(select(model).where(model.name == name))
        if existing is None:
            existing = model(name=name)
            session.add(existing)
            session.flush()
        cache[name] = existing.id
    return cache[name]


def _cell_columns(value: object) -> dict:
    if isinstance(value, bool):
        return {"value_bool": value}
    if isinstance(value, (int, float)):
        return {"value_number": to_decimal(value)}
    if value is None:
        return {}
    return {"value_text": str(value)}


def _verify(
    session: Session, year: int, expected: CompanyTable, kept: list[int], field_of: dict[str, str]
) -> collections.Counter:
    """Compare the table built from the database with the Excel + SQLite table."""
    db_source, db_edits = load_table(session, year)
    actual = build_company_table(db_source, db_edits)
    known = collections.Counter()
    problems: list[str] = []

    if [c.model_dump() for c in actual.columns] != [c.model_dump() for c in expected.columns]:
        problems.append("column headers differ")
    expected_rows = {r.row: r for r in expected.rows if r.row in set(kept)}
    actual_rows = {r.row: r for r in actual.rows}
    if list(actual_rows) != list(expected_rows):
        problems.append(f"rows differ: database {len(actual_rows)}, Excel {len(expected_rows)}")

    for row, expected_row in expected_rows.items():
        actual_row = actual_rows.get(row)
        if actual_row is None:
            continue
        for col, expected_cell in expected_row.cells.items():
            want = expected_cell.model_dump()
            got = actual_row.cells[col].model_dump() if col in actual_row.cells else None
            field = field_of.get(col)
            # Known, intended differences:
            if got and field not in NUMERIC_FIELDS and want["editable"] and not got["editable"]:
                known["unmapped numeric cells are read-only in the database"] += 1
                want["editable"] = False
            if got and field == "pib" and isinstance(want["value"], int) and got["value"] == str(want["value"]):
                known["numeric PIB stored as text"] += 1
                want["value"] = got["value"]
            if got != want:
                problems.append(f"{col}{row}: Excel+SQLite {want} != database {got}")

    if problems:
        shown = "\n  ".join(problems[:20])
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise ImportStopped(f"Verification failed, {len(problems)} difference(s):\n  {shown}{more}")
    return known


def import_year(year: int, replace: bool, dry_run: bool, user: str) -> None:
    path = _workbook_path(year)
    content = path.read_bytes()
    workbook = read_source_table(path)
    kept = main_list_rows(workbook)
    if not kept:
        raise ImportStopped("No company list found (R.B. does not start with 1, 2, 3, ...)")
    # The company list without the R.B. columns, exactly as the app shows it.
    source = company_list(workbook)
    try:
        field_of = map_columns(source.headers)
    except ValueError as exc:
        raise ImportStopped(str(exc)) from exc
    source = dataclasses.replace(source, fields=field_of)
    col_of = {field: col for col, field in field_of.items()}
    last = source.rows[kept[-1]][col_of["name"]].value
    logger.info("%s: %d companies (Excel rows %d-%d), last: #%d %s", path.name, len(kept), kept[0], kept[-1], len(kept), last)

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        replaced = _remove_previous_import(session, year, replace)

        # SQLite edits: carried over by the first import of a year, every one of them. After
        # that the database is the source of truth, so a --replace does not apply them again.
        if replaced:
            sqlite_edits = []
            logger.info("Earlier import replaced: SQLite edits are not applied again (already carried over)")
        else:
            sqlite_edits = _read_sqlite_edits(source)
        excel_edits: Edits = {}
        unmappable = []
        for row, col, value, original, *_ in sqlite_edits:
            cell = source.rows.get(row, {}).get(col)
            kind = edit_kind(source, col, cell) if cell is not None else None
            wrong_type = (kind == "number" and isinstance(value, str)) or (
                kind == "text" and value is not None and not isinstance(value, str)
            )
            if row not in kept or kind is None or wrong_type:
                unmappable.append(f"{col}{row}")
            excel_edits[(row, col)] = (value, original)
        if unmappable:
            raise ImportStopped(
                f"{len(unmappable)} saved edit(s) are outside the imported company list or not in an editable"
                f" GFI column ({', '.join(unmappable)}). They would be lost, so nothing was imported."
            )
        if not replaced:
            logger.info("Saved edits in SQLite for %s: %d (all will be carried over)", path.name, len(sqlite_edits))
        expected = build_company_table(source, excel_edits)

        if session.get(ReportingYear, year) is None:
            session.add(ReportingYear(year=year))
        source_file = SourceFile(
            kind="gfi", year=year, file_name=path.name, sheet_name=source.sheet,
            sha256=hashlib.sha256(content).digest(),
            file_mtime=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
            imported_at=now, imported_by=user,
        )
        session.add(source_file)
        session.flush()

        session.add_all(
            GfiColumn(source_file_id=source_file.id, col=col, position=i, header=header, field=field_of.get(col))
            for i, (col, header) in enumerate(source.headers.items())
        )
        session.add_all(
            SourceCell(
                source_file_id=source_file.id, row=row, col=col, is_formula=cell.is_formula,
                number_format=cell.number_format, **_cell_columns(cell.value),
            )
            for row in kept
            for col, cell in source.rows[row].items()
        )

        issues: list[ImportIssue] = []

        def issue(row: int, col: str | None, message: str) -> None:
            issues.append(ImportIssue(source_file_id=source_file.id, row=row, col=col, message=message))

        pib_rows = collections.defaultdict(list)
        referents: dict[str, int] = {}
        offices: dict[str, int] = {}
        company_years: dict[int, CompanyYear] = {}
        for row in kept:
            cells = source.rows[row]
            name = cells[col_of["name"]].value
            pib_value = cells[col_of["pib"]].value
            pib = None if pib_value is None or str(pib_value).strip() == "" else str(pib_value)
            if pib is None:
                issue(row, col_of["pib"], "No PIB")
            else:
                pib_rows[pib.strip()].append(row)
                if not PIB_PATTERN.match(pib.strip()):
                    issue(row, col_of["pib"], f"PIB is not 9 digits: {pib!r}")
            company = Company(name=str(name), pib=pib, created_at=now)
            session.add(company)

            values = {}
            for field in NUMERIC_FIELDS:
                value = cells[col_of[field]].value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[field] = to_decimal(value)
                elif value is not None:
                    issue(row, col_of[field], f"Not a number: {value!r} (kept in the snapshot only)")
            referent_id = office_id = None
            for field, model, cache in (("referent", Referent, referents), (OFFICE_FIELD, Office, offices)):
                value = cells[col_of[field]].value
                if value is not None and not isinstance(value, str):
                    issue(row, col_of[field], f"Not text: {value!r} (stored as text)")
                    value = str(value)
                if value is not None and value.strip():
                    lookup_id = _lookup(session, model, cache, value)
                    referent_id, office_id = (lookup_id, office_id) if field == "referent" else (referent_id, lookup_id)
            company_year = CompanyYear(
                company=company, year=year, source_file_id=source_file.id, source_row=row,
                name=str(name), referent_id=referent_id, office_id=office_id, **values,
            )
            session.add(company_year)
            company_years[row] = company_year

        for pib, rows in pib_rows.items():
            if len(rows) > 1:
                for row in rows:
                    others = ", ".join(str(source.rows[r][col_of["name"]].value) for r in rows if r != row)
                    issue(row, col_of["pib"], f"PIB {pib} is also used by: {others}")
        session.add_all(issues)
        session.flush()

        for row, col, value, original, updated_by, updated_at in sqlite_edits:
            company_year, field = company_years[row], field_of[col]
            excel_value = source.rows[row][col].value
            if original != excel_value:
                logger.warning("Edit %s%d was made when the Excel value was %r (now %r); keeping the edit", col, row, original, excel_value)
            changed_at = datetime.fromisoformat(updated_at)
            log = ChangeLog(
                company_year_id=company_year.id, year=year, source_row=row, col=col, field=field,
                changed_by=updated_by, changed_at=changed_at,
            )
            if field in TEXT_FIELDS:
                log.old_text, log.new_text = current_text(company_year, field), value
                set_text(session, company_year, field, value)
            else:
                log.old_value, log.new_value = getattr(company_year, field), to_decimal(value)
                setattr(company_year, field, log.new_value)
            session.add(log)
            company_year.updated_at, company_year.updated_by = changed_at, updated_by
        session.flush()

        # PB-1 links (which company a PB-1 file belongs to) carried over by company identity.
        # A link to a row outside the company list is not carried (it is made again when needed).
        for pb1_workbook, pb1_company, gfi_row, linked_by, linked_at in _read_sqlite_pb1_links(year, source.workbook):
            if gfi_row in company_years:
                session.merge(Pb1Link(
                    year=year, pb1_file_name=pb1_workbook, pb1_company=pb1_company,
                    company_year_id=company_years[gfi_row].id, linked_by=linked_by,
                    linked_at=datetime.fromisoformat(linked_at),
                ))
                logger.info("PB-1 link carried over: %s -> row %d", pb1_workbook, gfi_row)
            else:
                logger.warning("PB-1 link of %s points outside the company list (row %d); not carried over", pb1_workbook, gfi_row)
        session.flush()
        _remove_unused(session)

        known = _verify(session, year, expected, kept, field_of)
        logger.info("Verification passed: all %d rows x %d columns match Excel + SQLite", len(kept), len(source.headers))
        for reason, count in known.items():
            logger.info("  intended difference: %s (%d cells)", reason, count)
        logger.info("Import issues: %d", len(issues))
        for item in issues:
            logger.info("  row %s %s: %s", item.row, item.col or "", item.message)
        logger.info(
            "Imported: %d companies, %d referents, %d offices, %d cells, %d edits",
            len(kept), len(referents), len(offices), len(kept) * len(source.headers), len(sqlite_edits),
        )
        if dry_run:
            raise DryRunDone


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a GFI workbook into PostgreSQL.")
    parser.add_argument("year", type=int)
    parser.add_argument("--replace", action="store_true", help="replace an earlier import of this year (only if it has no changed values)")
    parser.add_argument("--dry-run", action="store_true", help="run and verify everything, then roll back")
    parser.add_argument("--user", default=getpass.getuser(), help="recorded as imported_by")
    args = parser.parse_args()

    setup_logging()
    if not database_enabled():
        logger.error("DATABASE_URL is not set (backend/.env). See backend/.env.example.")
        return 2
    logger.info("Database: %s", describe_database())
    try:
        import_year(args.year, args.replace, args.dry_run, args.user)
    except DryRunDone:
        logger.info("Dry run: everything checked, nothing was saved")
        return 0
    except ImportStopped as exc:
        logger.error("Import stopped, nothing was saved: %s", exc)
        return 1
    logger.info("Import of %s committed", args.year)
    return 0


if __name__ == "__main__":
    sys.exit(main())
