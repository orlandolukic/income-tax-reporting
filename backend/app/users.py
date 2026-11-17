"""Users and login sessions, in PostgreSQL: app_user (username, password hash, active) and
user_session (the SHA-256 of each session token, never the token itself), so logins survive a
backend restart.
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.db import session_scope
from app.models import AppUser, UserSession

# Verified against when the username is unknown, so response time doesn't reveal which usernames exist.
DUMMY_HASH = "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def get_password_hash(username: str) -> str | None:
    with session_scope() as session:
        return session.scalar(
            select(AppUser.password_hash).where(AppUser.username == username, AppUser.active)
        )


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def create_session(token: str, username: str) -> None:
    with session_scope() as session:
        session.add(UserSession(token_hash=_token_hash(token), username=username, created_at=datetime.now(timezone.utc)))


def session_user(token: str) -> str | None:
    """The user of a session token, or None (unknown token, or the user is no longer active)."""
    with session_scope() as session:
        return session.scalar(
            select(UserSession.username)
            .join(AppUser, AppUser.username == UserSession.username)
            .where(UserSession.token_hash == _token_hash(token), AppUser.active)
        )


def end_session(token: str) -> str | None:
    """Removes a session; returns its user, or None when there was none."""
    with session_scope() as session:
        return session.scalar(
            delete(UserSession).where(UserSession.token_hash == _token_hash(token)).returning(UserSession.username)
        )
