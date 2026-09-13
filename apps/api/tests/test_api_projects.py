"""HTTP integration tests for the projects API (v1, Phase 4 Issue #016).

All endpoints require a session; ownership derives from the caller
(cross-user isolation is covered in ``test_api_tenancy.py``).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _me(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    return response.json()


async def test_create_project_returns_201(authed_client: AsyncClient) -> None:
    me = await _me(authed_client)
    response = await authed_client.post(
        "/api/v1/projects", json={"name": "P1", "description": "first"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "P1"
    assert body["status"] == "ACTIVE"
    assert body["owner_id"] == me["id"]


async def test_create_project_ignores_spoofed_owner(
    authed_client: AsyncClient,
) -> None:
    me = await _me(authed_client)
    response = await authed_client.post(
        "/api/v1/projects",
        json={"owner_id": str(uuid.uuid4()), "name": "mine"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["owner_id"] == me["id"]


async def test_create_project_rejects_empty_name(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.post("/api/v1/projects", json={"name": ""})
    assert response.status_code == 422


async def test_create_project_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/projects", json={"name": "P1"})
    assert response.status_code == 401


async def test_get_project_returns_200(authed_client: AsyncClient) -> None:
    created = (await authed_client.post("/api/v1/projects", json={"name": "P1"})).json()
    response = await authed_client.get(f"/api/v1/projects/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "P1"


async def test_get_project_404_for_unknown_id(authed_client: AsyncClient) -> None:
    response = await authed_client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_list_projects_returns_own_newest_first(
    authed_client: AsyncClient,
) -> None:
    for name in ("a1", "a2"):
        response = await authed_client.post("/api/v1/projects", json={"name": name})
        assert response.status_code == 201
    response = await authed_client.get("/api/v1/projects")
    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert names == ["a2", "a1"]


async def test_list_projects_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/projects")).status_code == 401
