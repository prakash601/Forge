"""OpenAI LLM provider (default ``gpt-4o-mini``) in strict JSON-schema mode.

Uses ``httpx.AsyncClient`` (already a dependency) against the chat
completions endpoint with ``response_format`` JSON schema in strict
mode. The client is created lazily per call when not supplied so
tests can inject a fake transport. HTTP failures are wrapped in
``LLMProviderError``; invalid JSON or schema violations surface as
``SchemaValidationError``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.llm.errors import LLMProviderError, SchemaValidationError
from app.llm.observability import emit_llm_call
from app.llm.protocols import LLMResult


class OpenAILLMProvider:
    """Concrete provider for OpenAI chat models with structured output."""

    name = "openai"
    model = "gpt-4o-mini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        if model is not None:
            self.model = model
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None

    async def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        model: str | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        resolved_model = model or self.model
        resolved_tokens = max_output_tokens or self._max_output_tokens or 1024
        resolved_timeout = timeout_s if timeout_s is not None else self._timeout_seconds
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
            "max_completion_tokens": resolved_tokens,
        }
        start = time.perf_counter()

        def _latency_ms() -> int:
            return int((time.perf_counter() - start) * 1000)

        try:
            if self._client is not None:
                response = await self._client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=resolved_timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=resolved_timeout) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=resolved_timeout,
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            latency_ms = _latency_ms()
            emit_llm_call(
                provider=self.name,
                model=resolved_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                attempt=1,
                outcome="error",
                error=str(exc),
            )
            raise LLMProviderError(str(exc)) from exc

        try:
            data = response.json()
            message = data["choices"][0]["message"]
            refusal = message.get("refusal")
            if refusal:
                raise LLMProviderError(f"model refused the request: {refusal}")
            content = message.get("content")
            raw = json.loads(content) if isinstance(content, str) else content
            parsed = schema.model_validate(raw)
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except LLMProviderError as exc:
            emit_llm_call(
                provider=self.name,
                model=resolved_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=_latency_ms(),
                attempt=1,
                outcome="error",
                error=str(exc),
            )
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            emit_llm_call(
                provider=self.name,
                model=resolved_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=_latency_ms(),
                attempt=1,
                outcome="error",
                error=str(exc),
            )
            raise SchemaValidationError(str(exc)) from exc

        latency_ms = _latency_ms()
        emit_llm_call(
            provider=self.name,
            model=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            attempt=1,
            outcome="success",
        )
        return LLMResult(
            parsed=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            model=resolved_model,
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()


__all__ = ["OpenAILLMProvider"]
