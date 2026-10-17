"""Google Gemini embedding provider (default 1536 dims, matches the column).

Uses ``httpx.AsyncClient`` (already a dependency) against
``models.embedContent``. Auth is the ``x-goog-api-key`` header (a free
Google AI Studio key works). ``outputDimensionality`` defaults to 1536
so vectors fit the ``VECTOR(1536)`` column and the pipeline's
``EXPECTED_DIMENSION`` with no migration.

The client is created lazily per call when not supplied so tests can
inject a fake transport. HTTP failures and malformed payloads are
wrapped in ``EmbeddingProviderError`` (the pipeline retries those).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.memory.errors import EmbeddingProviderError


class GeminiEmbeddingProvider:
    """Concrete provider for ``gemini-embedding-001``."""

    name = "gemini"
    model = "gemini-embedding-001"
    dimension = 1536

    API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        if model is not None:
            self.model = model
        if dimension is not None:
            self.dimension = dimension
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None

    def _url(self) -> str:
        return f"{self.API_ROOT}/models/{self.model}:embedContent"

    async def _request(self, text: str) -> list[float]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key
        payload: dict[str, Any] = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self.dimension,
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    self._url(),
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        self._url(),
                        json=payload,
                        headers=headers,
                        timeout=self._timeout_seconds,
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingProviderError(str(exc)) from exc
        try:
            data = response.json()
            return list(data["embedding"]["values"])
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise EmbeddingProviderError(f"malformed embedContent response: {exc}") from exc

    async def embed(self, text: str) -> list[float]:
        return await self._request(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # One call per text: memory volumes are tiny (a few items per
        # run) and this keeps failure/typing semantics identical to
        # ``embed``. Revisit batchEmbedContents if backfills grow.
        return [await self._request(text) for text in texts]

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()


__all__ = ["GeminiEmbeddingProvider"]
