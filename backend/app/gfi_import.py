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
3. Write the snapshot (source_file, gfi_column, source_cell), companies, company years,
   referents, offices and import issues. Companies, referents and offices no longer used
   are removed.
4. Verify: build the GFI table from the database and compare every cell with the table
   built from the workbook (value, format, formula, editable, edited, original).

The Excel file is never written. (The 2025 import of 2026-11-12 also carried over the edits
saved before PostgreSQL in the old SQLite store, deleted on 2026-11-13.)
"""

import argparse
import collections
import dataclasses
import getpass
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.settings import load_settings

load_settings()

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.companies import CompanyTable, build_company_table  # noqa: E402
from app.db import database_enabled, describe_database, session_scope  # noqa: E402
from app.gfi_store import (  # noqa: E402
    OFFICE_FIELD,
    load_table,
    map_columns,
    to_decimal,
)
from app.gfi_table import SourceTable  # noqa: E402
from app.gfi_workbook import company_list, find_workbooks, get_data_dir, main_list_rows, read_source_table  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.models import (  # noqa: E402
    NUMERIC_FIELDS,
    Company,
    CompanyYear,
    GfiColumn,
    ImportIssue,
    Office,
    Pb1CompanyEdit,
    Pb1ReportState,
    Referent,
    ReportingYear,
    SourceCell,
    SourceFile,
)

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
    source, edits = load_table(session, year)
    # The status columns follow the PB-1 report steps, not the workbook: not a lost value here
    # (the steps themselves are checked below).
    edits = {k: v for k, v in edits.items() if source.fields.get(k[1]) not in NUMERIC_FIELDS}
    if edits:
        listed = ", ".join(f"{col}{row}" for row, col in sorted(edits))
        raise ImportStopped(
            f"The earlier {year} import has {len(edits)} value(s) changed in the database ({listed})."
            " Replacing it would lose them, so nothing was changed."
        )
    pb1_values = session.scalar(
        select(func.count()).select_from(Pb1CompanyEdit).join(CompanyYear).where(CompanyYear.year == year)
    )
    steps = session.scalar(
        select(func.count()).select_from(Pb1ReportState).join(CompanyYear).where(CompanyYear.year == year)
    )
    if steps:
        raise ImportStopped(
            f"{steps} {year} companies have PB-1 report steps stored."
            " Replacing the GFI import would lose them, so nothing was changed."
        )
    if pb1_values:
        raise ImportStopped(
            f"{pb1_values} PB-1 value(s) of {year} companies are stored in the database."
            " Replacing the GFI import would lose them, so nothing was changed."
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
    """Compare the table built from the database with the table built from the workbook."""
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
                problems.append(f"{col}{row}: Excel {want} != database {got}")

    if problems:
        shown = "\n  ".join(problems[:20])
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise ImportStopped(f"Verification failed, {len(problems)} difference(s):\n  {shown}{more}")
    return known


def _statuses_not_empty(source: SourceTable, field_of: dict[str, str]) -> SourceTable:
    """Status columns are never empty (user's rule): an empty or blank cell of the workbook is
    imported as 0 (snapshot and current value). Any other value than 0 / 1 stops the import."""
    status_cols = [col for col, field in field_of.items() if field in NUMERIC_FIELDS]
    wrong = []
    rows = {}
    for row, cells in source.rows.items():
        cells = dict(cells)
        for col in status_cols:
            cell = cells[col]
            value = cell.value
            if value is None or (isinstance(value, str) and not value.strip()):
                cells[col] = dataclasses.replace(cell, value=0)
            elif isinstance(value, bool) or value not in (0, 1):
                wrong.append(f"{col}{row}={value!r}")
        rows[row] = cells
    if wrong:
        raise ImportStopped(f"Status cells must be 0 or 1 (or empty): {', '.join(wrong[:20])}")
    return dataclasses.replace(source, rows=rows)


def _details_upper_case(source: SourceTable, field_of: dict[str, str]) -> SourceTable:
    """NAZIV, REFERENT and office are stored in upper case (user's rule, 2026-11-14), snapshot and
    current value alike; a REFERENT / office written as "-" is empty ("-" is how the app shows an
    empty detail)."""
    cols = {col: field for col, field in field_of.items() if field in ("name", "referent", OFFICE_FIELD)}
    rows = {}
    for row, cells in source.rows.items():
        cells = dict(cells)
        for col, field in cols.items():
            value = cells[col].value
            if not isinstance(value, str):
                continue
            new = None if field != "name" and value.strip() == "-" else value.upper()
            if new != value:
                cells[col] = dataclasses.replace(cells[col], value=new)
        rows[row] = cells
    return dataclasses.replace(source, rows=rows)


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
    source = _statuses_not_empty(source, field_of)
    source = _details_upper_case(source, field_of)
    col_of = {field: col for col, field in field_of.items()}
    last = source.rows[kept[-1]][col_of["name"]].value
    logger.info("%s: %d companies (Excel rows %d-%d), last: #%d %s", path.name, len(kept), kept[0], kept[-1], len(kept), last)

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        _remove_previous_import(session, year, replace)

        expected = build_company_table(source, {})

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

            # The status columns are set only by the PB-1 report steps (user, 2026-11-17): a
            # company without steps has 0 everywhere; the workbook's values stay in the snapshot.
            values = {field: to_decimal(0) for field in NUMERIC_FIELDS}
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

        _remove_unused(session)

        known = _verify(session, year, expected, kept, field_of)
        logger.info("Verification passed: all %d rows x %d columns match the workbook", len(kept), len(source.headers))
        for reason, count in known.items():
            logger.info("  intended difference: %s (%d cells)", reason, count)
        logger.info("Import issues: %d", len(issues))
        for item in issues:
            logger.info("  row %s %s: %s", item.row, item.col or "", item.message)
        logger.info(
            "Imported: %d companies, %d referents, %d offices, %d cells",
            len(kept), len(referents), len(offices), len(kept) * len(source.headers),
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
