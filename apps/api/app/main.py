"""Application entrypoint.

The factory in `create_app()` is the single source of truth for the FastAPI
application. It is reused by:

- `uvicorn apps.api.app.main:app` for production.
- `fastapi dev apps.api/app/main.py` for local development with reload.
- The test suite, via `from app.main import create_app; app = create_app()`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.health import router as health_router
from app.api.v1 import router as api_v1_router
from app.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_session_factory, init_engine
from app.memory.embeddings.registry import get_provider
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
    # Issue #007: wire the real Archaeologist for ANALYZING. The stub
    # remains registered for CREATED/PLANNING/AWAITING_APPROVAL/
    # IMPLEMENTING so the rest of the loop still walks in Phase 2.
    try:
        from pathlib import Path as _Path

        from app.agents.archaeologist import ArchaeologistAgent
        from app.agents.service import save_analysis
        from app.llm.registry import get_llm_provider

        _llm = get_llm_provider(
            provider_name=settings.llm_provider,
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
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

        _archaeologist = ArchaeologistAgent(
            llm=_llm,
            repo_root=_Path(settings.fixture_repo_path),
            save_fn=_save_analysis,
            model=settings.llm_model,
        )
        registry.register(RunState.ANALYZING, _archaeologist)
        app.state.archaeologist = _archaeologist
        app.state.llm_provider = _llm
    except Exception as exc:
        log.warning("archaeologist_wire_failed", error=str(exc))
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
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


# Module-level instance for `uvicorn apps.api.app.main:app`.
app = create_app()
