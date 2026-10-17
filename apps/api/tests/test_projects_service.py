"""Integration tests for the projects service (real Postgres).

Covers: create (happy + owner-not-found + empty-name), get-by-id,
list-for-owner, pagination.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects import service
from app.projects.enums import ProjectStatus
from app.projects.errors import ProjectNotFoundError
from app.users import service as users_service


async def _make_user(session: AsyncSession, email: str = "owner@x.com") -> uuid.UUID:
    user = await users_service.create_user(session, email=email)
    await session.commit()
    return user.id


async def test_create_project_persists_with_active_status(
    session: AsyncSession,
) -> None:
    owner = await _make_user(session)
    project = await service.create_project(
        session, owner_id=owner, name="My project", description="hello"
    )
    await session.commit()
    assert project.id is not None
    assert project.owner_id == owner
    assert project.name == "My project"
    assert project.description == "hello"
    assert project.status is ProjectStatus.ACTIVE


async def test_create_project_strips_whitespace(session: AsyncSession) -> None:
    owner = await _make_user(session)
    project = await service.create_project(
        session, owner_id=owner, name="  trimmed  ", description="  d  "
    )
    await session.commit()
    assert project.name == "trimmed"
    assert project.description == "d"


async def test_create_project_unknown_owner_raises(session: AsyncSession) -> None:
    with pytest.raises(Exception) as excinfo:
        await service.create_project(session, owner_id=uuid.uuid4(), name="orphan")
    # Either the pre-check raises UserNotFoundError or the FK does.
    assert "User" in str(excinfo.value) or "user" in str(excinfo.value).lower()


async def test_create_project_empty_name_raises(session: AsyncSession) -> None:
    owner = await _make_user(session)
    with pytest.raises(ValueError, match="non-empty"):
        await service.create_project(session, owner_id=owner, name="")


async def test_get_project_returns_persisted_row(session: AsyncSession) -> None:
    owner = await _make_user(session)
    created = await service.create_project(session, owner_id=owner, name="p1")
    await session.commit()
    fetched = await service.get_project(session, created.id)
    assert fetched.id == created.id


async def test_get_project_raises_for_unknown_id(session: AsyncSession) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.get_project(session, uuid.uuid4())


async def test_list_projects_for_owner_returns_only_theirs(
    session: AsyncSession,
) -> None:
    owner_a = await _make_user(session, "a@x.com")
    owner_b = await _make_user(session, "b@x.com")
    await service.create_project(session, owner_id=owner_a, name="a1")
    await service.create_project(session, owner_id=owner_a, name="a2")
    await service.create_project(session, owner_id=owner_b, name="b1")
    await session.commit()

    a_projects = await service.list_projects_for_owner(session, owner_a)
    b_projects = await service.list_projects_for_owner(session, owner_b)
    assert {p.name for p in a_projects} == {"a1", "a2"}
    assert {p.name for p in b_projects} == {"b1"}


async def test_list_projects_pagination(session: AsyncSession) -> None:
    owner = await _make_user(session)
    for i in range(5):
        await service.create_project(session, owner_id=owner, name=f"p{i}")
    await session.commit()

    page1 = await service.list_projects_for_owner(session, owner, limit=2, offset=0)
    page2 = await service.list_projects_for_owner(session, owner, limit=2, offset=2)
    page3 = await service.list_projects_for_owner(session, owner, limit=2, offset=4)
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1
    # Newest first means the first-created is last in the list.
    all_names = [p.name for p in page1 + page2 + page3]
    assert set(all_names) == {"p0", "p1", "p2", "p3", "p4"}


async def test_list_projects_unknown_owner_raises(session: AsyncSession) -> None:
    """We could return [] silently, but raising makes typos obvious."""
    from app.users.errors import UserNotFoundError

    with pytest.raises(UserNotFoundError):
        await service.list_projects_for_owner(session, uuid.uuid4())
