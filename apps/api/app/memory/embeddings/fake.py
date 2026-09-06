"""Deterministic fake provider for tests and CI.

Returns stable 1536-dim vectors derived from SHA-256 so CI never
calls a live API. Live OpenAI calls are never made in CI.
"""

from __future__ import annotations

import hashlib
import struct


class FakeEmbeddingProvider:
    """Fake ``EmbeddingProvider`` with deterministic output."""

    name = "fake"
    dimension = 1536

    def _vector_for(self, text: str) -> list[float]:
        out: list[float] = []
        counter = 0
        while len(out) < self.dimension:
            digest = hashlib.sha256(f"{text}:{counter}".encode()).digest()
            for i in range(0, len(digest), 8):
                (n,) = struct.unpack(">Q", digest[i : i + 8])
                out.append((n % 2000 - 1000) / 1000.0)
                if len(out) >= self.dimension:
                    break
            counter += 1
        return out

    async def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]


__all__ = ["FakeEmbeddingProvider"]
