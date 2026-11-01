"""SQLite storage for user edits of workbook cells.

The original Excel files are never modified; an edit overrides one cell's value.
Database file: DATABASE_PATH (default: backend/data/edits.db).
"""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "edits.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cell_edits (
    workbook       TEXT    NOT NULL,  -- workbook file name, e.g. "2025 GFI TOKK 1.xlsx"
    sheet          TEXT    NOT NULL,
    row            INTEGER NOT NULL,  -- Excel row number
    col            TEXT    NOT NULL,  -- Excel column letter
    value          REAL,              -- edited value (NULL = cleared)
    original_value REAL,              -- Excel value when the edit was made
    updated_by     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,  -- ISO 8601, UTC
    PRIMARY KEY (workbook, sheet, row, col)
)
"""


def get_database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH))


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(get_database_path())


def init_db() -> None:
    path = get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as conn, conn:
        conn.execute(SCHEMA)
    logger.info("Edits database ready: %s", path)


def get_edits(workbook: str, sheet: str) -> dict[tuple[int, str], tuple[float | None, float | None]]:
    """Return {(row, col): (value, original_value)} for one sheet."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT row, col, value, original_value FROM cell_edits WHERE workbook = ? AND sheet = ?",
            (workbook, sheet),
        ).fetchall()
    return {(row, col): (value, original) for row, col, value, original in rows}


def save_edit(
    workbook: str, sheet: str, row: int, col: str, value: float | None, original_value: float, user: str
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO cell_edits (workbook, sheet, row, col, value, original_value, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (workbook, sheet, row, col) DO UPDATE SET
                value = excluded.value,
                original_value = excluded.original_value,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (workbook, sheet, row, col, value, original_value, user, now),
        )


def delete_edit(workbook: str, sheet: str, row: int, col: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "DELETE FROM cell_edits WHERE workbook = ? AND sheet = ? AND row = ? AND col = ?",
            (workbook, sheet, row, col),
        )
