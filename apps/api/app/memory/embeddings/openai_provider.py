"""OpenAI embedding provider (default, 1536 dims).

Uses ``httpx.AsyncClient`` (already a dependency) against the
embeddings endpoint. The client is created lazily per call when not
supplied so tests can inject a fake transport.
"""

from __future__ import annotations

from typing import Any

import httpx


class OpenAIEmbeddingProvider:
    """Concrete provider for ``text-embedding-3-small``."""

    name = "openai"
    model = "text-embedding-3-small"
    dimension = 1536

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        if model is not None:
            self.model = model
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None

    async def _request(self, texts: list[str]) -> list[list[float]]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        if self._client is not None:
            response = await self._client.post(
                "https://api.openai.com/v1/embeddings",
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        else:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
        response.raise_for_status()
        data = response.json()
        return [list(item["embedding"]) for item in data["data"]]

    async def embed(self, text: str) -> list[float]:
        (vec,) = await self._request([text])
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._request(texts)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()


__all__ = ["OpenAIEmbeddingProvider"]
