"""Tests for the error envelope and request-id propagation."""

from __future__ import annotations

from httpx import AsyncClient


async def test_unknown_route_returns_envelope(client: AsyncClient) -> None:
    response = await client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "request_id" in body["error"]


async def test_validation_error_returns_envelope(client: AsyncClient) -> None:
    # Signup validation is open (no session needed): an invalid email
    # exercises the 422 envelope path.
    response = await client.post("/api/v1/users", json={"email": "not-an-email"})
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert "code" in body["error"]


async def test_request_id_is_generated_when_not_provided(
    client: AsyncClient,
) -> None:
    response = await client.get("/health")
    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    assert request_id.startswith("req_")


async def test_request_id_is_echoed_when_provided(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "req_abc123"})
    assert response.headers.get("x-request-id") == "req_abc123"
