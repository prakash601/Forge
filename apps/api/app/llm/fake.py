"""Deterministic fake LLM provider for tests and CI.

Returns schema-valid JSON without any network access. Live OpenAI
calls are never made in CI. Two response strategies:

- Per-agent canned payloads (``canned[agent_type]``), validated
  against the caller's schema before return.
- A synthesized fallback built from the schema's field annotations,
  so any ``BaseModel`` schema gets a valid instance.

Scripted failure ``mode``s exercise agent error handling:
``malformed`` (schema violation), ``timeout`` (transport failure),
and ``refusal`` (model refusal).
"""

from __future__ import annotations

import time
import types
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from app.llm.errors import LLMProviderError, SchemaValidationError
from app.llm.observability import emit_llm_call
from app.llm.protocols import LLMResult

FakeMode = Literal["ok", "malformed", "timeout", "refusal"]

_MODES: tuple[str, ...] = ("ok", "malformed", "timeout", "refusal")


def _value_for(field_name: str, annotation: Any) -> Any:
    """Build a placeholder value valid for ``annotation``."""
    if annotation is None or annotation is Any:
        return f"fake-{field_name}"
    if annotation is str:
        return f"fake-{field_name}"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return True
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _synthesize(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation)).value
    origin = get_origin(annotation)
    if origin is Literal:
        args = get_args(annotation)
        return args[0] if args else f"fake-{field_name}"
    if origin in (Union, types.UnionType):
        for arg in get_args(annotation):
            if arg is not type(None):
                return _value_for(field_name, arg)
        return None
    if origin is list:
        (item_type,) = get_args(annotation) or (Any,)
        return [_value_for(field_name, item_type)]
    if origin is dict:
        return {}
    return f"fake-{field_name}"


def _synthesize(schema: type[BaseModel]) -> dict[str, Any]:
    """Build a schema-valid payload from field annotations."""
    return {name: _value_for(name, field.annotation) for name, field in schema.model_fields.items()}


class FakeLLMProvider:
    """Fake ``LLMProvider`` with canned and synthesized responses."""

    name = "fake"

    def __init__(
        self,
        *,
        mode: FakeMode = "ok",
        agent_type: str = "default",
        canned: dict[str, dict[str, Any]] | None = None,
        model: str = "fake-llm",
    ) -> None:
        if mode not in _MODES:
            raise ValueError(f"unknown fake LLM mode: {mode!r}")
        self._mode = mode
        self._agent_type = agent_type
        self._canned = canned or {}
        self._model = model

    async def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        model: str | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        resolved_model = model or self._model
        start = time.perf_counter()

        def _latency_ms() -> int:
            return int((time.perf_counter() - start) * 1000)

        if self._mode == "timeout":
            latency_ms = _latency_ms()
            emit_llm_call(
                provider=self.name,
                model=resolved_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                attempt=1,
                outcome="error",
                error="fake LLM timeout (scripted)",
            )
            raise LLMProviderError("fake LLM timeout (scripted)")
        if self._mode == "refusal":
            latency_ms = _latency_ms()
            emit_llm_call(
                provider=self.name,
                model=resolved_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                attempt=1,
                outcome="error",
                error="fake LLM refusal (scripted)",
            )
            raise LLMProviderError("fake LLM refusal (scripted): model refused to comply")
        if self._mode == "malformed":
            latency_ms = _latency_ms()
            emit_llm_call(
                provider=self.name,
                model=resolved_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                attempt=1,
                outcome="error",
                error="fake LLM returned malformed JSON (scripted)",
            )
            raise SchemaValidationError("fake LLM returned malformed JSON (scripted)")

        payload = {**_synthesize(schema), **self._canned.get(self._agent_type, {})}
        try:
            parsed = schema.model_validate(payload)
        except Exception as exc:
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
            input_tokens=0,
            output_tokens=0,
            latency_ms=latency_ms,
            attempt=1,
            outcome="success",
        )
        return LLMResult(
            parsed=parsed,
            input_tokens=0,
            output_tokens=0,
            latency_ms=latency_ms,
            model=resolved_model,
        )


__all__ = ["FakeLLMProvider", "FakeMode"]
