"""Shared per-call observability for LLM providers.

Every ``complete_json`` call emits one ``llm_call`` structlog event with
``provider``, ``model``, token counts, ``latency_ms``, ``attempt``, and
``outcome`` — plus ``forge_llm_*`` counter increments. Prompts and API
keys are never logged.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.llm import metrics

log = get_logger(__name__)


def emit_llm_call(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    attempt: int,
    outcome: str,
    error: str | None = None,
) -> None:
    """Log one LLM call and record its counters.

    ``outcome`` is ``"success"`` or ``"error"`` (kept low-cardinality
    for the counters); failure detail goes in ``error`` (log only).
    """
    log.info(
        "llm_call",
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        attempt=attempt,
        outcome=outcome,
        error=error,
    )
    metrics.record_call(provider=provider, model=model, outcome=outcome)
    if outcome == "success":
        metrics.record_tokens(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


__all__ = ["emit_llm_call"]
