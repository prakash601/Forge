"""Unit tests for the embedding provider seam (no DB).

Seam 1: EmbeddingProvider protocol + Fake (CI) + OpenAI + registry.
"""

from __future__ import annotations


async def test_fake_provider_returns_deterministic_1536_vector() -> None:
    from app.memory.embeddings.fake import FakeEmbeddingProvider

    provider = FakeEmbeddingProvider()
    vec = await provider.embed("hello")
    assert len(vec) == 1536
    vec2 = await provider.embed("hello")
    assert vec == vec2
    batch = await provider.embed_batch(["a", "b"])
    assert len(batch) == 2
    assert all(len(v) == 1536 for v in batch)


async def test_registry_returns_fake_for_fake_config() -> None:
    from app.memory.embeddings.registry import get_provider

    provider = get_provider(provider_name="fake")
    vec = await provider.embed("x")
    assert len(vec) == 1536


async def test_registry_rejects_unknown_provider() -> None:
    import pytest

    from app.memory.embeddings.registry import get_provider

    with pytest.raises(ValueError, match="unknown"):
        get_provider(provider_name="nope")


def test_openai_provider_exposes_expected_dimension() -> None:
    from app.memory.embeddings.openai_provider import OpenAIEmbeddingProvider

    assert OpenAIEmbeddingProvider.dimension == 1536
    assert OpenAIEmbeddingProvider.model == "text-embedding-3-small"


def _gemini_client(payload: dict, *, status: int = 200):  # type: ignore[no-untyped-def]
    import httpx

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def _gemini_payload(values: list[float]) -> dict:
    return {"embedding": {"values": values}}


async def test_gemini_provider_request_shape_and_parse() -> None:
    import json

    from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider

    client, seen = _gemini_client(_gemini_payload([0.1, 0.2, 0.3]))
    provider = GeminiEmbeddingProvider(api_key="g-key", client=client, dimension=3)
    vec = await provider.embed("hello")
    assert vec == [0.1, 0.2, 0.3]
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
    )
    assert req.headers["x-goog-api-key"] == "g-key"
    body = json.loads(req.content.decode())
    assert body["model"] == "models/gemini-embedding-001"
    assert body["content"] == {"parts": [{"text": "hello"}]}
    assert body["outputDimensionality"] == 3


async def test_gemini_provider_defaults_to_1536_dims() -> None:
    from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider

    provider = GeminiEmbeddingProvider()
    assert provider.name == "gemini"
    assert provider.model == "gemini-embedding-001"
    assert provider.dimension == 1536
    client, _ = _gemini_client(_gemini_payload([0.0] * 1536))
    provider = GeminiEmbeddingProvider(client=client)
    assert len(await provider.embed("x")) == 1536


async def test_gemini_provider_batch_embeds_each_text() -> None:
    from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider

    client, seen = _gemini_client(_gemini_payload([1.0]))
    provider = GeminiEmbeddingProvider(client=client, dimension=1)
    batch = await provider.embed_batch(["a", "b", "c"])
    assert batch == [[1.0], [1.0], [1.0]]
    assert len(seen) == 3


async def test_gemini_provider_http_error_maps_to_provider_error() -> None:
    import pytest

    from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider
    from app.memory.errors import EmbeddingProviderError

    client, _ = _gemini_client({"error": {"message": "bad key"}}, status=400)
    provider = GeminiEmbeddingProvider(api_key="bad", client=client)
    with pytest.raises(EmbeddingProviderError):
        await provider.embed("x")


async def test_gemini_provider_malformed_response_maps_to_provider_error() -> None:
    import pytest

    from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider
    from app.memory.errors import EmbeddingProviderError

    client, _ = _gemini_client({"unexpected": "shape"})
    provider = GeminiEmbeddingProvider(client=client)
    with pytest.raises(EmbeddingProviderError):
        await provider.embed("x")


async def test_registry_returns_gemini_with_column_matching_dims() -> None:
    from app.memory.embeddings.gemini_provider import GeminiEmbeddingProvider
    from app.memory.embeddings.registry import get_provider
    from app.memory.pipeline import EXPECTED_DIMENSION

    # Settings always passes its OpenAI default model down; gemini must
    # resolve to its own model and to the column dimension instead.
    provider = get_provider(provider_name="gemini", model="text-embedding-3-small")
    assert isinstance(provider, GeminiEmbeddingProvider)
    assert provider.name == "gemini"
    assert provider.model == "gemini-embedding-001"
    assert provider.dimension == EXPECTED_DIMENSION == 1536

    explicit = get_provider(provider_name="gemini", model="gemini-embedding-001", dimension=768)
    assert isinstance(explicit, GeminiEmbeddingProvider)
    assert explicit.model == "gemini-embedding-001"
    assert explicit.dimension == 768


def test_embedding_settings_gemini_key_aliases(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.config import Settings

    for var in ("GEMINI_API_KEY", "FORGE_GEMINI_API_KEY", "FORGE_EMBEDDING_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FORGE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FORGE_LLM_API_KEY", raising=False)
    assert Settings().openai_api_key is None

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    assert Settings().openai_api_key == "gemini-key"
