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
                "TRUNCATE TABLE pull_requests, github_credentials, run_memories, "
                "run_reviews, run_diagnoses, run_test_results, "
                "run_implementations, run_plans, run_analyses, memory_embeddings, "
                "memory_items, projects, users, run_steps, runs RESTART IDENTITY CASCADE"
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
async def auth_settings(postgres_engine_url: str) -> Any:
    """Settings with auth configured (GitHub OAuth test creds + JWT).

    Uses the fake OAuth client via dependency override in the fixtures
    below — no network, ever. The plain ``app_settings`` fixture stays
    unconfigured so 503-path tests keep working.
    """
    from cryptography.fernet import Fernet

    from app.config import Settings

    return Settings(
        database_url=postgres_engine_url,
        environment="test",
        log_level="WARNING",
        github_client_id="test-client-id",
        github_client_secret="test-client-secret",
        jwt_secret="test-jwt-secret-for-suite-use-only",
        credentials_key=Fernet.generate_key().decode(),
    )


@pytest_asyncio.fixture
async def authed_client(auth_settings: Any, engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Logged-in client (session cookie set via the fake OAuth callback).

    Takes ``engine`` (unused) to force truncation-before-login ordering:
    without it, a test combining this fixture with ``session``/``engine``
    would wipe the login user at the other fixture's setup.
    """
    from app.api.v1.auth import get_oauth_client
    from app.auth.github import FakeGitHubOAuthClient
    from app.config import get_settings
    from app.db import session as db_session
    from app.main import create_app

    _ = engine
    get_settings.cache_clear()
    db_session.init_engine(auth_settings)
    try:
        factory = db_session.get_session_factory()
        eng = factory.kw["bind"]
        assert isinstance(eng, AsyncEngine)
        await _truncate_all(eng)
        app = create_app(auth_settings)
        app.dependency_overrides[get_oauth_client] = lambda: FakeGitHubOAuthClient()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            login = await ac.get("/api/v1/auth/github/callback?code=any")
            assert login.status_code == 200, login.text
            yield ac
    finally:
        await db_session.dispose_engine()


@pytest_asyncio.fixture
async def owned_project(authed_client: AsyncClient) -> dict[str, Any]:
    """A project owned by the logged-in caller, via the API."""
    project = await ensure_project(authed_client)
    me = (await authed_client.get("/api/v1/auth/me")).json()
    return {"user": me, "project": project}


async def ensure_project(client: AsyncClient, name: str = "tenancy-probe") -> dict[str, Any]:
    """Create a project for the logged-in caller; return its JSON."""
    response = await client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "todo-app"


def _pagination_edit_pair() -> tuple[str, str]:
    """Derive the canned pagination edit from the live fixture file.

    Reading the anchor from disk (instead of hardcoding it) keeps the
    canned developer payload valid when the fixture evolves.
    """
    src = (FIXTURE_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("def list_todos"))
    old = "\n".join(lines[start : start + 2])
    assert "sorted(_store)" in old, "fixture list_todos anchor drifted"
    new = (
        "def list_todos(limit: int = 100, offset: int = 0) -> list[Todo]:\n"
        "    items = [_store[key] for key in sorted(_store)]\n"
        "    return items[offset : offset + limit]"
    )
    return old, new


def _wire_test_agents(registry: Any, factory: Any, workspace_root: Path) -> None:
    """Register deterministic FakeLLM agents for the Phase 2 loop.

    Archaeologist (ANALYZING), planner (PLANNING), developer
    (IMPLEMENTING) persist to the test database. The policy
    auto-approver (AWAITING_APPROVAL) is registered by the caller when
    wanted, so approval tests can run with a human in the loop.
    """
    import uuid as _uuid

    from app.agents.archaeologist import ArchaeologistAgent
    from app.agents.developer import DeveloperAgent
    from app.agents.planner import PlannerAgent
    from app.agents.schemas import (
        ArchaeologistFindings as _Findings,
    )
    from app.agents.schemas import (
        DeveloperResult as _Result,
    )
    from app.agents.schemas import (
        Plan as _Plan,
    )
    from app.agents.service import save_analysis, save_implementation, save_plan
    from app.agents.workspace import WorkspaceManager
    from app.llm.fake import FakeLLMProvider
    from app.runs.enums import RunState as _RunState

    async def _commit(sess: Any) -> None:
        try:
            await sess.commit()
        except Exception:
            await sess.rollback()
            raise

    async def _save_analysis(*, run_id: object, findings: object, **kwargs: Any) -> None:
        assert isinstance(findings, _Findings)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_analysis(
                sess,
                run_id=_rid,
                findings=findings,
                provider=str(kwargs.get("provider", "fake")),
                model=str(kwargs.get("model", "fake-llm")),
            )
            await _commit(sess)
        finally:
            await sess.close()

    async def _save_plan(*, run_id: object, plan: object, **kwargs: Any) -> None:
        assert isinstance(plan, _Plan)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_plan(
                sess,
                run_id=_rid,
                plan=plan,
                provider=str(kwargs.get("provider", "fake")),
                model=str(kwargs.get("model", "fake-llm")),
            )
            await _commit(sess)
        finally:
            await sess.close()

    async def _save_impl(*, run_id: object, result: object, **kwargs: Any) -> None:
        assert isinstance(result, _Result)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_implementation(
                sess,
                run_id=_rid,
                result=result,
                provider=str(kwargs.get("provider", "fake")),
                model=str(kwargs.get("model", "fake-llm")),
                workspace_path=str(kwargs.get("workspace_path", "")),
            )
            await _commit(sess)
        finally:
            await sess.close()

    async def _load_plan(*, run_id: object, **kwargs: Any) -> Any:
        from app.agents.schemas import Plan as _Plan
        from app.agents.service import get_plan

        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            row = await get_plan(sess, _rid)
            return _Plan.model_validate(row.plan) if row is not None else None
        finally:
            await sess.close()

    async def _load_findings(*, run_id: object, **kwargs: Any) -> Any:
        from app.agents.schemas import ArchaeologistFindings as _Findings
        from app.agents.service import get_analysis

        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            row = await get_analysis(sess, _rid)
            return _Findings.model_validate(row.findings) if row is not None else None
        finally:
            await sess.close()

    from app.agents.service import (
        get_diagnosis,
        get_test_result,
        save_diagnosis,
        save_memory,
        save_review,
        save_test_result,
    )

    async def _save_test(*, run_id: object, result: object, **kwargs: Any) -> None:
        from app.agents.schemas import TestReport as _Report

        assert isinstance(result, _Report)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_test_result(
                sess,
                run_id=_rid,
                result=result,
                provider=str(kwargs.get("provider", "fake")),
                model=str(kwargs.get("model", "fake-llm")),
            )
            await _commit(sess)
        finally:
            await sess.close()

    async def _save_diag(*, run_id: object, diagnosis: object, **kwargs: Any) -> None:
        from app.agents.schemas import DebuggerDiagnosis as _Diagnosis

        assert isinstance(diagnosis, _Diagnosis)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_diagnosis(
                sess,
                run_id=_rid,
                diagnosis=diagnosis,
                provider=str(kwargs.get("provider", "fake")),
                model=str(kwargs.get("model", "fake-llm")),
            )
            await _commit(sess)
        finally:
            await sess.close()

    async def _save_review(*, run_id: object, review: object, **kwargs: Any) -> None:
        from app.agents.schemas import ReviewDecision as _Decision

        assert isinstance(review, _Decision)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_review(
                sess,
                run_id=_rid,
                review=review,
                provider=str(kwargs.get("provider", "fake")),
                model=str(kwargs.get("model", "fake-llm")),
            )
            await _commit(sess)
        finally:
            await sess.close()

    async def _save_mem(*, run_id: object, candidates: object, **kwargs: Any) -> None:
        assert isinstance(candidates, list)
        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            await save_memory(sess, run_id=_rid, candidates=candidates)
            await _commit(sess)
        finally:
            await sess.close()

    async def _load_report(*, run_id: object, **kwargs: Any) -> Any:
        from app.agents.schemas import TestReport as _Report

        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            row = await get_test_result(sess, _rid)
            return _Report.model_validate(row.result) if row is not None else None
        finally:
            await sess.close()

    async def _load_diag(*, run_id: object, **kwargs: Any) -> Any:
        from app.agents.schemas import DebuggerDiagnosis as _Diagnosis

        _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
        sess = factory()
        try:
            row = await get_diagnosis(sess, _rid)
            return _Diagnosis.model_validate(row.diagnosis) if row is not None else None
        finally:
            await sess.close()

    old_text, new_text = _pagination_edit_pair()
    registry.register(
        _RunState.ANALYZING,
        ArchaeologistAgent(llm=FakeLLMProvider(), repo_root=FIXTURE_ROOT, save_fn=_save_analysis),
    )
    registry.register(
        _RunState.PLANNING,
        PlannerAgent(
            llm=FakeLLMProvider(
                agent_type="planner",
                canned={
                    "planner": {
                        "goal": "Add pagination to GET /todos",
                        "approach": "Slice the in-memory list with limit/offset.",
                        "steps": [{"title": "Update list_todos", "detail": "Add params."}],
                        "files_to_change": ["app/main.py"],
                        "files_to_add": [],
                        "tests": ["fixtures tests still pass"],
                        "risks": ["clients relying on full list"],
                        "rollback_strategy": "Revert the edit.",
                    }
                },
            ),
            repo_root=FIXTURE_ROOT,
            save_fn=_save_plan,
            findings_provider=_load_findings,
        ),
    )
    registry.register(
        _RunState.IMPLEMENTING,
        DeveloperAgent(
            llm=FakeLLMProvider(
                agent_type="developer",
                canned={
                    "developer": {
                        "edits": [
                            {
                                "path": "app/main.py",
                                "mode": "edit",
                                "old_text": old_text,
                                "new_text": new_text,
                            }
                        ],
                        "summary": "Paginated list_todos.",
                        "implementation_notes": ["limit/offset slice"],
                        "validation": ["fixture tests"],
                        "remaining_risks": [],
                    }
                },
            ),
            workspaces=WorkspaceManager(root=workspace_root, fixture_dir=FIXTURE_ROOT),
            save_fn=_save_impl,
            plan_provider=_load_plan,
            diagnosis_provider=_load_diag,
        ),
    )
    from app.agents.debugger import DebuggerAgent
    from app.agents.reviewer import ReviewerAgent
    from app.agents.tester import TesterAgent
    from app.auth.tokens import TokenCipher
    from app.github.client import FakeGitHubAPIClient
    from app.github.publisher import PublisherAgent

    _workspaces = WorkspaceManager(root=workspace_root, fixture_dir=FIXTURE_ROOT)
    # PR publisher on COMPLETED (Phase 4, #018): fixture runs have no
    # repo_url, so this no-ops — proving the hook is safe by default.
    from cryptography.fernet import Fernet

    registry.register(
        _RunState.COMPLETED,
        PublisherAgent(
            session_factory=factory,
            workspace_root=workspace_root,
            github_client=FakeGitHubAPIClient(),
            cipher=TokenCipher(Fernet.generate_key().decode()),
        ),
    )
    registry.register(
        _RunState.TESTING,
        TesterAgent(
            llm=FakeLLMProvider(
                agent_type="tester",
                canned={
                    "tester": {
                        "commands": [
                            "python -m pytest tests -q --tb=short -rf -p no:cacheprovider"
                        ],
                        "framework": "pytest",
                    }
                },
            ),
            workspaces=_workspaces,
            save_fn=_save_test,
        ),
    )
    registry.register(
        _RunState.DEBUGGING,
        DebuggerAgent(
            llm=FakeLLMProvider(
                agent_type="debugger",
                canned={
                    "debugger": {
                        "root_cause": "Pagination slice is off by one.",
                        "evidence": ["tests -q output"],
                        "fix_strategy": "Adjust the slice bounds and re-run.",
                        "confidence": 0.8,
                    }
                },
            ),
            workspaces=_workspaces,
            save_fn=_save_diag,
            test_result_provider=_load_report,
        ),
    )
    registry.register(
        _RunState.REVIEWING,
        ReviewerAgent(
            llm=FakeLLMProvider(
                agent_type="reviewer",
                canned={
                    "reviewer": {
                        "decision": "APPROVE",
                        "summary": "Minimal pagination change with passing tests.",
                        "findings": ["limit/offset slice in list_todos"],
                        "blocking_findings": [],
                    }
                },
            ),
            workspaces=_workspaces,
            save_fn=_save_review,
            memory_fn=_save_mem,
            plan_provider=_load_plan,
            test_result_provider=_load_report,
        ),
    )


@pytest_asyncio.fixture
async def orchestrator_app(
    auth_settings: Any, engine: AsyncEngine, tmp_path: Path
) -> AsyncIterator[tuple[AsyncClient, Orchestrator]]:
    """Full Phase 2 loop with policy auto-approval (default settings).

    The walk now ends parked in TESTING (Tester lands in #009).
    The client is logged in (fake OAuth) so tenancy-enforced routes
    (#016) work; create a project via ``ensure_project`` before
    POSTing runs. Takes ``engine`` (unused) to force
    truncation-before-login ordering (see ``authed_client``).
    """
    from app.config import get_settings

    _ = engine
    get_settings.cache_clear()

    from app.agents.policy import PolicyAutoApproveAgent
    from app.api.v1.auth import get_oauth_client
    from app.auth.github import FakeGitHubOAuthClient
    from app.db import session as db_session
    from app.main import create_app
    from app.orchestrator import Orchestrator, StateAgentRegistry
    from app.runs.enums import RunState as _RunState

    db_session.init_engine(auth_settings)
    app = create_app(auth_settings)
    app.dependency_overrides[get_oauth_client] = lambda: FakeGitHubOAuthClient()
    factory = db_session.get_session_factory()
    registry = StateAgentRegistry()
    _wire_test_agents(registry, factory, tmp_path / "workspaces")
    registry.register(_RunState.AWAITING_APPROVAL, PolicyAutoApproveAgent())
    orchestrator = Orchestrator(
        driver=registry,
        session_maker=factory,
    )
    app.state.orchestrator = orchestrator
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            login = await ac.get("/api/v1/auth/github/callback?code=any")
            assert login.status_code == 200, login.text
            yield ac, orchestrator
    finally:
        await orchestrator.shutdown()
        await db_session.dispose_engine()


@pytest_asyncio.fixture
async def manual_approval_app(
    auth_settings: Any, engine: AsyncEngine, tmp_path: Path
) -> AsyncIterator[tuple[AsyncClient, Orchestrator]]:
    """Phase 2 loop with a human in the approval seat (no policy agent).

    Runs park in AWAITING_APPROVAL so tests can approve or reject plans
    over HTTP and assert the approved_by audit trail. The client is
    logged in (fake OAuth); create a project via ``ensure_project``
    before POSTing runs. Takes ``engine`` (unused) to force
    truncation-before-login ordering (see ``authed_client``).
    """
    from app.config import get_settings

    _ = engine
    get_settings.cache_clear()

    from app.api.v1.auth import get_oauth_client
    from app.auth.github import FakeGitHubOAuthClient
    from app.db import session as db_session
    from app.main import create_app
    from app.orchestrator import Orchestrator, StateAgentRegistry

    db_session.init_engine(auth_settings)
    app = create_app(auth_settings)
    app.dependency_overrides[get_oauth_client] = lambda: FakeGitHubOAuthClient()
    factory = db_session.get_session_factory()
    registry = StateAgentRegistry()
    _wire_test_agents(registry, factory, tmp_path / "workspaces")
    from app.orchestrator import null_agent as _null_agent
    from app.runs.enums import RunState as _AwaitState

    registry.register(_AwaitState.AWAITING_APPROVAL, _null_agent)
    orchestrator = Orchestrator(
        driver=registry,
        session_maker=factory,
    )
    app.state.orchestrator = orchestrator
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            login = await ac.get("/api/v1/auth/github/callback?code=any")
            assert login.status_code == 200, login.text
            yield ac, orchestrator
    finally:
        await orchestrator.shutdown()
        await db_session.dispose_engine()
