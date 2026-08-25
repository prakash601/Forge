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
from app.db.session import dispose_engine, init_engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and graceful shutdown.

    Startup:
      - Configure structured logging.
      - Initialize the database engine.
      - Log "api_started" with the bind address.

    Shutdown:
      - Dispose the database engine.
      - Log "api_stopped".
    """
    settings: Settings = app.state.settings
    configure_logging(settings)
    init_engine(settings)
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
