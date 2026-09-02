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

from app.users.errors import DuplicateUserEmailError, UserNotFoundError
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


__all__ = ["create_user", "get_user", "get_user_by_email"]
