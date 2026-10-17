"""FastAPI dependencies for auth (Phase 4, Issue #015).

:func:`get_current_user` resolves the caller from the session cookie
or the ``Authorization: Bearer`` header (same JWT both ways, per #56).
Missing/invalid tokens are 401; missing server configuration is 503.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import InvalidSessionTokenError
from app.auth.tokens import SESSION_COOKIE, TokenCipher, decode_session_token
from app.core.logging import get_logger
from app.db.session import get_session
from app.users.errors import UserNotFoundError
from app.users.models import User
from app.users.service import get_user

log = get_logger(__name__)


def _extract_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(SESSION_COOKIE)
    if cookie_token:
        return cookie_token
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _unauthorized(request: Request, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTHENTICATION_ERROR",
            "message": message,
            "request_id": request.state.request_id,
        },
    )


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Return the authenticated user or raise 401 (503 if unconfigured)."""
    settings = request.app.state.settings
    token = _extract_token(request)
    if token is None:
        raise _unauthorized(request, "Authentication required.")
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_NOT_CONFIGURED",
                "message": "Auth is not configured (missing jwt_secret).",
                "request_id": request.state.request_id,
            },
        )
    try:
        user_id = decode_session_token(token=token, secret=settings.jwt_secret)
    except (InvalidSessionTokenError, ValueError) as exc:
        raise _unauthorized(request, "Invalid or expired session.") from exc
    try:
        return await get_user(session, user_id)
    except UserNotFoundError as exc:
        raise _unauthorized(request, "Invalid or expired session.") from exc


def cipher_or_503(request: Request) -> TokenCipher:
    """Build the credential cipher from settings, or 503 when unconfigured."""
    settings = request.app.state.settings
    if not settings.credentials_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_NOT_CONFIGURED",
                "message": "Auth is not configured (missing credentials_key).",
                "request_id": request.state.request_id,
            },
        )
    try:
        return TokenCipher(settings.credentials_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_NOT_CONFIGURED",
                "message": "Auth is not configured (invalid credentials_key).",
                "request_id": request.state.request_id,
            },
        ) from exc


__all__ = ["cipher_or_503", "get_current_user"]
