"""Auth service: the OAuth callback orchestration (Phase 4, Issue #015).

Owns no transaction; the API layer commits. Pure orchestration over
the OAuth client seam, the email-selection rule, user linking, and
session minting — each independently unit-testable.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.github import GitHubOAuthClient, select_primary_verified_email
from app.auth.tokens import TokenCipher, create_session_token
from app.users.models import User
from app.users.service import link_github_account


async def handle_oauth_callback(
    session: AsyncSession,
    *,
    client: GitHubOAuthClient,
    code: str,
    redirect_uri: str,
    cipher: TokenCipher,
    jwt_secret: str,
    jwt_expiry_seconds: int,
) -> tuple[User, str]:
    """Complete one OAuth login: exchange, verify, link, mint session.

    Returns ``(user, session_jwt)``. Raises the typed errors from
    :mod:`app.auth.github` and :mod:`app.users.service` on failure
    (unverified email, linked-elsewhere, provider errors).
    """
    access_token = await client.exchange_code(code=code, redirect_uri=redirect_uri)
    gh_user = await client.get_user(access_token=access_token)
    emails = await client.list_emails(access_token=access_token)
    email = select_primary_verified_email(emails)
    user, _created = await link_github_account(
        session,
        email=email,
        github_id=gh_user.id,
        display_name=gh_user.name or gh_user.login,
        encrypted_token=cipher.encrypt(access_token),
    )
    token = create_session_token(
        user_id=user.id,
        secret=jwt_secret,
        expires_in_seconds=jwt_expiry_seconds,
    )
    return user, token


__all__ = ["handle_oauth_callback"]
