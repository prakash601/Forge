"""Per-process sliding-window rate limiter (Phase 4, Issue #82).

Guards the unauthenticated entry points (open signup, dev-login, OAuth
callback) against abuse. State lives on the app instance
(``app.state``), so every test app gets fresh buckets and the limiter
needs no external store — correct for the single-host prod target.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.logging import get_logger

log = get_logger(__name__)


class RateLimiter:
    """Sliding-window counter keyed by an opaque string (client IP)."""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """Record a hit; True when under budget, False when throttled."""
        at = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= at - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(at)
        return True

    def retry_after_seconds(self, key: str, *, now: float | None = None) -> int:
        """Seconds until the oldest hit ages out (for ``Retry-After``)."""
        at = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(0, int(hits[0] + self._window - at) + 1)


def limited(
    scope: str, *, limit: int, window_seconds: float = 60.0
) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """FastAPI dependency factory: 429s callers over budget for ``scope``."""

    async def _limit_requests(request: Request) -> None:
        attr = f"_rate_limiter_{scope}"
        limiter = getattr(request.app.state, attr, None)
        if limiter is None:
            limiter = RateLimiter(limit=limit, window_seconds=window_seconds)
            setattr(request.app.state, attr, limiter)
        key = request.client.host if request.client else "unknown"
        if not limiter.allow(key):
            log.warning(
                "rate_limited",
                scope=scope,
                client=key,
                request_id=getattr(request.state, "request_id", ""),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "Too many requests; slow down and retry.",
                    "request_id": getattr(request.state, "request_id", ""),
                },
                headers={"Retry-After": str(limiter.retry_after_seconds(key))},
            )

    return _limit_requests


__all__ = ["RateLimiter", "limited"]
