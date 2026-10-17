"""Integration tests for the memory service (real Postgres).

Covers: create (happy + project-not-found + validation), embedding
row creation, list-for-project, status filter, pagination.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import service
from app.memory.enums import MemoryStatus, MemoryType
from app.memory.errors import MemoryItemNotFoundError
from app.memory.models import MemoryEmbedding
from app.projects import service as projects_service
from app.projects.errors import ProjectNotFoundError
from app.users import service as users_service


async def _make_user_and_project(
    session: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID]:
    user = await users_service.create_user(session, email="o@x.com")
    await session.commit()
    project = await projects_service.create_project(session, owner_id=user.id, name="p")
    await session.commit()
    return user.id, project.id


async def test_create_memory_item_persists_with_active_status(
    session: AsyncSession,
) -> None:
    _, project_id = await _make_user_and_project(session)
    item = await service.create_memory_item(
        session,
        project_id=project_id,
        memory_type="decision",
        content="Use limit/offset for pagination",
    )
    await session.commit()
    assert item.id is not None
    assert item.project_id == project_id
    assert item.memory_type == "decision"
    assert item.status is MemoryStatus.ACTIVE
    assert item.confidence is None


async def test_create_memory_item_creates_empty_embedding_row(
    session: AsyncSession,
) -> None:
    """The schema invariant: every item has an embedding row, even
    if the vector column is NULL.
    """
    _, project_id = await _make_user_and_project(session)
    item = await service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content="x"
    )
    await session.commit()

    # The PK is shared with MemoryItem, so we look up by memory_item_id.
    result = await session.execute(
        select(MemoryEmbedding).where(MemoryEmbedding.memory_item_id == item.id)
    )
    found = result.scalar_one()
    assert found.memory_item_id == item.id
    assert found.embedding is None  # populated by a later issue


async def test_create_memory_item_rejects_empty_content(
    session: AsyncSession,
) -> None:
    _, project_id = await _make_user_and_project(session)
    with pytest.raises(ValueError, match="non-empty"):
        await service.create_memory_item(
            session, project_id=project_id, memory_type="fact", content=""
        )


async def test_create_memory_item_rejects_bad_confidence(
    session: AsyncSession,
) -> None:
    _, project_id = await _make_user_and_project(session)
    with pytest.raises(ValueError, match="confidence"):
        await service.create_memory_item(
            session,
            project_id=project_id,
            memory_type="fact",
            content="x",
            confidence=1.5,
        )


async def test_create_memory_item_unknown_project_raises(
    session: AsyncSession,
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.create_memory_item(
            session,
            project_id=uuid.uuid4(),
            memory_type="fact",
            content="orphan",
        )


async def test_get_memory_item_returns_persisted_row(
    session: AsyncSession,
) -> None:
    _, project_id = await _make_user_and_project(session)
    created = await service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content="x"
    )
    await session.commit()
    fetched = await service.get_memory_item(session, created.id)
    assert fetched.id == created.id


async def test_get_memory_item_raises_for_unknown_id(
    session: AsyncSession,
) -> None:
    with pytest.raises(MemoryItemNotFoundError):
        await service.get_memory_item(session, uuid.uuid4())


async def test_list_memory_items_for_project_newest_first(
    session: AsyncSession,
) -> None:
    _, project_id = await _make_user_and_project(session)
    for i in range(3):
        await service.create_memory_item(
            session, project_id=project_id, memory_type="fact", content=f"item {i}"
        )
    await session.commit()
    items = await service.list_memory_items_for_project(session, project_id)
    assert [i.content for i in items] == ["item 2", "item 1", "item 0"]


async def test_list_memory_items_status_filter(session: AsyncSession) -> None:
    _, project_id = await _make_user_and_project(session)
    item = await service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content="alive"
    )
    await session.commit()

    # Mark as SUPERSEDED.
    item.status = MemoryStatus.SUPERSEDED
    await session.commit()

    active = await service.list_memory_items_for_project(
        session, project_id, status=MemoryStatus.ACTIVE
    )
    superseded = await service.list_memory_items_for_project(
        session, project_id, status=MemoryStatus.SUPERSEDED
    )
    assert active == []
    assert len(superseded) == 1


async def test_list_memory_items_isolated_by_project(
    session: AsyncSession,
) -> None:
    user_id, project_a_id = await _make_user_and_project(session)
    project_b = await projects_service.create_project(session, owner_id=user_id, name="other")
    project_b_id = project_b.id
    await session.commit()
    await service.create_memory_item(
        session, project_id=project_a_id, memory_type="fact", content="A"
    )
    await service.create_memory_item(
        session, project_id=project_b_id, memory_type="fact", content="B"
    )
    await session.commit()

    a_items = await service.list_memory_items_for_project(session, project_a_id)
    b_items = await service.list_memory_items_for_project(session, project_b_id)
    assert [i.content for i in a_items] == ["A"]
    assert [i.content for i in b_items] == ["B"]


async def test_list_memory_items_unknown_project_raises(
    session: AsyncSession,
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.list_memory_items_for_project(session, uuid.uuid4())


async def test_memory_type_enum_values_present() -> None:
    """Sanity: the enum values match what we expect callers to send."""
    assert MemoryType.DECISION.value == "decision"
    assert MemoryType.CONVENTION.value == "convention"


def _unit_vec(index: int, dims: int = 1536) -> list[float]:
    vec = [0.0] * dims
    vec[index] = 1.0
    return vec


async def _make_embedded_item(
    session: AsyncSession,
    project_id: uuid.UUID,
    content: str,
    vector: list[float] | None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> uuid.UUID:
    from app.memory.models import MemoryEmbedding

    item = await service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content=content
    )
    item.status = status
    emb_row = (
        await session.execute(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_item_id == item.id)
        )
    ).scalar_one()
    emb_row.embedding = vector
    await session.flush()
    return item.id


async def test_search_returns_nearest_first(session: AsyncSession) -> None:
    _, project_id = await _make_user_and_project(session)
    await _make_embedded_item(session, project_id, "orthogonal", _unit_vec(1))
    await _make_embedded_item(session, project_id, "nearest", _unit_vec(0))
    found = await service.search_similar_memories(
        session, project_id=project_id, query_embedding=_unit_vec(0), limit=5
    )
    assert [i.content for i in found] == ["nearest", "orthogonal"]


async def test_search_scopes_to_project(session: AsyncSession) -> None:
    _, project_a = await _make_user_and_project(session)
    user_b = await users_service.create_user(session, email="other@x.com")
    await session.commit()
    from app.projects import service as projects_service

    project_b = await projects_service.create_project(session, owner_id=user_b.id, name="other")
    await session.commit()
    await _make_embedded_item(session, project_b.id, "foreign", _unit_vec(0))
    found = await service.search_similar_memories(
        session, project_id=project_a, query_embedding=_unit_vec(0), limit=5
    )
    assert found == []


async def test_search_skips_null_and_inactive(session: AsyncSession) -> None:
    _, project_id = await _make_user_and_project(session)
    await _make_embedded_item(session, project_id, "no-vector", None)
    await _make_embedded_item(
        session, project_id, "retired", _unit_vec(0), status=MemoryStatus.SUPERSEDED
    )
    found = await service.search_similar_memories(
        session, project_id=project_id, query_embedding=_unit_vec(0), limit=5
    )
    assert found == []


async def test_search_respects_limit_and_validates(session: AsyncSession) -> None:
    import pytest

    _, project_id = await _make_user_and_project(session)
    for n in range(3):
        await _make_embedded_item(session, project_id, f"m{n}", _unit_vec(0))
    found = await service.search_similar_memories(
        session, project_id=project_id, query_embedding=_unit_vec(0), limit=2
    )
    assert len(found) == 2
    with pytest.raises(ValueError):
        await service.search_similar_memories(
            session, project_id=project_id, query_embedding=[], limit=2
        )
    with pytest.raises(ValueError):
        await service.search_similar_memories(
            session, project_id=project_id, query_embedding=_unit_vec(0), limit=0
        )


async def test_search_unknown_project_returns_empty(session: AsyncSession) -> None:
    found = await service.search_similar_memories(
        session, project_id=uuid.uuid4(), query_embedding=_unit_vec(0), limit=5
    )
    assert found == []
