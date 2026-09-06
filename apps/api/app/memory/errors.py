"""Typed exceptions for the memory service."""

from __future__ import annotations


class MemoryItemNotFoundError(LookupError):
    """No MemoryItem exists with the given identifier."""

    def __init__(self, memory_item_id: str) -> None:
        super().__init__(memory_item_id)
        self.memory_item_id = memory_item_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"MemoryItem {self.memory_item_id!r} does not exist."


class EmbeddingProviderError(RuntimeError):
    """The embedding provider call failed (network, auth, rate limit)."""


class EmbeddingDimensionMismatchError(ValueError):
    """The provider returned a vector with an unexpected dimension."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"expected dimension {expected}, got {actual}")
        self.expected = expected
        self.actual = actual


__all__ = [
    "EmbeddingDimensionMismatchError",
    "EmbeddingProviderError",
    "MemoryItemNotFoundError",
]
