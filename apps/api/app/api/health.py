"""Health, readiness, and version endpoints.

These endpoints are intentionally outside the versioned `/api/v1` prefix
because they are operational concerns consumed by orchestrators and humans,
not by application clients.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.core.logging import get_logger
from app.db.session import ping_database

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Liveness probe.

    Returns 200 OK as long as the process is running. It does NOT depend
    on the database. Use `/ready` to verify downstream dependencies.
    """
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness probe",
    response_model=None,  # Union return type; FastAPI must not build a response model.
)
async def ready(request: Request) -> dict[str, str] | JSONResponse:
    """Readiness probe.

    Returns 200 OK only when all required dependencies (PostgreSQL) are
    reachable. Returns 503 otherwise. Used by load balancers and the
    Docker healthcheck to decide when to route traffic to this instance.
    """
    try:
        await ping_database()
    except Exception as exc:
        log.warning(
            "readiness_check_failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": "database_unreachable"},
        )

    return {"status": "ok", "version": __version__}
