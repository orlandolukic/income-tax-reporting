"""Authentication routes using server-side sessions stored in an HttpOnly cookie."""

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.logging_config import get_logger
from app.security import verify_password
from app.users import DUMMY_HASH, get_password_hash

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "session_id"

# session token -> username. In memory: sessions are lost when the backend restarts.
_sessions: dict[str, str] = {}


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    username: str


@router.post("/login")
def login(credentials: LoginRequest, response: Response) -> UserResponse:
    stored_hash = get_password_hash(credentials.username)
    password_ok = verify_password(credentials.password, stored_hash or DUMMY_HASH)

    if stored_hash is None or not password_ok:
        logger.warning("Failed login attempt for username '%s'", credentials.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    token = secrets.token_urlsafe(32)
    _sessions[token] = credentials.username
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    logger.info("User '%s' logged in", credentials.username)
    return UserResponse(username=credentials.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, session_id: str | None = Cookie(default=None)) -> None:
    username = _sessions.pop(session_id, None) if session_id else None
    response.delete_cookie(SESSION_COOKIE)
    if username:
        logger.info("User '%s' logged out", username)
    else:
        logger.debug("Logout called without a valid session")


def require_user(session_id: str | None = Cookie(default=None)) -> str:
    """Dependency for protected endpoints: returns the logged-in username or raises 401."""
    username = _sessions.get(session_id) if session_id else None
    if username is None:
        logger.debug("Session check failed: not authenticated")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return username


@router.get("/me")
def me(username: str = Depends(require_user)) -> UserResponse:
    return UserResponse(username=username)
