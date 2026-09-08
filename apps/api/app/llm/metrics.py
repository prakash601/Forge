"""Emission-only counters for LLM calls.

Exposes ``forge_llm_*`` counters without adding a metrics dependency:
in-process totals keyed by ``(metric, provider, ...)`` labels. A future
Prometheus bridge can scrape these; cost dashboards are out of scope
(Issue #005) — this module only emits.
"""

from __future__ import annotations

import threading

CALLS_TOTAL = "forge_llm_calls_total"
INPUT_TOKENS_TOTAL = "forge_llm_input_tokens_total"
OUTPUT_TOKENS_TOTAL = "forge_llm_output_tokens_total"

_counters: dict[tuple[str, ...], int] = {}
_lock = threading.Lock()


def record_call(*, provider: str, model: str, outcome: str) -> None:
    """Increment the per-call counter for ``(provider, model, outcome)``."""
    with _lock:
        key = (CALLS_TOTAL, provider, model, outcome)
        _counters[key] = _counters.get(key, 0) + 1


def record_tokens(*, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
    """Add token usage to the per-provider, per-model totals."""
    with _lock:
        in_key = (INPUT_TOKENS_TOTAL, provider, model)
        out_key = (OUTPUT_TOKENS_TOTAL, provider, model)
        _counters[in_key] = _counters.get(in_key, 0) + input_tokens
        _counters[out_key] = _counters.get(out_key, 0) + output_tokens


def get_counters() -> dict[tuple[str, ...], int]:
    """Return a snapshot of all counters (for tests and future exporters)."""
    with _lock:
        return dict(_counters)


def reset_counters() -> None:
    """Clear all counters. Tests only — never call in production code."""
    with _lock:
        _counters.clear()


__all__ = [
    "CALLS_TOTAL",
    "INPUT_TOKENS_TOTAL",
    "OUTPUT_TOKENS_TOTAL",
    "get_counters",
    "record_call",
    "record_tokens",
    "reset_counters",
]
