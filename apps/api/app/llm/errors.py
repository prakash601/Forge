"""Typed exceptions for the LLM provider seam."""

from __future__ import annotations


class LLMProviderError(RuntimeError):
    """The LLM provider call failed (network, auth, rate limit, refusal)."""


class SchemaValidationError(LLMProviderError):
    """The provider output was not valid JSON or violated the schema."""


__all__ = ["LLMProviderError", "SchemaValidationError"]
