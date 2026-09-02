"""Shared pytest fixtures for the Forge API.

Phase 1 uses **Postgres-only** test runs (per project decision recorded in
STATUS.md). The fixtures below start a disposable Postgres container via
``testcontainers[postgres]`` and apply migrations 0001 + 0002.

Resolution
----------
The container is started lazily, *only* when a test requests one of the
database fixtures (``engine``, ``session``, ``client``, ``app_instance``).
Pure-Python unit tests (e.g. transition table tests) run with no
container and no DB. This keeps the unit-test feedback loop fast.

Environment variables
---------------------
  * ``FORGE_TEST_DATABASE_URL`` — point at a pre-existing Postgres DSN
    (used by CI runners that provision Postgres themselves). When set,
    no testcontainers container is started.
  * ``FORGE_TEST_NO_TESTCONTAINERS=1`` — skip tests that need Postgres
    entirely (used by lightweight CI jobs that don't need DB tests).

Why not SQLite?
---------------
Phase 0 used SQLite for speed. Phase 1 introduces a Postgres ``ENUM``
type (``run_state``) and ``gen_random_uuid()`` server defaults; neither
is supported by SQLite. Reverting to SQLite would require divergent
ORM definitions for test vs. prod.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Forward import for type hints. The actual orchestrator is built
# inside the fixture to avoid a hard dependency at module import time.
from app.orchestrator import Orchestrator

# Force test mode so the application does not emit structured JSON to
# the test runner's stdout.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")


# Container handle keyed by DSN so multiple sessions (e.g. pytest-xdist
# workers) can coexist. We stop them all at process exit.
_CONTAINERS: list[Any] = []


async def _create_database_and_apply_migrations(async_dsn: str) -> None:
    """Create a throwaway database and apply all SQL migrations.

    Connects to the server's default ``postgres`` DB first to issue
    ``CREATE DATABASE``, then reconnects against the new DB and applies
    every ``db/migrations/*.sql`` file in lexical order.

    asyncpg rejects multi-statement prepared calls, so we split each
    SQL file on ``;`` and execute the statements individually.
    """
    server_dsn = async_dsn.rsplit("/", 1)[0] + "/postgres"
    bootstrap_engine = create_async_engine(server_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with bootstrap_engine.connect() as conn:
            db_name = async_dsn.rsplit("/", 1)[1].split("?")[0]
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await bootstrap_engine.dispose()

    migrations_dir = Path(__file__).resolve().parents[3] / "db" / "migrations"
    engine = create_async_engine(async_dsn)
    try:
        sql_files = sorted(migrations_dir.glob("*.sql"))
        async with engine.connect() as conn:
            for sql_file in sql_files:
                for statement in _split_sql_statements(sql_file.read_text(encoding="utf-8")):
                    await conn.execute(text(statement))
            await conn.commit()
    finally:
        await engine.dispose()


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Naive split on ``;`` that ignores ``--`` line comments and dollar-
    quoted blocks (``$$ ... $$``). The Forge migrations do not use
    nested dollar quoting, so this is sufficient.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_dollar_quote = False
    for raw_line in sql.splitlines():
        line = raw_line
        # Strip line comments before further processing.
        if not in_dollar_quote:
            comment_idx = line.find("--")
            if comment_idx != -1:
                line = line[:comment_idx]
        if "$$" in line:
            in_dollar_quote = not in_dollar_quote
        if line.strip() == "":
            continue
        buf.append(line)
        if not in_dollar_quote and line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    leftover = "\n".join(buf).strip()
    if leftover:
        statements.append(leftover)
    return statements


async def _truncate_all(engine: AsyncEngine) -> None:
    """Empty the run-related tables between integration tests."""
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE memory_embeddings, memory_items, projects, users, "
                "run_steps, runs RESTART IDENTITY CASCADE"
            )
        )
        await conn.commit()


@pytest.fixture(scope="session")
def postgres_engine_url() -> str:
    """Return an async Postgres DSN, starting a container on demand.

    The container (and the throwaway DB inside it) lives for the whole
    test session. Each test that uses the ``engine`` fixture runs inside
    a SAVEPOINT so it can commit freely without leaking state.
    """
    explicit = os.environ.get("FORGE_TEST_DATABASE_URL")
    if explicit:
        return explicit

    if os.environ.get("FORGE_TEST_NO_TESTCONTAINERS") == "1":
        pytest.skip("FORGE_TEST_NO_TESTCONTAINERS=1 and no FORGE_TEST_DATABASE_URL provided")

    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError as exc:  # pragma: no cover - import guard
        pytest.skip(f"testcontainers[postgres] not installed: {exc}")

    container = PostgresContainer("pgvector/pgvector:pg16")
    container.start()
    _CONTAINERS.append(container)

    # Generate a unique DB name; the container ships with a default DB.
    db_name = f"forge_test_{uuid.uuid4().hex[:8]}"
    raw = container.get_connection_url()
    # testcontainers returns e.g. ``postgresql+psycopg2://u:p@h:port/db``.
    # Translate to asyncpg and swap the db name.
    sync_dsn = raw.replace("postgresql+psycopg2", "postgresql", 1)
    base = sync_dsn.rsplit("/", 1)[0]
    async_dsn = f"{base}/{db_name}".replace("postgresql", "postgresql+asyncpg", 1)

    asyncio.run(_create_database_and_apply_migrations(async_dsn))
    return async_dsn


@pytest.fixture(scope="session", autouse=True)
def _stop_containers_at_end() -> AsyncIterator[None]:
    """Stop any testcontainers Postgres containers at session end."""
    yield
    for container in _CONTAINERS:
        try:
            container.stop()
        except Exception:  # pragma: no cover - best-effort
            pass


@pytest.fixture
def app_settings(postgres_engine_url: str) -> Any:
    """Settings pointing at the test database."""
    from app.config import Settings

    return Settings(database_url=postgres_engine_url, environment="test", log_level="WARNING")


@pytest_asyncio.fixture
async def app_instance(app_settings: Any) -> AsyncIterator[Any]:
    """Build the FastAPI app against the test database."""
    # Drop the cached settings so a previous test cannot leak in.
    from app.config import get_settings

    get_settings.cache_clear()

    from app.db import session as db_session
    from app.main import create_app

    db_session.init_engine(app_settings)
    # Truncate before each test that uses this fixture so HTTP-only
    # tests (which do not pull in the ``engine`` fixture) still get
    # a clean slate.
    factory = db_session.get_session_factory()
    eng = factory.kw["bind"]
    assert isinstance(eng, AsyncEngine)
    await _truncate_all(eng)
    app = create_app(app_settings)
    try:
        yield app
    finally:
        await db_session.dispose_engine()


@pytest_asyncio.fixture
async def engine(app_settings: Any) -> AsyncIterator[AsyncEngine]:
    """Async SQLAlchemy engine bound to the test database."""
    from app.db import session as db_session

    db_session.init_engine(app_settings)
    try:
        factory = db_session.get_session_factory()
        # The sessionmaker's ``kw`` dict holds the bind. SQLAlchemy does
        # not expose a public ``.bind`` on async_sessionmaker, so we read
        # from the kwargs instead. ``bind`` is a single AsyncEngine here.
        eng = factory.kw["bind"]
        assert isinstance(eng, AsyncEngine)
        # Start clean.
        await _truncate_all(eng)
        yield eng
    finally:
        await db_session.dispose_engine()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A test-scoped session wrapped in a SAVEPOINT.

    Tests that explicitly call ``session.commit()`` commit their own
    work; the outer fixture rolls the session back at teardown so any
    uncommitted state is undone.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.begin_nested()
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def client(app_instance: Any) -> AsyncIterator[AsyncClient]:
    """``httpx.AsyncClient`` against the FastAPI app."""
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def orchestrator_app(
    app_settings: Any,
) -> AsyncIterator[tuple[AsyncClient, Orchestrator]]:
    """Build an app with the orchestrator wired in, returning the client.

    The orchestrator is installed on ``app.state`` and uses the same
    async session factory as the API layer. Tests can inspect
    ``orchestrator.runtime`` to assert on in-flight tasks.
    """
    from app.config import get_settings

    get_settings.cache_clear()

    from app.db import session as db_session
    from app.main import create_app
    from app.orchestrator import Orchestrator, StateAgentRegistry

    db_session.init_engine(app_settings)
    app = create_app(app_settings)
    factory = db_session.get_session_factory()
    orchestrator = Orchestrator(
        driver=StateAgentRegistry(),
        session_maker=factory,
    )
    app.state.orchestrator = orchestrator
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac, orchestrator
    finally:
        await orchestrator.shutdown()
        await db_session.dispose_engine()
