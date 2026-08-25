"""Async SQLAlchemy engine and session management.

The Phase 0 API uses this only to confirm that the database is reachable
from `/ready`. Application tables and repositories are added starting in
Phase 1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from app.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(settings: Settings) -> AsyncEngine:
    if settings.database_url is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set the DATABASE_URL environment "
            "variable (e.g. in .env) before starting the API.",
        )
    return create_async_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
    )


def init_engine(settings: Settings) -> None:
    """Initialize the global engine and session factory.

    Called once at application startup. Idempotent.
    """
    global _engine, _session_factory
    if _engine is None:
        _engine = _build_engine(settings)
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )


async def dispose_engine() -> None:
    """Dispose the global engine.

    Called during graceful shutdown.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError(
            "Database session factory is not initialized. "
            "Call init_engine() during application startup.",
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def ping_database() -> None:
    """Raise if the database cannot be reached.

    Used by the readiness probe. Performs a `SELECT 1`.
    """
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))


__all__: list[Any] = [
    "AsyncEngine",
    "AsyncSession",
    "dispose_engine",
    "get_session",
    "get_session_factory",
    "init_engine",
    "ping_database",
]
