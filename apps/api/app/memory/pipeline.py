"""Embedding pipeline: populate ``memory_embeddings.embedding``.

The ``memory_embeddings`` row is created NULL by
``create_memory_item``; this module fills it. Re-running on a row
that already has a vector is a no-op (idempotent). Provider failures
are retried with exponential backoff; on final failure the item's
status is set to ``EMBEDDING_FAILED``.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from sqlalchemy import select

from app.core.logging import get_logger
from app.memory.embeddings.protocols import EmbeddingProvider
from app.memory.enums import MemoryStatus
from app.memory.errors import EmbeddingDimensionMismatchError, MemoryItemNotFoundError
from app.memory.models import MemoryEmbedding, MemoryItem

log = get_logger(__name__)

EXPECTED_DIMENSION = 1536
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)


async def embed_memory_item(
    session: object,
    memory_item_id: uuid.UUID,
    provider: EmbeddingProvider,
    *,
    max_attempts: int = 3,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> bool:
    """Embed a single memory item. Returns True if newly embedded.

    Returns False when the row already had a vector (no-op) or when
    the item ended in ``EMBEDDING_FAILED`` after exhausting retries.

    Raises:
        MemoryItemNotFoundError: unknown ``memory_item_id``.
        EmbeddingDimensionMismatchError: provider returned wrong dims.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    item = await session.get(MemoryItem, memory_item_id)
    if item is None:
        raise MemoryItemNotFoundError(str(memory_item_id))

    emb_row = (
        await session.execute(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_item_id == item.id)
        )
    ).scalar_one_or_none()
    if emb_row is None:
        emb_row = MemoryEmbedding(memory_item_id=item.id, embedding=None)
        session.add(emb_row)
        await session.flush()

    if emb_row.embedding is not None:
        return False

    provider_name = getattr(provider, "name", type(provider).__name__)
    last_error: Exception | None = None
    last_latency_ms = 0
    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        try:
            vector = await provider.embed(item.content)
        except Exception as exc:
            last_error = exc
            last_latency_ms = int((time.perf_counter() - start) * 1000)
            log.warning(
                "memory_embedding_attempt",
                memory_item_id=str(item.id),
                provider=provider_name,
                latency_ms=last_latency_ms,
                attempt=attempt,
                outcome="retry" if attempt < max_attempts else "failed",
            )
            if attempt < max_attempts:
                delay = retry_delays[attempt - 1] if attempt - 1 < len(retry_delays) else 0
                if delay > 0:
                    await asyncio.sleep(delay)
            continue
        latency_ms = int((time.perf_counter() - start) * 1000)
        if len(vector) != EXPECTED_DIMENSION:
            item.status = MemoryStatus.EMBEDDING_FAILED
            await session.flush()
            log.warning(
                "memory_embedding_attempt",
                memory_item_id=str(item.id),
                provider=provider_name,
                latency_ms=latency_ms,
                attempt=attempt,
                outcome="dimension-mismatch",
                error=str(EmbeddingDimensionMismatchError(EXPECTED_DIMENSION, len(vector))),
            )
            return False
        emb_row.embedding = vector
        await session.flush()
        log.info(
            "memory_embedding_attempt",
            memory_item_id=str(item.id),
            provider=provider_name,
            latency_ms=latency_ms,
            attempt=attempt,
            outcome="success",
        )
        return True

    item.status = MemoryStatus.EMBEDDING_FAILED
    await session.flush()
    log.warning(
        "memory_embedding_attempt",
        memory_item_id=str(item.id),
        provider=provider_name,
        latency_ms=last_latency_ms,
        attempt=max_attempts,
        outcome="final-fail",
        error=str(last_error) if last_error else None,
    )
    return False


async def backfill_missing(
    session: object,
    provider: EmbeddingProvider,
    *,
    batch_size: int = 100,
    max_attempts: int = 3,
    project_id: uuid.UUID | None = None,
) -> int:
    """Embed all rows with NULL vectors. Returns count newly embedded."""
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    stmt = (
        select(MemoryEmbedding.memory_item_id)
        .where(MemoryEmbedding.embedding.is_(None))
        .limit(batch_size)
    )
    if project_id is not None:
        stmt = stmt.join(MemoryItem, MemoryItem.id == MemoryEmbedding.memory_item_id).where(
            MemoryItem.project_id == project_id
        )
    ids = list((await session.execute(stmt)).scalars().all())
    done = 0
    for memory_item_id in ids:
        if await embed_memory_item(session, memory_item_id, provider, max_attempts=max_attempts):
            done += 1
    return done


__all__ = ["DEFAULT_RETRY_DELAYS", "EXPECTED_DIMENSION", "backfill_missing", "embed_memory_item"]
