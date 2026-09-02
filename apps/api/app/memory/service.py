"""Memory service.

Functions over the ``memory_items`` table. The caller owns the
transaction.

Embedding handling
------------------
The ``memory_embeddings`` table is created alongside ``memory_items``
in migration 0005 but the embedding column is intentionally NULLable.
A memory item can exist without an embedding — the row is simply
not retrievable by vector search. The embedding pipeline (separate
issue) is responsible for populating the column.

This service creates the ``memory_items`` row only. Creating the
``memory_embeddings`` row is also done here as a convenience: it
keeps the schema consistent (one-to-one via the unique constraint)
and means the embedding pipeline can simply ``UPDATE`` the
existing row. Without this, the pipeline would have to deal with
"row exists vs not" branching.

Embedding generation itself is explicitly NOT performed here. A
later issue owns the model + provider choice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.enums import MemoryStatus
from app.memory.errors import MemoryItemNotFoundError
from app.memory.models import MemoryEmbedding, MemoryItem
from app.projects.errors import ProjectNotFoundError
from app.projects.models import Project


async def create_memory_item(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    memory_type: str,
    content: str,
    title: str | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    confidence: float | None = None,
    repository_commit: str | None = None,
) -> MemoryItem:
    """Create a memory item and its (empty) embedding row.

    Raises:
        ProjectNotFoundError: ``project_id`` does not exist.
        ValueError: ``content`` is empty or ``confidence`` out of range.
    """
    if not content or not content.strip():
        raise ValueError("content must be a non-empty string")
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be in [0.0, 1.0]")

    # Pre-check the project exists so the API layer can return a
    # clean 404 instead of an opaque IntegrityError.
    project = await session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))

    now = datetime.now(UTC)
    item = MemoryItem(
        project_id=project_id,
        memory_type=memory_type.strip(),
        title=(title.strip() if title else None) or None,
        content=content.strip(),
        source_type=(source_type.strip() if source_type else None) or None,
        source_id=source_id,
        confidence=confidence,
        status=MemoryStatus.ACTIVE,
        repository_commit=(repository_commit.strip() if repository_commit else None) or None,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    await session.flush()  # populate item.id for the FK

    # Create the empty embedding row. The column is NULL until the
    # embedding pipeline runs.
    embedding_row = MemoryEmbedding(
        memory_item_id=item.id,
        embedding=None,
        created_at=now,
    )
    session.add(embedding_row)
    await session.flush()
    return item


async def get_memory_item(session: AsyncSession, memory_item_id: uuid.UUID) -> MemoryItem:
    """Return the memory item with ``memory_item_id`` or raise
    :class:`MemoryItemNotFoundError`.
    """
    item = await session.get(MemoryItem, memory_item_id)
    if item is None:
        raise MemoryItemNotFoundError(str(memory_item_id))
    return item


async def list_memory_items_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    status: MemoryStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryItem]:
    """List memory items for ``project_id``, newest first.

    Filter by ``status`` to retrieve only ACTIVE items (the common
    case) or include SUPERSEDED/INVALIDATED for audit views.

    Raises:
        ProjectNotFoundError: ``project_id`` does not exist. Listing
            against a non-existent project is treated as an error
            rather than returning an empty list, so callers cannot
            silently miss typos.
    """
    # Pre-check project existence for the same reason as create.
    project = await session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))

    stmt = select(MemoryItem).where(MemoryItem.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MemoryItem.status == status.value)
    stmt = stmt.order_by(MemoryItem.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "create_memory_item",
    "get_memory_item",
    "list_memory_items_for_project",
]
