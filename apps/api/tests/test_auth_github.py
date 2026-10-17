"""Unit tests for the GitHub OAuth seam (no DB, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.auth.errors import GitHubOAuthError, NoGitHubEmailError, UnverifiedEmailError
from app.auth.github import (
    FakeGitHubOAuthClient,
    GitHubEmail,
    GitHubUser,
    RealGitHubOAuthClient,
    select_primary_verified_email,
)


def test_select_primary_verified_email() -> None:
    emails = [
        GitHubEmail(email="old@example.com", primary=False, verified=True),
        GitHubEmail(email="new@example.com", primary=True, verified=True),
    ]
    assert select_primary_verified_email(emails) == "new@example.com"


def test_select_email_falls_back_without_primary() -> None:
    assert (
        select_primary_verified_email([GitHubEmail(email="solo@example.com", verified=True)])
        == "solo@example.com"
    )


def test_select_email_rejects_unverified_primary() -> None:
    with pytest.raises(UnverifiedEmailError):
        select_primary_verified_email(
            [GitHubEmail(email="x@example.com", primary=True, verified=False)]
        )


def test_select_email_rejects_unverified_primary_despite_verified_secondary() -> None:
    with pytest.raises(UnverifiedEmailError):
        select_primary_verified_email(
            [
                GitHubEmail(email="primary@example.com", primary=True, verified=False),
                GitHubEmail(email="other@example.com", primary=False, verified=True),
            ]
        )


def test_select_email_rejects_all_unverified_without_primary() -> None:
    with pytest.raises(NoGitHubEmailError):
        select_primary_verified_email([GitHubEmail(email="x@example.com", verified=False)])


def test_select_email_rejects_empty() -> None:
    with pytest.raises(NoGitHubEmailError):
        select_primary_verified_email([])


async def test_fake_client_login_url_uses_login_scopes() -> None:
    client = FakeGitHubOAuthClient()
    url = client.login_url(redirect_uri="http://x/cb", state="s")
    assert "redirect_uri" in url and "state" in url


def test_real_client_login_url_requests_minimal_scopes() -> None:
    client = RealGitHubOAuthClient(client_id="id", client_secret="shh")
    url = client.login_url(redirect_uri="http://x/cb", state="s")
    assert "client_id=id" in url
    assert "scope=read%3Auser+user%3Aemail" in url or "scope=read:user user:email" in url
    assert "repo" not in url


async def test_fake_client_exchange_and_user() -> None:
    client = FakeGitHubOAuthClient()
    token = await client.exchange_code(code="any", redirect_uri="http://x/cb")
    assert token == "fake-access-token"
    user = await client.get_user(access_token=token)
    assert isinstance(user, GitHubUser) and user.id == 424242
    assert (await client.list_emails(access_token=token))[0].verified


async def test_fake_client_bad_code() -> None:
    client = FakeGitHubOAuthClient()
    with pytest.raises(GitHubOAuthError):
        await client.exchange_code(code="bad-code", redirect_uri="http://x/cb")


def _transport(handler: object) -> httpx.MockTransport:
    assert callable(handler)
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


async def test_real_client_exchange_user_emails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "tok123", "scope": "x"})
        if request.url.path == "/user/emails":
            return httpx.Response(
                200,
                json=[{"email": "a@x.com", "primary": True, "verified": True}],
            )
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 7, "login": "octo"})
        raise AssertionError(f"unexpected {request.url}")

    client = RealGitHubOAuthClient(
        client_id="id", client_secret="shh", transport=_transport(handler)
    )
    assert await client.exchange_code(code="c", redirect_uri="http://x/cb") == "tok123"
    user = await client.get_user(access_token="tok123")
    assert (user.id, user.login) == (7, "octo")
    emails = await client.list_emails(access_token="tok123")
    assert select_primary_verified_email(emails) == "a@x.com"


async def test_real_client_exchange_error_surfaces() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code"})

    client = RealGitHubOAuthClient(
        client_id="id", client_secret="shh", transport=_transport(handler)
    )
    with pytest.raises(GitHubOAuthError):
        await client.exchange_code(code="c", redirect_uri="http://x/cb")


async def test_real_client_http_error_surfaces() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    client = RealGitHubOAuthClient(
        client_id="id", client_secret="shh", transport=_transport(handler)
    )
    with pytest.raises(GitHubOAuthError):
        await client.get_user(access_token="tok123")
