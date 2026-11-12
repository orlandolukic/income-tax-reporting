"""PostgreSQL connection (SQLAlchemy 2 + psycopg 3).

The database is used when DATABASE_URL is set, e.g.
    DATABASE_URL=postgresql://income_tax:<password>@localhost:5432/income_tax_reporting
Without it the app keeps reading GFI data from the Excel workbooks (edits in SQLite).
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session


def get_database_url() -> str | None:
    url = os.getenv("DATABASE_URL", "").strip()
    return url or None


def database_enabled() -> bool:
    return get_database_url() is not None


def _sqlalchemy_url(url: str) -> str:
    # Use the psycopg 3 driver for plain postgresql:// / postgres:// URLs.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@cache
def _engine(url: str) -> Engine:
    engine = create_engine(_sqlalchemy_url(url), pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        # SQLite is only used for local tests; enforce foreign keys (ON DELETE CASCADE) like PostgreSQL.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys = ON")

    return engine


def get_engine() -> Engine:
    url = get_database_url()
    if url is None:
        raise RuntimeError("DATABASE_URL is not set")
    return _engine(url)


def describe_database() -> str:
    """Database URL for logs, with the password hidden."""
    return get_engine().url.render_as_string(hide_password=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session in one transaction: committed on success, rolled back on error."""
    with Session(get_engine()) as session, session.begin():
        yield session
