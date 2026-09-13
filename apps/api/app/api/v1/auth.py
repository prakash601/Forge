"""HTTP endpoints for auth (v1, Phase 4 Issue #015).

* ``GET /api/v1/auth/github/login`` — 307 to the GitHub authorize URL.
* ``GET /api/v1/auth/github/callback`` — exchange → link → session cookie.
* ``GET /api/v1/auth/me`` — the caller (401 without a valid session).
* ``POST /api/v1/auth/logout`` — clear the session cookie.

OAuth itself runs through the :mod:`app.auth.github` seam; tests
override :func:`get_oauth_client` with the fake (no network in CI).
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import cipher_or_503, get_current_user
from app.auth.errors import (
    GitHubOAuthError,
    NoGitHubEmailError,
    UnverifiedEmailError,
)
from app.auth.github import GitHubOAuthClient, RealGitHubOAuthClient
from app.auth.schemas import AuthStatus
from app.auth.service import handle_oauth_callback
from app.auth.tokens import SESSION_COOKIE
from app.core.logging import get_logger
from app.db.session import get_session
from app.users.errors import DuplicateUserEmailError, GitHubAccountLinkedError
from app.users.models import User
from app.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _not_configured(request: Request, missing: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "AUTH_NOT_CONFIGURED",
            "message": f"Auth is not configured (missing {missing}).",
            "request_id": request.state.request_id,
        },
    )


async def get_oauth_client(request: Request) -> GitHubOAuthClient:
    """Build the OAuth client from settings, or 503 when unconfigured.

    Overridden in tests with :class:`FakeGitHubOAuthClient` via
    ``app.dependency_overrides``.
    """
    settings = request.app.state.settings
    if not settings.github_client_id or not settings.github_client_secret:
        raise _not_configured(request, "GitHub OAuth credentials")
    return RealGitHubOAuthClient(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
    )


def _set_session_cookie(response: Response, *, token: str, request: Request) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.jwt_expiry_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )


@router.get(
    "/github/login",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="Redirect to GitHub OAuth authorize.",
    responses={503: {"description": "GitHub OAuth is not configured."}},
)
async def github_login(
    request: Request,
    client: Annotated[GitHubOAuthClient, Depends(get_oauth_client)],
) -> Response:
    settings = request.app.state.settings
    state = secrets.token_urlsafe(16)
    url = client.login_url(redirect_uri=settings.github_oauth_callback_url, state=state)
    return Response(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"location": url})


@router.get(
    "/github/callback",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Complete GitHub OAuth login and set the session cookie.",
    responses={
        400: {"description": "OAuth or email verification failure."},
        409: {"description": "Email taken or GitHub account linked elsewhere."},
        503: {"description": "Auth is not configured."},
    },
)
async def github_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[GitHubOAuthClient, Depends(get_oauth_client)],
    code: str,
) -> Response:
    settings = request.app.state.settings
    if not settings.jwt_secret:
        raise _not_configured(request, "jwt_secret")
    cipher = cipher_or_503(request)
    try:
        user, token = await handle_oauth_callback(
            session,
            client=client,
            code=code,
            redirect_uri=settings.github_oauth_callback_url,
            cipher=cipher,
            jwt_secret=settings.jwt_secret,
            jwt_expiry_seconds=settings.jwt_expiry_seconds,
        )
    except (GitHubOAuthError, NoGitHubEmailError, UnverifiedEmailError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "OAUTH_FAILED",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
    except (DuplicateUserEmailError, GitHubAccountLinkedError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICT",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
    await session.commit()
    log.info("user_logged_in", user_id=str(user.id), request_id=request.state.request_id)
    body = UserRead.model_validate(user).model_dump_json().encode("utf-8")
    response = Response(content=body, media_type="application/json")
    _set_session_cookie(response, token=token, request=request)
    return response


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Read the authenticated caller.",
    responses={401: {"description": "No valid session."}},
)
async def read_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserRead:
    return UserRead.model_validate(current_user)


@router.post(
    "/logout",
    response_model=AuthStatus,
    status_code=status.HTTP_200_OK,
    summary="Clear the session cookie.",
)
async def logout(request: Request) -> Response:
    body = AuthStatus(ok=True).model_dump_json().encode("utf-8")
    response = Response(content=body, media_type="application/json")
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    log.info("user_logged_out", request_id=request.state.request_id)
    return response


__all__ = ["get_oauth_client", "router"]
