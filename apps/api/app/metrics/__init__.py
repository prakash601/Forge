"""Metrics package (Phase 4, Issue #019, decided in #60).

Prometheus exposition for the Forge API: HTTP counts, run lifecycle,
and the LLM-counter bridge. See :mod:`app.metrics.registry`.
"""

from __future__ import annotations

from app.metrics import middleware, registry

__all__ = ["middleware", "registry"]
