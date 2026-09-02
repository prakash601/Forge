"""Projects service.

Functions over the ``projects`` table. The caller owns the
transaction. The service raises typed exceptions on the unhappy
paths so the API layer can map them to the right HTTP status code.

Foreign key handling
--------------------
``owner_id`` is enforced at the database level (FK to ``users.id``).
If the caller passes a non-existent user UUID, the insert fails with
``IntegrityError``. We surface this as :class:`ProjectNotFoundError`
against the *user* — the API layer maps it to 404 with a clear
message, since the symptom the user sees is "I tried to use this
owner and you couldn't find them".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.enums import ProjectStatus
from app.projects.errors import ProjectNotFoundError
from app.projects.models import Project
from app.users.errors import UserNotFoundError
from app.users.models import User


async def create_project(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str | None = None,
) -> Project:
    """Create a new project owned by ``owner_id``.

    Raises:
        UserNotFoundError: ``owner_id`` does not reference an existing user.
        ValueError: ``name`` is empty.
    """
    if not name or not name.strip():
        raise ValueError("name must be a non-empty string")
    # Pre-check the user exists. This is a tiny race (the user could
    # be deleted between this read and the insert) but the FK
    # constraint is the source of truth; the pre-check is just to
    # produce a clean 404 instead of an IntegrityError.
    owner = await session.get(User, owner_id)
    if owner is None:
        raise UserNotFoundError(str(owner_id))

    now = datetime.now(UTC)
    project = Project(
        owner_id=owner_id,
        name=name.strip(),
        description=(description.strip() if description else None) or None,
        status=ProjectStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Owner was deleted between our pre-check and the insert.
        # Re-raise as a not-found so the API layer returns 404.
        await session.rollback()
        raise UserNotFoundError(str(owner_id)) from exc
    return project


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    """Return the project with ``project_id`` or raise :class:`ProjectNotFoundError`."""
    project = await session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


async def list_projects_for_owner(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Project]:
    """List projects owned by ``owner_id``, newest first.

    Pagination is offset-based for now; a later issue can switch to
    cursor pagination if the MVP data size warrants it.

    Raises:
        UserNotFoundError: ``owner_id`` does not exist. Listing against
            a non-existent owner is treated as an error rather than
            returning an empty list, so callers cannot silently miss
            typos.
    """
    # Pre-check the owner exists for the same reason as create_project.
    owner = await session.get(User, owner_id)
    if owner is None:
        raise UserNotFoundError(str(owner_id))

    result = await session.execute(
        select(Project)
        .where(Project.owner_id == owner_id)
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


__all__ = ["create_project", "get_project", "list_projects_for_owner"]
