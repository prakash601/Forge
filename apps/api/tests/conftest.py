"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db import session as db_session
from app.main import create_app


class _InMemorySettings(Settings):
    """Settings that point at an in-process async SQLite database.

    SQLite is sufficient for the Phase 0 smoke tests; we only need to
    exercise FastAPI wiring. Real database behavior is validated in CI
    against PostgreSQL via the migration step.
    """

    database_url: str = "sqlite+aiosqlite:///:memory:"  # type: ignore[assignment]
    environment: str = "test"  # type: ignore[assignment]
    log_level: str = "WARNING"  # type: ignore[assignment]


@pytest_asyncio.fixture
async def app_instance() -> AsyncIterator[Any]:
    settings = _InMemorySettings()
    app = create_app(settings)
    # Initialize the engine eagerly so the readiness probe has something
    # to ping. The lifespan event would also do this, but httpx's
    # ASGITransport does not trigger lifespan by default.
    db_session.init_engine(settings)
    try:
        yield app
    finally:
        await db_session.dispose_engine()


@pytest_asyncio.fixture
async def client(app_instance: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
