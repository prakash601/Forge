"""HTTP integration tests for repo-connect + repo-backed runs (Phase 4, Issue #018)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import ensure_project

_REPO = "https://github.com/octocat/hello"


async def _connect(
    client: AsyncClient, project_id: str, *, credential: str = "ghp_test-pat"
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project_id}/repo",
        json={
            "repo_url": _REPO,
            "default_branch": "main",
            "credential": credential,
        },
    )


async def test_repo_connect_and_read(authed_client: AsyncClient) -> None:
    project = await ensure_project(authed_client)
    response = await _connect(authed_client, project["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "repo_url": _REPO,
        "default_branch": "main",
        "credential_set": True,
    }
    assert "credential" not in body
    assert "ghp_test-pat" not in response.text
    read = await authed_client.get(f"/api/v1/projects/{project['id']}/repo")
    assert read.status_code == 200
    assert read.json() == body


async def test_repo_connect_rejects(authed_client: AsyncClient) -> None:
    project = await ensure_project(authed_client)
    bad_url = await authed_client.post(
        f"/api/v1/projects/{project['id']}/repo",
        json={"repo_url": "git@github.com:o/r.git", "credential": "x"},
    )
    assert bad_url.status_code == 422
    empty_branch = await authed_client.post(
        f"/api/v1/projects/{project['id']}/repo",
        json={"repo_url": _REPO, "default_branch": " ", "credential": "x"},
    )
    assert empty_branch.status_code == 422
    empty_cred = await authed_client.post(
        f"/api/v1/projects/{project['id']}/repo",
        json={"repo_url": _REPO, "credential": " "},
    )
    assert empty_cred.status_code == 422


async def test_repo_requires_owner(authed_client: AsyncClient) -> None:
    import uuid as _uuid

    project = await ensure_project(authed_client)
    assert (
        await authed_client.get(f"/api/v1/projects/{project['id']}/repo")
    ).status_code == 404  # never connected
    assert (await authed_client.get(f"/api/v1/projects/{_uuid.uuid4()}/repo")).status_code == 404


async def test_repo_anon_denied(client: AsyncClient) -> None:
    import uuid as _uuid

    assert (
        await client.post(
            f"/api/v1/projects/{_uuid.uuid4()}/repo",
            json={"repo_url": _REPO, "credential": "x"},
        )
    ).status_code == 401
    assert (await client.get(f"/api/v1/projects/{_uuid.uuid4()}/repo")).status_code == 401


async def test_run_create_clones_repo(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.v1.runs as runs_api

    project = await ensure_project(authed_client)
    assert (await _connect(authed_client, project["id"])).status_code == 200

    async def fake_clone(**kwargs: Any) -> str:
        assert kwargs["branch"].startswith("forge/")
        assert kwargs["default_branch"] == "main"
        return "deadbeef" * 5

    monkeypatch.setattr(runs_api, "clone_repo", fake_clone)
    created = await authed_client.post(
        "/api/v1/runs", json={"task": "Do thing", "project_id": project["id"]}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["branch"].startswith("forge/do-thing-")
    assert body["base_commit"] == "deadbeef" * 5


async def test_run_create_clone_auth_failure(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.v1.runs as runs_api
    from app.github.errors import GitOperationError

    project = await ensure_project(authed_client)
    assert (await _connect(authed_client, project["id"])).status_code == 200

    async def bad_clone(**kwargs: Any) -> str:
        raise GitOperationError("clone failed: Authentication failed")

    monkeypatch.setattr(runs_api, "clone_repo", bad_clone)
    response = await authed_client.post(
        "/api/v1/runs", json={"task": "Do thing", "project_id": project["id"]}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "GITHUB_AUTH_ERROR"
    assert (await authed_client.get("/api/v1/runs")).json()["total"] == 0


async def test_run_create_clone_upstream_failure_is_502(authed_client: AsyncClient) -> None:
    project = await ensure_project(authed_client)
    response = await authed_client.post(
        f"/api/v1/projects/{project['id']}/repo",
        json={
            "repo_url": "https://github.com/octocat/this-repo-does-not-exist-xyz",
            "credential": "ghp_test-pat",
        },
    )
    assert response.status_code == 200, response.text
    created = await authed_client.post(
        "/api/v1/runs", json={"task": "Do thing", "project_id": project["id"]}
    )
    assert created.status_code == 502
    assert created.json()["error"]["code"] == "GITHUB_UPSTREAM_ERROR"
