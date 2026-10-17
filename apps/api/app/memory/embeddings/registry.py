"""Provider factory keyed by config; mirrors orchestrator registry."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.core.providers import pick_provider
from app.memory.embeddings.fake import FakeEmbeddingProvider
from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider
from app.memory.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.memory.embeddings.protocols import EmbeddingProvider


def get_provider(
    *,
    provider_name: str = "fake",
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 30.0,
    client: httpx.AsyncClient | None = None,
    dimension: int | None = None,
) -> EmbeddingProvider:
    """Return the provider for ``provider_name``.

    ``fake`` (CI/tests), ``openai`` (fixed 1536 dims), or ``gemini``
    (Gemini ``embedContent``; ``dimension`` sets ``outputDimensionality``
    and defaults to 1536 to match the ``VECTOR`` column). A ``model``
    equal to the OpenAI default is treated as unspecified for gemini,
    since ``Settings`` always passes its own default down.

    Raises:
        ValueError: unknown provider name.
    """
    resolved_model = model
    if resolved_model in (None, OpenAIEmbeddingProvider.model):
        resolved_model = None
    builders: dict[str, Callable[[], EmbeddingProvider]] = {
        "fake": FakeEmbeddingProvider,
        "openai": lambda: OpenAIEmbeddingProvider(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            client=client,
        ),
        "gemini": lambda: GeminiEmbeddingProvider(
            api_key=api_key,
            model=resolved_model,
            dimension=dimension,
            timeout_seconds=timeout_seconds,
            client=client,
        ),
    }
    return pick_provider(provider_name, "embedding", builders)


__all__ = ["get_provider"]
