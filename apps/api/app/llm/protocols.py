"""LLM provider seam.

Mirrors ``app.memory.embeddings``: Phase 2 agents depend only on the
``LLMProvider`` protocol, not on concrete implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMResult:
    """Structured result of one ``complete_json`` call.

    ``parsed`` is the provider output validated against the caller's
    schema. Token counts come from the provider's usage block (zero
    when the provider does not report usage, e.g. the fake).
    """

    parsed: BaseModel
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str


@runtime_checkable
class LLMProvider(Protocol):
    """Produces schema-validated JSON via an LLM."""

    name: str

    async def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        model: str | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult: ...


__all__ = ["LLMProvider", "LLMResult"]
