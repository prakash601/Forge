"""HTTP integration tests for tenancy enforcement (Phase 4, Issue #016)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.auth import get_oauth_client
from app.auth.github import FakeGitHubOAuthClient, GitHubEmail, GitHubUser


@pytest_asyncio.fixture
async def app_pair(postgres_engine_url: str, engine: Any) -> AsyncIterator[Any]:
    """Configured app (fake OAuth) shared by two login identities.

    Takes ``engine`` (unused) to force truncation-before-login ordering
    (see ``authed_client`` in conftest).
    """
    from app.config import Settings, get_settings
    from app.db import session as db_session
    from app.main import create_app
    from tests.conftest import _truncate_all

    _ = engine
    get_settings.cache_clear()
    settings = Settings(
        database_url=postgres_engine_url,
        environment="test",
        log_level="WARNING",
        github_client_id="test-client-id",
        github_client_secret="test-client-secret",
        jwt_secret="test-jwt-secret-for-suite-use-only",
        credentials_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    db_session.init_engine(settings)
    try:
        factory = db_session.get_session_factory()
        await _truncate_all(factory.kw["bind"])
        yield create_app(settings)
    finally:
        await db_session.dispose_engine()


async def login_as(app: Any, *, email: str, github_id: int) -> AsyncClient:
    """Fresh client logged in as the given GitHub identity (fake OAuth)."""
    app.dependency_overrides[get_oauth_client] = lambda: FakeGitHubOAuthClient(
        user=GitHubUser(id=github_id, login=email.split("@")[0], email=email),
        emails=[GitHubEmail(email=email, primary=True, verified=True)],
    )
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    response = await client.get("/api/v1/auth/github/callback?code=any")
    assert response.status_code == 200, response.text
    return client


async def test_project_idor_matrix(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    bob = await login_as(app_pair, email="bob@x.com", github_id=102)
    project = (await alice.post("/api/v1/projects", json={"name": "alice-proj"})).json()
    assert (await alice.get(f"/api/v1/projects/{project['id']}")).status_code == 200
    stranger = await bob.get(f"/api/v1/projects/{project['id']}")
    assert stranger.status_code == 404
    assert stranger.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_project_list_autoscopes(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    bob = await login_as(app_pair, email="bob@x.com", github_id=102)
    await alice.post("/api/v1/projects", json={"name": "a1"})
    assert len((await alice.get("/api/v1/projects")).json()) == 1
    assert (await bob.get("/api/v1/projects")).json() == []
    # A stale ?owner_id= param is ignored, not trusted.
    me_bob = (await bob.get("/api/v1/auth/me")).json()
    assert (await bob.get(f"/api/v1/projects?owner_id={me_bob['id']}")).json() == []


async def test_project_create_derives_owner(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    me = (await alice.get("/api/v1/auth/me")).json()
    body = (await alice.post("/api/v1/projects", json={"name": "p", "owner_id": me["id"]})).json()
    assert body["owner_id"] == me["id"]


async def test_run_idor_matrix(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    bob = await login_as(app_pair, email="bob@x.com", github_id=102)
    project = (await alice.post("/api/v1/projects", json={"name": "p"})).json()
    run = (
        await alice.post("/api/v1/runs", json={"task": "do thing", "project_id": project["id"]})
    ).json()
    assert run["project_id"] == project["id"]
    assert (await alice.get(f"/api/v1/runs/{run['id']}")).status_code == 200
    for path in (
        f"/api/v1/runs/{run['id']}",
        f"/api/v1/runs/{run['id']}/details",
        f"/api/v1/runs/{run['id']}/stream",
    ):
        denied = await bob.get(path)
        assert denied.status_code == 404, path
    denied_event = await bob.post(f"/api/v1/runs/{run['id']}/events", json={"event": "cancel"})
    assert denied_event.status_code == 404
    assert (await bob.get("/api/v1/runs")).json() == {"runs": [], "total": 0}
    mine = (await alice.get("/api/v1/runs")).json()
    assert mine["total"] == 1


async def test_run_create_requires_owned_project(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    bob = await login_as(app_pair, email="bob@x.com", github_id=102)
    project = (await alice.post("/api/v1/projects", json={"name": "p"})).json()
    assert (await alice.post("/api/v1/runs", json={"task": "no project"})).status_code == 422
    assert (
        await alice.post(
            "/api/v1/runs",
            json={"task": "x", "project_id": "00000000-0000-0000-0000-000000000000"},
        )
    ).status_code == 404
    stolen = await bob.post("/api/v1/runs", json={"task": "x", "project_id": project["id"]})
    assert stolen.status_code == 404


async def test_memory_idor_matrix(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    bob = await login_as(app_pair, email="bob@x.com", github_id=102)
    project = (await alice.post("/api/v1/projects", json={"name": "p"})).json()
    payload = {"memory_type": "NOTE", "content": "hello"}
    assert (
        await alice.post(f"/api/v1/projects/{project['id']}/memory", json=payload)
    ).status_code == 201
    assert (
        await bob.post(f"/api/v1/projects/{project['id']}/memory", json=payload)
    ).status_code == 404
    assert (await bob.get(f"/api/v1/projects/{project['id']}/memory")).status_code == 404
    assert (await alice.get(f"/api/v1/projects/{project['id']}/memory")).status_code == 200


async def test_users_self_only(app_pair: Any) -> None:
    alice = await login_as(app_pair, email="alice@x.com", github_id=101)
    bob = await login_as(app_pair, email="bob@x.com", github_id=102)
    me_alice = (await alice.get("/api/v1/auth/me")).json()
    me_bob = (await bob.get("/api/v1/auth/me")).json()
    assert (await alice.get(f"/api/v1/users/{me_alice['id']}")).status_code == 200
    assert (await alice.get(f"/api/v1/users/{me_bob['id']}")).status_code == 404


async def test_signup_stays_open(app_pair: Any) -> None:
    transport = ASGITransport(app=app_pair)
    async with AsyncClient(transport=transport, base_url="http://testserver") as anon:
        response = await anon.post("/api/v1/users", json={"email": "fresh@example.com"})
        assert response.status_code == 201
        assert (await anon.get("/api/v1/runs")).status_code == 401
