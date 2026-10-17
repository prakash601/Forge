"""Users service.

Functions over the ``users`` table. Each function is a thin wrapper
that owns no transaction; the caller (API layer or repository code)
manages ``session.commit()``.

Design note
-----------
``email`` is unique at the database level. We do not pre-check
uniqueness in the service because that would race; we catch the
``IntegrityError`` raised by the unique-index violation and translate
it to :class:`DuplicateUserEmailError`. This is the standard SQLAlchemy
pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.errors import (
    DuplicateUserEmailError,
    GitHubAccountLinkedError,
    UserNotFoundError,
)
from app.users.models import User


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str | None = None,
) -> User:
    """Create a new user. Raises :class:`DuplicateUserEmailError` if email taken."""
    if not email or not email.strip():
        raise ValueError("email must be a non-empty string")
    now = datetime.now(UTC)
    user = User(
        email=email.strip().lower(),
        display_name=(display_name.strip() if display_name else None) or None,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Email is the only unique constraint in this table; any
        # IntegrityError here is a duplicate-email collision.
        raise DuplicateUserEmailError(email) from exc
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Return the user with ``user_id`` or raise :class:`UserNotFoundError`."""
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFoundError(str(user_id))
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User:
    """Return the user with ``email`` or raise :class:`UserNotFoundError`.

    Emails are stored normalized (lowercased, trimmed), so callers
    should pass the same form. This is a convenience for the future
    auth flow; not used in this issue's API surface.
    """
    result = await session.execute(select(User).where(User.email == email.strip().lower()))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(email)
    return user


async def get_user_by_github_id(session: AsyncSession, github_id: int) -> User:
    """Return the user linked to ``github_id`` or raise :class:`UserNotFoundError`."""
    result = await session.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(f"github:{github_id}")
    return user


async def link_github_account(
    session: AsyncSession,
    *,
    email: str,
    github_id: int,
    display_name: str | None = None,
    encrypted_token: str | None = None,
) -> tuple[User, bool]:
    """Find-or-create a user by verified email and link the GitHub account.

    The caller must have verified the email with the OAuth provider
    (GitHub ``verified=true`` primary email); this function trusts it.

    Matching rules (both lookups run before any write):

    * Same user owns the email and the GitHub id → refresh token.
    * GitHub id known, email new → the user changed their GitHub
      primary email: update it.
    * Email known, GitHub id new → link the GitHub account.
    * Email and GitHub id owned by *different* users → refuse with
      :class:`GitHubAccountLinkedError` (no mutation).
    * Neither known → create.

    Returns ``(user, created)`` and refreshes the stored encrypted
    token on every login. Residual write races are guarded by
    savepoints and disambiguated into :class:`GitHubAccountLinkedError`
    / :class:`DuplicateUserEmailError`.
    """
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email must be a non-empty string")
    now = datetime.now(UTC)
    try:
        github_owner = await get_user_by_github_id(session, github_id)
    except UserNotFoundError:
        github_owner = None
    try:
        email_owner = await get_user_by_email(session, normalized)
    except UserNotFoundError:
        email_owner = None

    if github_owner is not None and email_owner is not None:
        if github_owner.id != email_owner.id:
            raise GitHubAccountLinkedError(github_id)
        user = github_owner
        user.updated_at = now
        if display_name and not user.display_name:
            user.display_name = display_name.strip() or None
        if encrypted_token is not None:
            user.github_token_encrypted = encrypted_token
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:  # pragma: no cover - race backstop
            raise GitHubAccountLinkedError(github_id) from exc
        return user, False

    if github_owner is not None:
        # Email change on the GitHub side: same account, new primary email.
        user = github_owner
        user.email = normalized
        user.updated_at = now
        if display_name and not user.display_name:
            user.display_name = display_name.strip() or None
        if encrypted_token is not None:
            user.github_token_encrypted = encrypted_token
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:
            # The new email belongs to a different user.
            raise DuplicateUserEmailError(normalized) from exc
        return user, False

    if email_owner is not None:
        user = email_owner
        user.github_id = github_id
        user.updated_at = now
        if display_name and not user.display_name:
            user.display_name = display_name.strip() or None
        if encrypted_token is not None:
            user.github_token_encrypted = encrypted_token
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:  # pragma: no cover - race backstop
            raise GitHubAccountLinkedError(github_id) from exc
        return user, False

    user = User(
        email=normalized,
        display_name=(display_name.strip() if display_name else None) or None,
        github_id=github_id,
        github_token_encrypted=encrypted_token,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        # Either the email or the github_id was taken concurrently.
        # Disambiguate so callers (and the API layer) report correctly.
        # The savepoint rolled back only the failed insert; the outer
        # transaction is intact, so these lookups are safe.
        try:
            await get_user_by_github_id(session, github_id)
        except UserNotFoundError:
            raise DuplicateUserEmailError(normalized) from exc
        raise GitHubAccountLinkedError(github_id) from exc
    return user, True


__all__ = [
    "create_user",
    "get_user",
    "get_user_by_email",
    "get_user_by_github_id",
    "link_github_account",
]
