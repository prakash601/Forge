"""Provider factory keyed by config; mirrors orchestrator registry."""

from __future__ import annotations

import httpx

from app.memory.embeddings.fake import FakeEmbeddingProvider
from app.memory.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.memory.embeddings.protocols import EmbeddingProvider


def get_provider(
    *,
    provider_name: str = "fake",
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> EmbeddingProvider:
    """Return the provider for ``provider_name``.

    Raises:
        ValueError: unknown provider name.
    """
    normalized = provider_name.strip().lower()
    if normalized == "fake":
        return FakeEmbeddingProvider()
    if normalized == "openai":
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            client=client,
        )
    raise ValueError(f"unknown embedding provider: {provider_name!r}")


__all__ = ["get_provider"]
