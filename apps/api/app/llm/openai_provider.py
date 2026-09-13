"""OpenAI-compatible LLM provider (default ``gpt-4o-mini``) with JSON output.

Uses ``httpx.AsyncClient`` (already a dependency) against the chat
completions endpoint. ``base_url`` makes any OpenAI-compatible gateway
work — e.g. OpenCode inference at
``https://opencode.ai/inference/openai/v1`` — by appending
``/chat/completions``.

Strict ``response_format`` JSON-schema mode is tried first; gateways
that reject it (HTTP 400) are retried once in plain-JSON mode with an
explicit "respond with JSON only" instruction plus fenced-code
extraction. HTTP failures are wrapped in ``LLMProviderError``; invalid
JSON or schema violations surface as ``SchemaValidationError``.
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


def _prompt_for(prompt: str, schema: type[BaseModel], strict: bool) -> str:
    """Return the user prompt, with a JSON-only instruction when not strict."""
    if strict:
        return prompt
    return (
        f"{prompt}\n\nRespond with a single JSON object only (no prose, "
        "no code fences) matching this JSON schema:\n"
        f"{json.dumps(schema.model_json_schema())}"
    )


def _extract_json(content: str) -> Any:
    """Parse model text into JSON, tolerating fences and stray prose."""
    text = content.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        try:
            return json.loads("\n".join(lines))
        except ValueError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("model output did not contain a JSON object")


class OpenAILLMProvider:
    """Concrete provider for OpenAI chat models with structured output."""

    name = "openai"
    model = "gpt-4o-mini"

    #: Default chat-completions roots (``/chat/completions`` is appended).
    OPENAI_BASE_URL = "https://api.openai.com/v1"
    OPENCODE_BASE_URL = "https://opencode.ai/inference/openai/v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        name: str | None = None,
    ) -> None:
        self._api_key = api_key
        if model is not None:
            self.model = model
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None
        self._base_url = (base_url or self.OPENAI_BASE_URL).rstrip("/")
        if name is not None:
            self.name = name

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
        url = f"{self._base_url}/chat/completions"
        start = time.perf_counter()

        def _latency_ms() -> int:
            return int((time.perf_counter() - start) * 1000)

        # Attempt 1: strict JSON-schema mode. Attempt 2 (only when the
        # gateway rejects strict mode with 400): plain-JSON mode.
        strict = True
        for attempt in (1, 2):
            payload: dict[str, Any] = {
                "model": resolved_model,
                "messages": [{"role": "user", "content": _prompt_for(prompt, schema, strict)}],
                "max_completion_tokens": resolved_tokens,
            }
            if strict:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    },
                }
            try:
                if self._client is not None:
                    response = await self._client.post(
                        url, json=payload, headers=headers, timeout=resolved_timeout
                    )
                else:
                    async with httpx.AsyncClient(timeout=resolved_timeout) as client:
                        response = await client.post(
                            url, json=payload, headers=headers, timeout=resolved_timeout
                        )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if strict and exc.response.status_code == 400:
                    # Gateway does not support strict mode — retry plain.
                    strict = False
                    continue
                latency_ms = _latency_ms()
                emit_llm_call(
                    provider=self.name,
                    model=resolved_model,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    attempt=attempt,
                    outcome="error",
                    error=str(exc),
                )
                raise LLMProviderError(str(exc)) from exc
            except httpx.HTTPError as exc:
                latency_ms = _latency_ms()
                emit_llm_call(
                    provider=self.name,
                    model=resolved_model,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    attempt=attempt,
                    outcome="error",
                    error=str(exc),
                )
                raise LLMProviderError(str(exc)) from exc
            break

        try:
            data = response.json()
            message = data["choices"][0]["message"]
            refusal = message.get("refusal")
            if refusal:
                raise LLMProviderError(f"model refused the request: {refusal}")
            content = message.get("content")
            raw = _extract_json(content) if isinstance(content, str) else content
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
                attempt=attempt,
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
                attempt=attempt,
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
            attempt=attempt,
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
