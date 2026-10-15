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
from app.config import Settings, get_settings, unknown_forge_env_vars
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import (
    as_async_session_factory,
    dispose_engine,
    get_session_factory,
    init_engine,
)
from app.memory.embeddings.registry import get_provider
from app.metrics.middleware import metrics_middleware
from app.orchestrator import Orchestrator, StateAgentRegistry
from app.runs.enums import RunState

log = get_logger(__name__)

# Dev-only defaults from `.env.example` (LOCAL ONLY). These are sentinel
# values, never real secrets: booting in production with them is refused
# (see :func:`_reject_example_secrets`). Keep in sync with `.env.example`.
_DEV_JWT_PLACEHOLDER = (
    "dev-only-change-me-5f6163aea7e9413bd3b8e28b97a8fe0a440c0ee7187f31cb1979fed423b7a087"
)
_DEV_CREDENTIALS_KEY = "V8G0Rbuyy1qK3TI5qZmSE82-M_C-iEj6-3MGXD2JwSY="


def _reject_example_secrets(settings: Settings) -> None:
    """Refuse to boot production on the shipped dev-only secrets.

    Copy-pasting `.env.example` to a server is the expected accident;
    fail closed with rotation guidance instead of running (Issue #82).
    """
    if not settings.is_production:
        return
    offenders = [
        name
        for name, value in (
            ("FORGE_JWT_SECRET", settings.jwt_secret),
            ("FORGE_CREDENTIALS_KEY", settings.credentials_key),
        )
        if value in (_DEV_JWT_PLACEHOLDER, _DEV_CREDENTIALS_KEY)
    ]
    if offenders:
        raise RuntimeError(
            f"Refusing to boot: production uses dev-only example secrets "
            f"({', '.join(offenders)}). Generate fresh ones — see the "
            f"comments in `.env.example` — and set them in the environment."
        )


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
    for unknown in unknown_forge_env_vars():
        log.warning("unknown_forge_env_var", name=unknown)
    _reject_example_secrets(settings)
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
        from app.agents.persistence import (
            load_diagnosis,
            load_findings,
            load_memory_lines,
            load_plan,
            load_test_report,
            save_analysis_record,
            save_diagnosis_record,
            save_implementation_record,
            save_memory_record,
            save_plan_record,
            save_review_record,
            save_test_result_record,
        )
        from app.agents.planner import PlannerAgent
        from app.agents.reviewer import ReviewerAgent
        from app.agents.schemas import (
            ArchaeologistFindings as _Findings,
        )
        from app.agents.schemas import (
            DebuggerDiagnosis as _Diagnosis,
        )
        from app.agents.schemas import (
            DeveloperResult as _Result,
        )
        from app.agents.schemas import (
            Plan as _Plan,
        )
        from app.agents.schemas import (
            ReviewDecision as _Decision,
        )
        from app.agents.schemas import (
            TestReport as _Report,
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
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(findings, _Findings)
            await save_analysis_record(
                factory, run_id=run_id, findings=findings, provider=provider, model=model
            )

        async def _load_memory(run_id: uuid.UUID | None = None) -> list[str]:
            provider = getattr(app.state, "embedding_provider", None)
            try:
                return await load_memory_lines(factory, provider, run_id=run_id)
            except Exception:
                return []

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
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(plan, _Plan)
            await save_plan_record(
                factory, run_id=run_id, plan=plan, provider=provider, model=model
            )

        async def _load_findings(*, run_id: object) -> object:
            assert isinstance(run_id, (uuid.UUID, str))
            return await load_findings(factory, run_id=run_id)

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
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(result, _Result)
            await save_implementation_record(
                factory,
                run_id=run_id,
                result=result,
                provider=provider,
                model=model,
                workspace_path=workspace_path,
            )

        async def _load_plan(*, run_id: object) -> object:
            assert isinstance(run_id, (uuid.UUID, str))
            return await load_plan(factory, run_id=run_id)

        _workspaces = WorkspaceManager(
            root=_Path(settings.workspace_root),
            fixture_dir=_Path(settings.fixture_repo_path),
        )

        async def _load_diagnosis(*, run_id: object) -> object:
            assert isinstance(run_id, (uuid.UUID, str))
            return await load_diagnosis(factory, run_id=run_id)

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
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(result, _Report)
            await save_test_result_record(
                factory,
                run_id=run_id,
                result=result,
                provider=str(kwargs.get("provider", "unknown")),
                model=str(kwargs.get("model", "unknown")),
            )

        async def _load_test_report(*, run_id: object) -> object:
            assert isinstance(run_id, (uuid.UUID, str))
            return await load_test_report(factory, run_id=run_id)

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
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(diagnosis, _Diagnosis)
            await save_diagnosis_record(
                factory,
                run_id=run_id,
                diagnosis=diagnosis,
                provider=str(kwargs.get("provider", "unknown")),
                model=str(kwargs.get("model", "unknown")),
            )

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
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(review, _Decision)
            await save_review_record(
                factory,
                run_id=run_id,
                review=review,
                provider=str(kwargs.get("provider", "unknown")),
                model=str(kwargs.get("model", "unknown")),
            )

        async def _save_memory(*, run_id: object, candidates: object) -> None:
            assert isinstance(run_id, (uuid.UUID, str))
            assert isinstance(candidates, list)
            await save_memory_record(factory, run_id=run_id, candidates=candidates)

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
        # Fail fast: silently falling back to stub agents would ship a
        # degraded loop to prod with only a warning (Issue #82).
        log.error("agents_wire_failed", error=str(exc))
        raise RuntimeError("Agent wiring failed; refusing to boot with stub agents.") from exc
    orchestrator = Orchestrator(
        driver=registry,
        session_factory=as_async_session_factory(factory),
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
    # Methods/headers are explicit (never "*" with credentials): the
    # dashboard only needs JSON GET/POST/PUT/PATCH/DELETE plus the
    # auth/content headers (Issue #82).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    install_exception_handlers(app)
    app.middleware("http")(metrics_middleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


# Module-level instance for `uvicorn apps.api.app.main:app`.
app = create_app()
