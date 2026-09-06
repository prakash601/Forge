"""Integration tests for the embedding pipeline (real Postgres).

Seam 2: embed_memory_item + backfill_missing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import service as memory_service
from app.memory.embeddings.fake import FakeEmbeddingProvider
from app.memory.enums import MemoryStatus
from app.memory.models import MemoryEmbedding
from app.projects import service as projects_service
from app.users import service as users_service


async def _make_project(session: AsyncSession) -> uuid.UUID:
    user = await users_service.create_user(session, email="e@x.com")
    await session.commit()
    project = await projects_service.create_project(session, owner_id=user.id, name="p")
    await session.commit()
    return project.id


async def test_embed_memory_item_populates_null_embedding(session: AsyncSession) -> None:
    from app.memory import pipeline

    project_id = await _make_project(session)
    item = await memory_service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content="FastAPI uses Pydantic v2"
    )
    await session.commit()

    result = await pipeline.embed_memory_item(session, item.id, FakeEmbeddingProvider())
    await session.commit()

    assert result is True
    row = (
        await session.execute(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_item_id == item.id)
        )
    ).scalar_one()
    assert row.embedding is not None
    assert len(row.embedding) == 1536


async def test_embed_memory_item_is_idempotent_when_already_embedded(
    session: AsyncSession,
) -> None:
    from app.memory import pipeline

    project_id = await _make_project(session)
    item = await memory_service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content="hello"
    )
    await session.commit()
    provider = FakeEmbeddingProvider()
    assert await pipeline.embed_memory_item(session, item.id, provider) is True
    await session.commit()
    # Second run is a no-op.
    assert await pipeline.embed_memory_item(session, item.id, provider) is False
    await session.commit()


async def test_embed_memory_item_marks_failed_after_retries(session: AsyncSession) -> None:
    from app.memory import pipeline

    class Boom:
        name = "boom"
        dimension = 1536
        calls = 0

        async def embed(self, text: str) -> list[float]:
            self.calls += 1
            raise RuntimeError("provider down")

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("provider down")

    project_id = await _make_project(session)
    item = await memory_service.create_memory_item(
        session, project_id=project_id, memory_type="fact", content="needs embedding"
    )
    await session.commit()

    ok = await pipeline.embed_memory_item(
        session, item.id, Boom(), max_attempts=3, retry_delays=(0, 0, 0)
    )
    await session.commit()

    assert ok is False
    refreshed = await memory_service.get_memory_item(session, item.id)
    assert refreshed.status is MemoryStatus.EMBEDDING_FAILED


async def test_backfill_processes_only_missing_rows(session: AsyncSession) -> None:
    from app.memory import pipeline

    project_id = await _make_project(session)
    for i in range(3):
        await memory_service.create_memory_item(
            session, project_id=project_id, memory_type="fact", content=f"row {i}"
        )
    await session.commit()

    done = await pipeline.backfill_missing(session, FakeEmbeddingProvider(), batch_size=10)
    await session.commit()
    assert done == 3
    # Second pass finds nothing to do.
    done2 = await pipeline.backfill_missing(session, FakeEmbeddingProvider(), batch_size=10)
    await session.commit()
    assert done2 == 0
