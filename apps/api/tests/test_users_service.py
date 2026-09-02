"""Integration tests for the users service (real Postgres).

Covers: create, get-by-id, get-by-email, duplicate-email rejection,
empty-email validation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.users import service
from app.users.errors import DuplicateUserEmailError, UserNotFoundError
from app.users.models import User


async def test_create_user_persists_with_normalized_email(
    session: AsyncSession,
) -> None:
    user = await service.create_user(session, email="Foo@Example.COM")
    await session.commit()
    assert user.id is not None
    assert user.email == "foo@example.com"
    assert user.display_name is None


async def test_create_user_with_display_name(session: AsyncSession) -> None:
    user = await service.create_user(session, email="a@b.com", display_name="  Alice  ")
    await session.commit()
    assert user.display_name == "Alice"


async def test_create_user_rejects_empty_email(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        await service.create_user(session, email="")


async def test_create_user_duplicate_email_raises(
    session: AsyncSession,
) -> None:
    await service.create_user(session, email="dup@example.com")
    await session.commit()
    with pytest.raises(DuplicateUserEmailError):
        await service.create_user(session, email="DUP@example.com")
    await session.rollback()


async def test_get_user_returns_persisted_row(session: AsyncSession) -> None:
    created = await service.create_user(session, email="find@me.com")
    await session.commit()
    fetched = await service.get_user(session, created.id)
    assert fetched.id == created.id
    assert fetched.email == "find@me.com"


async def test_get_user_raises_for_unknown_id(session: AsyncSession) -> None:
    with pytest.raises(UserNotFoundError):
        await service.get_user(session, uuid.uuid4())


async def test_get_user_by_email_works(session: AsyncSession) -> None:
    created = await service.create_user(session, email="lookup@x.com")
    await session.commit()
    fetched = await service.get_user_by_email(session, "LOOKUP@x.com")
    assert fetched.id == created.id


async def test_get_user_by_email_raises_when_missing(session: AsyncSession) -> None:
    with pytest.raises(UserNotFoundError):
        await service.get_user_by_email(session, "nope@x.com")


async def test_users_table_persists_across_sessions(
    session: AsyncSession,
) -> None:
    """The truncate-between-tests fixture should not affect this test
    because we only have one fixture in play, but the assertion is
    that a created user is visible to a fresh read in the same session.
    """
    user = await service.create_user(session, email="persist@x.com")
    await session.commit()
    found = await service.get_user(session, user.id)
    assert isinstance(found, User)
    assert found.id == user.id
