"""SQLite storage for user edits of workbook cells (used while PostgreSQL is not configured).

The original Excel files are never modified; an edit overrides one cell's value.
Numbers are stored in value / original_value, text (company name, PIB, referent,
office) in value_text / original_text. Both NULL = the cell was cleared.

Also holds pb1_links: which GFI company (row of the company list) a PB-1 file belongs to.
Database file: DATABASE_PATH (default: backend/data/edits.db).
"""

import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "edits.db"

CellValue = str | int | float | bool | None

SCHEMA = """
CREATE TABLE IF NOT EXISTS cell_edits (
    workbook       TEXT    NOT NULL,  -- workbook file name, e.g. "2025 GFI TOKK 1.xlsx"
    sheet          TEXT    NOT NULL,
    row            INTEGER NOT NULL,  -- Excel row number
    col            TEXT    NOT NULL,  -- Excel column letter
    value          REAL,              -- edited number (NULL = cleared or text)
    original_value REAL,              -- Excel number when the edit was made
    updated_by     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,  -- ISO 8601, UTC
    value_text     TEXT,              -- edited text (NULL = cleared or number)
    original_text  TEXT,              -- Excel text when the edit was made
    PRIMARY KEY (workbook, sheet, row, col)
)
"""
PB1_LINKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pb1_links (
    year          INTEGER NOT NULL,
    pb1_workbook  TEXT    NOT NULL,  -- PB-1 file name, e.g. "2025 PB-1.xls"
    pb1_company   TEXT    NOT NULL,  -- company name as written in the PB-1 file when linked
    gfi_workbook  TEXT    NOT NULL,  -- GFI workbook the row belongs to
    gfi_row       INTEGER NOT NULL,  -- Excel row of the company in the GFI company list
    linked_by     TEXT    NOT NULL,
    linked_at     TEXT    NOT NULL,  -- ISO 8601, UTC
    PRIMARY KEY (year, pb1_workbook)
)
"""
# Columns added after the first version; added in place to existing databases.
ADDED_COLUMNS = {"value_text": "TEXT", "original_text": "TEXT"}


def get_database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH))


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(get_database_path())


def init_db() -> None:
    path = get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(cell_edits)")}
        missing = [name for name in ADDED_COLUMNS if existing and name not in existing]
        if missing:
            # Older database: keep a copy, then add the columns (existing edits are kept as they are).
            backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
            shutil.copy2(path, backup)
            logger.info("Edits database backed up to %s before adding columns %s", backup.name, missing)
        with conn:
            conn.execute(SCHEMA)
            conn.execute(PB1_LINKS_SCHEMA)
            conn.execute(PB1_EDITS_SCHEMA)
            conn.execute(PB1_COMMENT_DEFAULTS_SCHEMA)
            for name in missing:
                conn.execute(f"ALTER TABLE cell_edits ADD COLUMN {name} {ADDED_COLUMNS[name]}")
    logger.info("Edits database ready: %s", path)


def _split(value: CellValue) -> tuple[float | None, str | None]:
    """(number, text) columns for a value."""
    if isinstance(value, str):
        return None, value
    if isinstance(value, bool) or value is None:
        return None, None
    return float(value), None


def get_edits(workbook: str, sheet: str) -> dict[tuple[int, str], tuple[CellValue, CellValue]]:
    """Return {(row, col): (value, original_value)} for one sheet."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT row, col, value, value_text, original_value, original_text"
            " FROM cell_edits WHERE workbook = ? AND sheet = ?",
            (workbook, sheet),
        ).fetchall()
    return {
        (row, col): (text if text is not None else number, original_text if original_text is not None else original)
        for row, col, number, text, original, original_text in rows
    }


def save_edit(
    workbook: str, sheet: str, row: int, col: str, value: CellValue, original_value: CellValue, user: str
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    number, text = _split(value)
    original_number, original_text = _split(original_value)
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO cell_edits
                (workbook, sheet, row, col, value, original_value, updated_by, updated_at, value_text, original_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (workbook, sheet, row, col) DO UPDATE SET
                value = excluded.value,
                original_value = excluded.original_value,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at,
                value_text = excluded.value_text,
                original_text = excluded.original_text
            """,
            (workbook, sheet, row, col, number, original_number, user, now, text, original_text),
        )


def delete_edit(workbook: str, sheet: str, row: int, col: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "DELETE FROM cell_edits WHERE workbook = ? AND sheet = ? AND row = ? AND col = ?",
            (workbook, sheet, row, col),
        )


def get_pb1_link(year: int, pb1_workbook: str) -> tuple[str, str, int] | None:
    """(pb1_company, gfi_workbook, gfi_row) of a PB-1 file, or None."""
    with closing(_connect()) as conn:
        conn.execute(PB1_LINKS_SCHEMA)
        return conn.execute(
            "SELECT pb1_company, gfi_workbook, gfi_row FROM pb1_links WHERE year = ? AND pb1_workbook = ?",
            (year, pb1_workbook),
        ).fetchone()


def save_pb1_link(year: int, pb1_workbook: str, pb1_company: str, gfi_workbook: str, gfi_row: int, user: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect()) as conn, conn:
        conn.execute(PB1_LINKS_SCHEMA)
        conn.execute(
            """
            INSERT INTO pb1_links (year, pb1_workbook, pb1_company, gfi_workbook, gfi_row, linked_by, linked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (year, pb1_workbook) DO UPDATE SET
                pb1_company = excluded.pb1_company, gfi_workbook = excluded.gfi_workbook,
                gfi_row = excluded.gfi_row, linked_by = excluded.linked_by, linked_at = excluded.linked_at
            """,
            (year, pb1_workbook, pb1_company, gfi_workbook, gfi_row, user, now),
        )


def delete_pb1_link(year: int, pb1_workbook: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(PB1_LINKS_SCHEMA)
        conn.execute("DELETE FROM pb1_links WHERE year = ? AND pb1_workbook = ?", (year, pb1_workbook))


# PB-1 form edits (the PB-1 workbook is never written). An amount belongs to one company
# (gfi_workbook + gfi_row: the company's identity in the GFI company list); a template field
# (description, comment, konto) is shared by every company (gfi_workbook "" and gfi_row 0).
PB1_EDITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pb1_edits (
    year           INTEGER NOT NULL,
    pb1_workbook   TEXT    NOT NULL,  -- PB-1 file name, e.g. "2025 PB-1.xls"
    tab            TEXT    NOT NULL,  -- "poreski-bilans" | "uporedo" | "preliminarni"
    row            INTEGER NOT NULL,  -- Excel row of the form
    col            TEXT    NOT NULL,  -- Excel column letter
    gfi_workbook   TEXT    NOT NULL,  -- company (amounts); "" for template fields
    gfi_row        INTEGER NOT NULL,  -- company's GFI row (amounts); 0 for template fields
    value          REAL,              -- edited number (NULL = cleared or text)
    value_text     TEXT,              -- edited text (NULL = cleared or number)
    original_value REAL,              -- value shown before the first edit (number)
    original_text  TEXT,              -- value shown before the first edit (text)
    updated_by     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,  -- ISO 8601, UTC
    PRIMARY KEY (year, pb1_workbook, tab, row, col, gfi_workbook, gfi_row)
)
"""
TEMPLATE_COMPANY = ("", 0)  # gfi_workbook, gfi_row of a template (shared) edit

# (row, col) -> (value, original value)
Pb1Edits = dict[tuple[int, str], tuple[CellValue, CellValue]]


def get_pb1_edits(year: int, pb1_workbook: str, tab: str, gfi_workbook: str, gfi_row: int) -> Pb1Edits:
    """Edits of one PB-1 tab for one company (gfi_workbook, gfi_row), or the template
    edits with TEMPLATE_COMPANY."""
    with closing(_connect()) as conn:
        conn.execute(PB1_EDITS_SCHEMA)
        rows = conn.execute(
            "SELECT row, col, value, value_text, original_value, original_text FROM pb1_edits"
            " WHERE year = ? AND pb1_workbook = ? AND tab = ? AND gfi_workbook = ? AND gfi_row = ?",
            (year, pb1_workbook, tab, gfi_workbook, gfi_row),
        ).fetchall()
    return {
        (row, col): (text if text is not None else number, original_text if original_text is not None else original)
        for row, col, number, text, original, original_text in rows
    }


def save_pb1_edit(
    year: int, pb1_workbook: str, tab: str, row: int, col: str, gfi_workbook: str, gfi_row: int,
    value: CellValue, original_value: CellValue, user: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    number, text = _split(value)
    original_number, original_text = _split(original_value)
    with closing(_connect()) as conn, conn:
        conn.execute(PB1_EDITS_SCHEMA)
        conn.execute(
            """
            INSERT INTO pb1_edits (year, pb1_workbook, tab, row, col, gfi_workbook, gfi_row,
                value, value_text, original_value, original_text, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (year, pb1_workbook, tab, row, col, gfi_workbook, gfi_row) DO UPDATE SET
                value = excluded.value, value_text = excluded.value_text,
                updated_by = excluded.updated_by, updated_at = excluded.updated_at
            """,
            (year, pb1_workbook, tab, row, col, gfi_workbook, gfi_row,
             number, text, original_number, original_text, user, now),
        )


def delete_pb1_edit(year: int, pb1_workbook: str, tab: str, row: int, col: str, gfi_workbook: str, gfi_row: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(PB1_EDITS_SCHEMA)
        conn.execute(
            "DELETE FROM pb1_edits WHERE year = ? AND pb1_workbook = ? AND tab = ? AND row = ? AND col = ?"
            " AND gfi_workbook = ? AND gfi_row = ?",
            (year, pb1_workbook, tab, row, col, gfi_workbook, gfi_row),
        )


# PB-1 comment settings: the default comment of each form row (column "Komentar, stopa, konto"),
# taken once from the PB-1 workbook. A company's own comment is a pb1_edits row of that column
# (company scope) and replaces the default for that company only.
PB1_COMMENT_DEFAULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pb1_comment_defaults (
    year          INTEGER NOT NULL,
    pb1_workbook  TEXT    NOT NULL,  -- PB-1 file name, e.g. "2025 PB-1.xls"
    tab           TEXT    NOT NULL,
    row           INTEGER NOT NULL,  -- Excel row of the form
    value         REAL,              -- number (e.g. a rate 0.05)
    value_text    TEXT,              -- text (a comment, konto numbers)
    source        TEXT    NOT NULL,  -- "workbook": taken from the PB-1 file
    updated_by    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,  -- ISO 8601, UTC
    PRIMARY KEY (year, pb1_workbook, tab, row)
)
"""


def seed_pb1_comment_defaults(
    year: int, pb1_workbook: str, tab: str, values: dict[int, CellValue], user: str
) -> int:
    """Stores the default comments taken from the workbook for rows that have none yet (an
    existing default is never overwritten). Returns the number of rows added."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect()) as conn, conn:
        conn.execute(PB1_COMMENT_DEFAULTS_SCHEMA)
        before = conn.total_changes
        for row, value in values.items():
            number, text = _split(value)
            conn.execute(
                "INSERT OR IGNORE INTO pb1_comment_defaults"
                " (year, pb1_workbook, tab, row, value, value_text, source, updated_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'workbook', ?, ?)",
                (year, pb1_workbook, tab, row, number, text, user, now),
            )
        return conn.total_changes - before


def get_pb1_comment_defaults(year: int, pb1_workbook: str, tab: str) -> dict[int, CellValue]:
    """Default comment of each row of one PB-1 tab (row -> number or text)."""
    with closing(_connect()) as conn:
        conn.execute(PB1_COMMENT_DEFAULTS_SCHEMA)
        rows = conn.execute(
            "SELECT row, value, value_text FROM pb1_comment_defaults WHERE year = ? AND pb1_workbook = ? AND tab = ?",
            (year, pb1_workbook, tab),
        ).fetchall()
    return {row: text if text is not None else number for row, number, text in rows}


def copy_pb1_form_settings(from_year: int, from_workbook: str, to_year: int, to_workbook: str, user: str) -> tuple[int, int]:
    """For a constructed year's PB-1 form (Migracija): copies the form-level settings of the
    year it is built from, as they are in the app: the shared template edits (comments, konto,
    ... changed for every company) and the default comments. Company amounts and company
    comments are not copied. Existing rows of the new year are kept. Returns (edits, defaults)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect()) as conn, conn:
        conn.execute(PB1_EDITS_SCHEMA)
        conn.execute(PB1_COMMENT_DEFAULTS_SCHEMA)
        edits = conn.execute(
            """
            INSERT OR IGNORE INTO pb1_edits (year, pb1_workbook, tab, row, col, gfi_workbook, gfi_row,
                value, value_text, original_value, original_text, updated_by, updated_at)
            SELECT ?, ?, tab, row, col, gfi_workbook, gfi_row, value, value_text, original_value, original_text, ?, ?
            FROM pb1_edits WHERE year = ? AND pb1_workbook = ? AND gfi_workbook = ? AND gfi_row = ?
            """,
            (to_year, to_workbook, user, now, from_year, from_workbook, *TEMPLATE_COMPANY),
        ).rowcount
        defaults = conn.execute(
            """
            INSERT OR IGNORE INTO pb1_comment_defaults (year, pb1_workbook, tab, row, value, value_text, source,
                updated_by, updated_at)
            SELECT ?, ?, tab, row, value, value_text, ?, ?, ? FROM pb1_comment_defaults WHERE year = ? AND pb1_workbook = ?
            """,
            (to_year, to_workbook, f"year {from_year}", user, now, from_year, from_workbook),
        ).rowcount
    return edits, defaults
