"""HTTP integration tests for the auth API (v1, Phase 4 Issue #015)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from httpx import AsyncClient

from app.api.v1.auth import get_oauth_client
from app.auth.github import FakeGitHubOAuthClient, GitHubEmail


@pytest_asyncio.fixture
async def auth_stack(postgres_engine_url: str) -> AsyncIterator[tuple[AsyncClient, Any, str]]:
    """App with auth configured + fake OAuth; yields (client, app, cipher key)."""
    from cryptography.fernet import Fernet
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings, get_settings
    from app.db import session as db_session
    from app.main import create_app
    from tests.conftest import _truncate_all

    get_settings.cache_clear()
    key = Fernet.generate_key().decode()
    settings = Settings(
        database_url=postgres_engine_url,
        environment="test",
        log_level="WARNING",
        github_client_id="test-client-id",
        github_client_secret="test-client-secret",
        jwt_secret="test-jwt-secret",
        credentials_key=key,
    )
    db_session.init_engine(settings)
    try:
        factory = db_session.get_session_factory()
        await _truncate_all(factory.kw["bind"])
        app = create_app(settings)
        app.dependency_overrides[get_oauth_client] = lambda: FakeGitHubOAuthClient()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, app, key
    finally:
        await db_session.dispose_engine()


async def test_login_redirects_to_github(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    response = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 307, response.text
    assert "github.com" in response.headers["location"]


async def test_login_503_when_unconfigured(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


async def test_callback_503_when_unconfigured(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/github/callback?code=x")
    assert response.status_code == 503


async def test_callback_creates_session(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    response = await client.get("/api/v1/auth/github/callback?code=any")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "octocat@example.com"
    assert "github_token_encrypted" not in body
    assert "forge_session=" in response.headers.get("set-cookie", "")


async def test_callback_rejects_bad_code(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    response = await client.get("/api/v1/auth/github/callback?code=bad-code")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OAUTH_FAILED"


async def test_callback_rejects_unverified_email(auth_stack: Any) -> None:
    client, app, _ = auth_stack
    app.dependency_overrides[get_oauth_client] = lambda: FakeGitHubOAuthClient(
        emails=[GitHubEmail(email="u@x.com", primary=True, verified=False)]
    )
    response = await client.get("/api/v1/auth/github/callback?code=any")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OAUTH_FAILED"


async def test_callback_requires_code(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    response = await client.get("/api/v1/auth/github/callback")
    assert response.status_code == 422


async def test_callback_relogin_is_idempotent(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    first = (await client.get("/api/v1/auth/github/callback?code=any")).json()
    second = (await client.get("/api/v1/auth/github/callback?code=any")).json()
    assert first["id"] == second["id"]


async def test_me_with_cookie(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    await client.get("/api/v1/auth/github/callback?code=any")
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "octocat@example.com"


async def test_me_with_bearer(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    await client.get("/api/v1/auth/github/callback?code=any")
    token = client.cookies.get("forge_session")
    assert token
    fresh_headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=client._transport, base_url="http://testserver", headers=fresh_headers
    ) as bare:
        response = await bare.get("/api/v1/auth/me")
    assert response.status_code == 200


async def test_me_401_without_session(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"


async def test_me_401_with_garbage_token(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"


async def test_me_503_when_unconfigured_with_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


async def test_logout_clears_cookie(auth_stack: Any) -> None:
    client, _, _ = auth_stack
    await client.get("/api/v1/auth/github/callback?code=any")
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "forge_session=" in response.headers.get("set-cookie", "")
    assert (await client.get("/api/v1/auth/me")).status_code == 401
