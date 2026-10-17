"""Embedding providers for project memory."""

from __future__ import annotations

from app.memory.embeddings.fake import FakeEmbeddingProvider
from app.memory.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.memory.embeddings.protocols import EmbeddingProvider
from app.memory.embeddings.registry import get_provider

__all__ = [
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_provider",
]
