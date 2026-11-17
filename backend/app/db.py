"""PostgreSQL connection (SQLAlchemy 2 + psycopg 3).

All data of the app is in this database; DATABASE_URL (backend/.env) is required, e.g.
    DATABASE_URL=postgresql://income_tax:<password>@localhost:5432/income_tax_reporting
The backend doesn't start without it.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from sqlalchemy import Engine, create_engine
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
    if engine.dialect.name != "postgresql":
        # PostgreSQL is the only store of the app's data (no SQLite or other database).
        raise RuntimeError(f"DATABASE_URL must be a PostgreSQL database, not {engine.dialect.name}")
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
