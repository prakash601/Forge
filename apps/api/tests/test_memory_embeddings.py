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
