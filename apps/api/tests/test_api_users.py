"""HTTP integration tests for the users API (v1)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_create_user_returns_201(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users", json={"email": "alice@example.com", "display_name": "Alice"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["display_name"] == "Alice"
    assert "id" in body


async def test_create_user_normalizes_email(client: AsyncClient) -> None:
    response = await client.post("/api/v1/users", json={"email": "  Bob@Example.COM  "})
    # Pydantic's EmailStr trims whitespace and lowercases the domain;
    # the service layer additionally lowercases the local part.
    assert response.status_code == 201
    assert response.json()["email"] == "bob@example.com"


async def test_create_user_rejects_invalid_email(client: AsyncClient) -> None:
    response = await client.post("/api/v1/users", json={"email": "not-an-email"})
    assert response.status_code == 422


async def test_create_user_duplicate_email_returns_409(
    client: AsyncClient,
) -> None:
    first = await client.post("/api/v1/users", json={"email": "dup@x.com"})
    assert first.status_code == 201
    second = await client.post("/api/v1/users", json={"email": "DUP@x.com"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


async def test_get_user_returns_200(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/users", json={"email": "x@y.com"})).json()
    response = await client.get(f"/api/v1/users/{created['id']}")
    assert response.status_code == 200
    assert response.json()["email"] == "x@y.com"


async def test_get_user_404_for_unknown_id(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/users/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_get_user_422_for_malformed_uuid(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/not-a-uuid")
    assert response.status_code == 422
