"""HTTP integration tests for the projects API (v1)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _create_user(client: AsyncClient, email: str = "owner@x.com") -> str:
    response = await client.post("/api/v1/users", json={"email": email})
    assert response.status_code == 201
    return response.json()["id"]


async def test_create_project_returns_201(client: AsyncClient) -> None:
    owner = await _create_user(client)
    response = await client.post(
        "/api/v1/projects",
        json={"owner_id": owner, "name": "P1", "description": "first"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "P1"
    assert body["status"] == "ACTIVE"


async def test_create_project_unknown_owner_returns_404(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/projects",
        json={"owner_id": str(uuid.uuid4()), "name": "orphan"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_create_project_rejects_empty_name(client: AsyncClient) -> None:
    owner = await _create_user(client)
    response = await client.post("/api/v1/projects", json={"owner_id": owner, "name": ""})
    assert response.status_code == 422


async def test_get_project_returns_200(client: AsyncClient) -> None:
    owner = await _create_user(client)
    created = (await client.post("/api/v1/projects", json={"owner_id": owner, "name": "P1"})).json()
    response = await client.get(f"/api/v1/projects/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "P1"


async def test_get_project_404_for_unknown_id(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_projects_for_owner(client: AsyncClient) -> None:
    owner_a = await _create_user(client, "a@x.com")
    owner_b = await _create_user(client, "b@x.com")
    for n in ("a1", "a2"):
        await client.post("/api/v1/projects", json={"owner_id": owner_a, "name": n})
    await client.post("/api/v1/projects", json={"owner_id": owner_b, "name": "b1"})
    response = await client.get(f"/api/v1/projects?owner_id={owner_a}")
    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert set(names) == {"a1", "a2"}


async def test_list_projects_unknown_owner_returns_404(
    client: AsyncClient,
) -> None:
    response = await client.get(f"/api/v1/projects?owner_id={uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_projects_requires_owner_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects")
    # Missing required query parameter.
    assert response.status_code == 422
