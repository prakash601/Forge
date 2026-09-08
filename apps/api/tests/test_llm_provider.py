"""Unit tests for the LLM provider seam (no DB, no live calls).

Seam: LLMProvider protocol + Fake (CI) + OpenAI + registry.
Live OpenAI calls are never made in CI — the OpenAI provider is
exercised only through an httpx.MockTransport.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel


class PlanStep(BaseModel):
    title: str
    done: bool = False


class PlanOutput(BaseModel):
    steps: list[PlanStep]
    summary: str


class EchoOutput(BaseModel):
    text: str
    count: int


def _result_shape(result: Any) -> None:
    """Contract-shape assertion shared with AGENT_CONTRACTS §16 readers."""
    assert hasattr(result, "parsed")
    assert hasattr(result, "input_tokens")
    assert hasattr(result, "output_tokens")
    assert hasattr(result, "latency_ms")
    assert hasattr(result, "model")
    assert isinstance(result.input_tokens, int)
    assert isinstance(result.output_tokens, int)
    assert isinstance(result.latency_ms, int)
    assert isinstance(result.model, str)


async def test_fake_returns_schema_valid_result() -> None:
    from app.llm.fake import FakeLLMProvider

    provider = FakeLLMProvider()
    result = await provider.complete_json("draft a plan", PlanOutput)
    _result_shape(result)
    assert isinstance(result.parsed, PlanOutput)
    assert isinstance(result.parsed.summary, str)


async def test_fake_canned_json_differs_per_agent_type() -> None:
    from app.llm.fake import FakeLLMProvider

    canned = {
        "planner": {"steps": [{"title": "a", "done": False}], "summary": "plan!"},
        "archaeologist": {"steps": [{"title": "b", "done": True}], "summary": "dig!"},
    }
    planner = FakeLLMProvider(agent_type="planner", canned=canned)
    archaeologist = FakeLLMProvider(agent_type="archaeologist", canned=canned)

    plan = await planner.complete_json("prompt", PlanOutput)
    dig = await archaeologist.complete_json("prompt", PlanOutput)
    assert isinstance(plan.parsed, PlanOutput)
    assert isinstance(dig.parsed, PlanOutput)
    assert plan.parsed.summary == "plan!"
    assert dig.parsed.summary == "dig!"


async def test_fake_malformed_mode_raises_schema_validation_error() -> None:
    from app.llm.errors import SchemaValidationError
    from app.llm.fake import FakeLLMProvider

    provider = FakeLLMProvider(mode="malformed")
    with pytest.raises(SchemaValidationError):
        await provider.complete_json("prompt", PlanOutput)


async def test_fake_timeout_mode_raises_provider_error() -> None:
    from app.llm.errors import LLMProviderError
    from app.llm.fake import FakeLLMProvider

    provider = FakeLLMProvider(mode="timeout")
    with pytest.raises(LLMProviderError):
        await provider.complete_json("prompt", PlanOutput)


async def test_fake_refusal_mode_raises_provider_error() -> None:
    from app.llm.errors import LLMProviderError
    from app.llm.fake import FakeLLMProvider

    provider = FakeLLMProvider(mode="refusal")
    with pytest.raises(LLMProviderError, match=r"[Rr]efus"):
        await provider.complete_json("prompt", PlanOutput)


async def test_registry_returns_fake_by_default() -> None:
    from app.llm.registry import get_llm_provider

    provider = get_llm_provider()
    assert provider.name == "fake"
    result = await provider.complete_json("prompt", EchoOutput)
    assert isinstance(result.parsed, EchoOutput)


async def test_registry_returns_openai_for_openai_config() -> None:
    from app.llm.registry import get_llm_provider

    provider = get_llm_provider(provider_name="openai", api_key="test-key")
    assert provider.name == "openai"


async def test_registry_rejects_unknown_provider() -> None:
    from app.llm.registry import get_llm_provider

    with pytest.raises(ValueError, match="unknown"):
        get_llm_provider(provider_name="anthropic")


def test_openai_provider_default_model_is_gpt_4o_mini() -> None:
    from app.llm.openai_provider import OpenAILLMProvider

    assert OpenAILLMProvider.model == "gpt-4o-mini"


def _mock_openai_client(payload: dict[str, Any], *, status: int = 200):  # type: ignore[no-untyped-def]
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _chat_payload(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-4o-mini",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def test_openai_provider_parses_strict_json_response() -> None:
    import json

    from app.llm.openai_provider import OpenAILLMProvider

    payload = _chat_payload(json.dumps({"text": "hi", "count": 3}))
    provider = OpenAILLMProvider(api_key="test-key", client=_mock_openai_client(payload))
    result = await provider.complete_json("prompt", EchoOutput)
    _result_shape(result)
    assert isinstance(result.parsed, EchoOutput)
    assert result.parsed.text == "hi"
    assert result.parsed.count == 3
    assert result.input_tokens == 10
    assert result.output_tokens == 5


async def test_openai_provider_http_error_maps_to_provider_error() -> None:
    from app.llm.errors import LLMProviderError
    from app.llm.openai_provider import OpenAILLMProvider

    client = _mock_openai_client({"error": {"message": "boom"}}, status=500)
    provider = OpenAILLMProvider(api_key="test-key", client=client)
    with pytest.raises(LLMProviderError):
        await provider.complete_json("prompt", EchoOutput)


async def test_openai_provider_schema_violation_maps_to_schema_error() -> None:
    from app.llm.errors import SchemaValidationError
    from app.llm.openai_provider import OpenAILLMProvider

    payload = _chat_payload('{"text": 123, "count": "not-an-int"}')
    provider = OpenAILLMProvider(api_key="test-key", client=_mock_openai_client(payload))
    with pytest.raises(SchemaValidationError):
        await provider.complete_json("prompt", EchoOutput)


async def test_openai_provider_garbage_content_maps_to_schema_error() -> None:
    from app.llm.errors import SchemaValidationError
    from app.llm.openai_provider import OpenAILLMProvider

    payload = _chat_payload("this is not json {{{")
    provider = OpenAILLMProvider(api_key="test-key", client=_mock_openai_client(payload))
    with pytest.raises(SchemaValidationError):
        await provider.complete_json("prompt", EchoOutput)


def test_llm_settings_defaults_and_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    defaults = Settings()
    assert defaults.llm_provider == "fake"
    assert defaults.llm_model == "gpt-4o-mini"
    assert defaults.llm_timeout_seconds == 30.0
    assert defaults.llm_max_output_tokens > 0
    assert defaults.openai_api_key is None

    monkeypatch.setenv("FORGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("FORGE_LLM_MODEL", "gpt-4o")
    monkeypatch.setenv("FORGE_LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("FORGE_LLM_MAX_OUTPUT_TOKENS", "512")
    monkeypatch.setenv("FORGE_OPENAI_API_KEY", "forge-prefixed-key")
    prefixed = Settings()
    assert prefixed.llm_provider == "openai"
    assert prefixed.llm_model == "gpt-4o"
    assert prefixed.llm_timeout_seconds == 12.5
    assert prefixed.llm_max_output_tokens == 512
    assert prefixed.openai_api_key == "forge-prefixed-key"

    monkeypatch.delenv("FORGE_OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "plain-key")
    plain = Settings()
    assert plain.openai_api_key == "plain-key"


async def test_llm_calls_emit_forge_counters() -> None:
    from app.llm import metrics
    from app.llm.errors import LLMProviderError
    from app.llm.fake import FakeLLMProvider

    metrics.reset_counters()
    provider = FakeLLMProvider()
    await provider.complete_json("prompt", EchoOutput)
    snapshot = metrics.get_counters()
    assert snapshot.get(("forge_llm_calls_total", "fake", "fake-llm", "success"), 0) == 1

    failing = FakeLLMProvider(mode="timeout")
    with pytest.raises(LLMProviderError):
        await failing.complete_json("prompt", EchoOutput)
    snapshot = metrics.get_counters()
    assert snapshot.get(("forge_llm_calls_total", "fake", "fake-llm", "error"), 0) == 1
