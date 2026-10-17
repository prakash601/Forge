"""HTTP metrics middleware (Phase 4, Issue #019)."""

from __future__ import annotations

from typing import Any

from app.metrics.registry import record_http_request


def _route_template(request: Any) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unknown"


async def metrics_middleware(request: Any, call_next: Any) -> Any:
    """Count every request except ``/metrics`` itself (avoid self-feedback)."""
    response = await call_next(request)
    if request.url.path != "/metrics":
        record_http_request(
            method=request.method,
            route=_route_template(request),
            status=response.status_code,
        )
    return response


__all__ = ["metrics_middleware"]
