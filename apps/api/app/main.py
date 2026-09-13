"""Application entrypoint.

The factory in `create_app()` is the single source of truth for the FastAPI
application. It is reused by:

- `uvicorn apps.api.app.main:app` for production.
- `fastapi dev apps.api/app/main.py` for local development with reload.
- The test suite, via `from app.main import create_app; app = create_app()`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.v1 import router as api_v1_router
from app.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_session_factory, init_engine
from app.memory.embeddings.registry import get_provider
from app.metrics.middleware import metrics_middleware
from app.orchestrator import Orchestrator, StateAgentRegistry
from app.runs.enums import RunState

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and graceful shutdown.

    Startup:
      - Configure structured logging.
      - Initialize the database engine.
      - Build the orchestrator (in-process for Phase 1).
      - Log "api_started" with the bind address.

    Shutdown:
      - Drain outstanding orchestrator tasks.
      - Dispose the database engine.
      - Log "api_stopped".
    """
    settings: Settings = app.state.settings
    configure_logging(settings)
    init_engine(settings)
    factory = get_session_factory()
    registry = StateAgentRegistry()
    # Issues #007/#008: wire the real agents. The stub remains only
    # for CREATED (repository_ready) until repository onboarding lands.
    try:
        from pathlib import Path as _Path

        from app.agents.archaeologist import ArchaeologistAgent
        from app.agents.debugger import DebuggerAgent
        from app.agents.developer import DeveloperAgent
        from app.agents.planner import PlannerAgent
        from app.agents.reviewer import ReviewerAgent
        from app.agents.service import (
            get_analysis,
            get_plan,
            save_analysis,
            save_implementation,
            save_plan,
        )
        from app.agents.tester import TesterAgent
        from app.agents.workspace import WorkspaceManager
        from app.auth.tokens import TokenCipher
        from app.github.client import RealGitHubAPIClient
        from app.github.publisher import PublisherAgent
        from app.llm.registry import get_llm_provider

        _llm = get_llm_provider(
            provider_name=settings.llm_provider,
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            base_url=settings.llm_base_url,
        )

        async def _save_analysis(
            *, run_id: object, findings: object, provider: str, model: str
        ) -> None:
            import uuid as _uuid

            from app.agents.schemas import ArchaeologistFindings as _Findings

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(findings, _Findings)
            session = factory()
            try:
                await save_analysis(
                    session, run_id=_rid, findings=findings, provider=provider, model=model
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        async def _load_memory(run_id: uuid.UUID | None = None) -> list[str]:
            from app.agents.service import get_latest_memory
            from app.memory.service import search_similar_memories
            from app.runs.service import get_run

            session = factory()
            try:
                # Fail closed: without a run (or a project on it) there
                # is no memory — a global fallback would leak one
                # owner's outcomes into another's archaeology (#016).
                if run_id is None:
                    return []
                try:
                    run = await get_run(session, run_id)
                except Exception:
                    return []
                if run.project_id is None:
                    return []
                lines: list[str] = []
                row = await get_latest_memory(session, project_id=run.project_id)
                if row is not None:
                    lines.extend(
                        f"{c.get('memory_type', 'NOTE')}: {c.get('content', '')}"
                        for c in row.candidates
                        if isinstance(c, dict)
                    )
                # Vector recall: nearest ACTIVE memories to the task
                # text, so old but relevant learnings surface even when
                # they are not the latest. Same per-project scoping;
                # any failure degrades to latest-memory lines only.
                try:
                    provider = getattr(app.state, "embedding_provider", None)
                    if provider is not None and run.task.strip():
                        query = await provider.embed(run.task)
                        similar = await search_similar_memories(
                            session,
                            project_id=run.project_id,
                            query_embedding=query,
                            limit=5,
                        )
                        for item in similar:
                            line = f"{item.memory_type}: {item.content}"
                            if line not in lines:
                                lines.append(line)
                except Exception:
                    log.warning("memory_vector_recall_failed", run_id=str(run_id))
                return lines
            except Exception:
                return []
            finally:
                await session.close()

        _archaeologist = ArchaeologistAgent(
            llm=_llm,
            repo_root=_Path(settings.fixture_repo_path),
            save_fn=_save_analysis,
            memory_reader=_load_memory,
            model=settings.llm_model,
        )
        registry.register(RunState.ANALYZING, _archaeologist)
        app.state.archaeologist = _archaeologist
        app.state.llm_provider = _llm

        async def _save_plan(*, run_id: object, plan: object, provider: str, model: str) -> None:
            import uuid as _uuid

            from app.agents.schemas import Plan as _Plan

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(plan, _Plan)
            session = factory()
            try:
                await save_plan(session, run_id=_rid, plan=plan, provider=provider, model=model)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        async def _load_findings(*, run_id: object) -> object:
            import uuid as _uuid

            from app.agents.schemas import ArchaeologistFindings as _Findings

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            session = factory()
            try:
                row = await get_analysis(session, _rid)
                if row is None:
                    return None
                return _Findings.model_validate(row.findings)
            finally:
                await session.close()

        _planner = PlannerAgent(
            llm=_llm,
            repo_root=_Path(settings.fixture_repo_path),
            save_fn=_save_plan,
            findings_provider=_load_findings,
            model=settings.llm_model,
        )
        registry.register(RunState.PLANNING, _planner)
        app.state.planner = _planner

        async def _save_implementation(
            *,
            run_id: object,
            result: object,
            provider: str,
            model: str,
            workspace_path: str,
        ) -> None:
            import uuid as _uuid

            from app.agents.schemas import DeveloperResult as _Result

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(result, _Result)
            session = factory()
            try:
                await save_implementation(
                    session,
                    run_id=_rid,
                    result=result,
                    provider=provider,
                    model=model,
                    workspace_path=workspace_path,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        async def _load_plan(*, run_id: object) -> object:
            import uuid as _uuid

            from app.agents.schemas import Plan as _Plan

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            session = factory()
            try:
                row = await get_plan(session, _rid)
                if row is None:
                    return None
                return _Plan.model_validate(row.plan)
            finally:
                await session.close()

        _workspaces = WorkspaceManager(
            root=_Path(settings.workspace_root),
            fixture_dir=_Path(settings.fixture_repo_path),
        )

        async def _load_diagnosis(*, run_id: object) -> object:
            import uuid as _uuid

            from app.agents.schemas import DebuggerDiagnosis as _Diagnosis
            from app.agents.service import get_diagnosis

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            session = factory()
            try:
                row = await get_diagnosis(session, _rid)
                if row is None:
                    return None
                return _Diagnosis.model_validate(row.diagnosis)
            finally:
                await session.close()

        _developer = DeveloperAgent(
            llm=_llm,
            workspaces=_workspaces,
            save_fn=_save_implementation,
            plan_provider=_load_plan,
            diagnosis_provider=_load_diagnosis,
            model=settings.llm_model,
        )
        registry.register(RunState.IMPLEMENTING, _developer)
        app.state.developer = _developer

        async def _save_test_result(*, run_id: object, result: object, **kwargs: object) -> None:
            import uuid as _uuid

            from app.agents.schemas import TestReport as _Report
            from app.agents.service import save_test_result

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(result, _Report)
            session = factory()
            try:
                await save_test_result(
                    session,
                    run_id=_rid,
                    result=result,
                    provider=str(kwargs.get("provider", "unknown")),
                    model=str(kwargs.get("model", "unknown")),
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        async def _load_test_report(*, run_id: object) -> object:
            import uuid as _uuid

            from app.agents.schemas import TestReport as _Report
            from app.agents.service import get_test_result

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            session = factory()
            try:
                row = await get_test_result(session, _rid)
                if row is None:
                    return None
                return _Report.model_validate(row.result)
            finally:
                await session.close()

        _tester = TesterAgent(
            llm=_llm,
            workspaces=_workspaces,
            save_fn=_save_test_result,
            model=settings.llm_model,
            timeout_seconds=settings.test_timeout_seconds,
        )
        registry.register(RunState.TESTING, _tester)
        app.state.tester = _tester

        async def _save_diagnosis(*, run_id: object, diagnosis: object, **kwargs: object) -> None:
            import uuid as _uuid

            from app.agents.schemas import DebuggerDiagnosis as _Diagnosis
            from app.agents.service import save_diagnosis

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(diagnosis, _Diagnosis)
            session = factory()
            try:
                await save_diagnosis(
                    session,
                    run_id=_rid,
                    diagnosis=diagnosis,
                    provider=str(kwargs.get("provider", "unknown")),
                    model=str(kwargs.get("model", "unknown")),
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        _debugger = DebuggerAgent(
            llm=_llm,
            workspaces=_workspaces,
            save_fn=_save_diagnosis,
            test_result_provider=_load_test_report,
            model=settings.llm_model,
        )
        registry.register(RunState.DEBUGGING, _debugger)
        app.state.debugger = _debugger

        async def _save_review(*, run_id: object, review: object, **kwargs: object) -> None:
            import uuid as _uuid

            from app.agents.schemas import ReviewDecision as _Decision
            from app.agents.service import save_review

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(review, _Decision)
            session = factory()
            try:
                await save_review(
                    session,
                    run_id=_rid,
                    review=review,
                    provider=str(kwargs.get("provider", "unknown")),
                    model=str(kwargs.get("model", "unknown")),
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        async def _save_memory(*, run_id: object, candidates: object) -> None:
            import uuid as _uuid

            from app.agents.service import save_memory

            _rid = run_id if isinstance(run_id, _uuid.UUID) else _uuid.UUID(str(run_id))
            assert isinstance(candidates, list)
            session = factory()
            try:
                await save_memory(session, run_id=_rid, candidates=candidates)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

        _reviewer = ReviewerAgent(
            llm=_llm,
            workspaces=_workspaces,
            save_fn=_save_review,
            memory_fn=_save_memory,
            plan_provider=_load_plan,
            test_result_provider=_load_test_report,
            model=settings.llm_model,
        )
        registry.register(RunState.REVIEWING, _reviewer)
        app.state.reviewer = _reviewer

        # PR publisher on COMPLETED entry (Phase 4, Issue #018). Returns
        # None always: the run stays COMPLETED; failures land on the
        # pull_requests row. Skips silently without a credentials key.
        _cipher: TokenCipher | None = None
        if settings.credentials_key:
            try:
                _cipher = TokenCipher(settings.credentials_key)
            except ValueError:
                _cipher = None
        _publisher = PublisherAgent(
            session_factory=factory,
            workspace_root=_Path(settings.workspace_root),
            github_client=RealGitHubAPIClient(),
            cipher=_cipher,
        )
        registry.register(RunState.COMPLETED, _publisher)
        app.state.publisher = _publisher

        # Plan approval gate (Phase 4, Issue #020): policy approval only
        # under the global env or the run's project opt-in; otherwise the
        # run waits for a human. Replaces the auto_approve if/else: the
        # decision is per-run now, not per-deploy.
        from app.agents.policy import ProjectPolicyAgent

        registry.register(
            RunState.AWAITING_APPROVAL,
            ProjectPolicyAgent(
                session_factory=factory,
                global_auto_approve=settings.auto_approve,
            ),
        )
    except Exception as exc:
        log.warning("agents_wire_failed", error=str(exc))
    orchestrator = Orchestrator(
        driver=registry,
        session_maker=factory,
    )
    app.state.orchestrator = orchestrator
    # Embedding provider for the memory pipeline (Issue #004). Built
    # from settings so tests/CI use the fake provider; production
    # sets FORGE_EMBEDDING_PROVIDER=openai with a key.
    app.state.embedding_provider = get_provider(
        provider_name=settings.embedding_provider,
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout_seconds,
        dimension=settings.embedding_dimension,
    )
    log.info(
        "api_started",
        version=__version__,
        environment=settings.environment,
        host=settings.api_host,
        port=settings.api_port,
    )
    try:
        yield
    finally:
        await orchestrator.shutdown()
        provider = getattr(app.state, "embedding_provider", None)
        aclose = getattr(provider, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception as exc:
                log.warning("embedding_provider_close_failed", error=str(exc))
        await dispose_engine()
        log.info("api_stopped", version=__version__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    The `settings` argument is overridable for tests. When omitted, the
    process-wide cached settings are used.
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Forge API",
        version=__version__,
        description=(
            "Forge control-plane API. Phase 0 exposes only the operational "
            "endpoints (`/health`, `/ready`). Application endpoints under "
            "`/api/v1` are introduced starting in Phase 1."
        ),
        lifespan=lifespan,
    )

    app.state.settings = settings

    # CORS — only honored in development. Production deployments should
    # terminate TLS at the gateway and configure CORS at that layer.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_exception_handlers(app)
    app.middleware("http")(metrics_middleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


# Module-level instance for `uvicorn apps.api.app.main:app`.
app = create_app()
