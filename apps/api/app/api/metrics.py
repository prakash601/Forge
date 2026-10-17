"""Prometheus scrape endpoint (operational, unversioned like /health).

``GET /metrics`` serves the Prometheus exposition format. It is
deliberately unauthenticated: scrapers rarely hold user sessions.
In production it must only be reachable on the private network (the
prod compose exposes it to Prometheus, never through Caddy).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import func, select

from app.core.logging import get_logger
from app.metrics.registry import RUNS_BY_STATE, render_latest
from app.runs.enums import RunState

router = APIRouter(tags=["metrics"])
log = get_logger(__name__)


@router.get("/metrics", summary="Prometheus exposition")
async def metrics() -> Response:
    """Render counters plus best-effort runs-by-state gauge."""
    try:
        from app.db.session import get_session_factory
        from app.runs.models import Run

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(select(Run.state, func.count()).group_by(Run.state))
            ).all()
            seen = set()
            for state, count in rows:
                label = state.value if isinstance(state, RunState) else str(state)
                RUNS_BY_STATE.labels(state=label).set(int(count))
                seen.add(label)
            for state in RunState:
                if state.value not in seen:
                    RUNS_BY_STATE.labels(state=state.value).set(0)
    except Exception as exc:
        # Metrics must serve even when the DB is down.
        log.debug("metrics_db_gauge_skipped", error=str(exc))
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)


__all__ = ["router"]
