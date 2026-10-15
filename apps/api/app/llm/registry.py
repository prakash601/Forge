"""LLM provider factory keyed by config; mirrors embeddings registry."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.core.providers import pick_provider
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
    base_url: str | None = None,
) -> LLMProvider:
    """Return the LLM provider for ``provider_name``.

    ``fake`` (CI/tests), ``openai`` (api.openai.com), or ``opencode``
    (OpenCode inference ``https://opencode.ai/inference/openai/v1``,
    OpenAI-compatible chat completions). ``base_url`` overrides the
    endpoint root for ``openai``/``opencode`` (``/chat/completions``
    is appended), so any OpenAI-compatible gateway works.

    Raises:
        ValueError: unknown provider name.
    """
    builders: dict[str, Callable[[], LLMProvider]] = {
        "fake": FakeLLMProvider,
        "openai": lambda: OpenAILLMProvider(
            api_key=api_key,
            model=model,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url,
        ),
        "opencode": lambda: OpenAILLMProvider(
            api_key=api_key,
            model=model,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url or OpenAILLMProvider.OPENCODE_BASE_URL,
            name="opencode",
        ),
    }
    return pick_provider(provider_name, "LLM", builders)


__all__ = ["get_llm_provider"]
