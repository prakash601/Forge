"""Embedding provider seam.

Mirrors ``app.orchestrator.protocols``: the pipeline depends only on
the ``EmbeddingProvider`` protocol, not on concrete implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Generates dense vectors for memory content."""

    name: str
    dimension: int

    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


__all__ = ["EmbeddingProvider"]
