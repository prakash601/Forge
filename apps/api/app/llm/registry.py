"""LLM provider factory keyed by config; mirrors embeddings registry."""

from __future__ import annotations

import httpx

from app.llm.fake import FakeLLMProvider
from app.llm.openai_provider import OpenAILLMProvider
from app.llm.protocols import LLMProvider


def get_llm_provider(
    *,
    provider_name: str = "fake",
    api_key: str | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    timeout_seconds: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> LLMProvider:
    """Return the LLM provider for ``provider_name``.

    Only ``fake`` (CI/tests) and ``openai`` exist; Anthropic will sit
    behind the same seam later.

    Raises:
        ValueError: unknown provider name.
    """
    normalized = provider_name.strip().lower()
    if normalized == "fake":
        return FakeLLMProvider()
    if normalized == "openai":
        return OpenAILLMProvider(
            api_key=api_key,
            model=model,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            client=client,
        )
    raise ValueError(f"unknown LLM provider: {provider_name!r}")


__all__ = ["get_llm_provider"]
