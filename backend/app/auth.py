"""Authentication routes using server-side sessions (app.users) referenced by an HttpOnly cookie."""

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.logging_config import get_logger
from app.security import verify_password
from app.users import DUMMY_HASH, create_session, end_session, get_password_hash, session_user

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "session_id"


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
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Pogrešno korisničko ime ili lozinka.")

    token = secrets.token_urlsafe(32)
    create_session(token, credentials.username)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    logger.info("User '%s' logged in", credentials.username)
    return UserResponse(username=credentials.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, session_id: str | None = Cookie(default=None)) -> None:
    username = end_session(session_id) if session_id else None
    response.delete_cookie(SESSION_COOKIE)
    if username:
        logger.info("User '%s' logged out", username)
    else:
        logger.debug("Logout called without a valid session")


def require_user(session_id: str | None = Cookie(default=None)) -> str:
    """Dependency for protected endpoints: returns the logged-in username or raises 401."""
    username = session_user(session_id) if session_id else None
    if username is None:
        logger.debug("Session check failed: not authenticated")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Niste prijavljeni.")
    return username


@router.get("/me")
def me(username: str = Depends(require_user)) -> UserResponse:
    return UserResponse(username=username)
