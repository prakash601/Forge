"""Backfill CLI: populate NULL ``memory_embeddings`` rows.

Usage:
    uv run python -m app.memory.backfill --all [--batch-size 100]
    uv run python -m app.memory.backfill --project-id <uuid> [--batch-size 100]
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from app.config import get_settings
from app.db.session import get_session_factory, init_engine
from app.memory import pipeline
from app.memory.embeddings.registry import get_provider


async def _run(project_id: uuid.UUID | None, batch_size: int) -> int:
    settings = get_settings()
    init_engine(settings)
    provider = get_provider(
        provider_name=settings.embedding_provider,
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    factory = get_session_factory()
    total = 0
    async with factory() as session:
        while True:
            done = await pipeline.backfill_missing(
                session, provider, batch_size=batch_size, project_id=project_id
            )
            await session.commit()
            total += done
            if done < batch_size:
                break
    print(f"backfilled {total} memory items")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing memory embeddings.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Backfill all projects.")
    group.add_argument("--project-id", type=uuid.UUID, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    project_id = args.project_id if not args.all else None
    asyncio.run(_run(project_id, args.batch_size))


if __name__ == "__main__":
    main()
