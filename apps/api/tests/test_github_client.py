"""Unit tests for the GitHub REST seam (no DB, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.github.client import (
    FakeGitHubAPIClient,
    PullInfo,
    RealGitHubAPIClient,
)
from app.github.errors import GitHubAPIError, GitHubAuthError, GitHubRateLimitError


def _transport(handler: object) -> httpx.MockTransport:
    assert callable(handler)
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


async def test_fake_lists_and_creates() -> None:
    client = FakeGitHubAPIClient(
        pulls=[PullInfo(number=3, url="https://github.com/o/r/pull/3", state="open")]
    )
    assert len(await client.list_pulls(credential="t", owner_repo="o/r", head="o:b")) == 1
    opened = await client.create_pull(
        credential="t", owner_repo="o/r", head="b", base="main", title="T", body="B"
    )
    assert opened.number == 7
    assert client.create_calls[0]["title"] == "T"


async def test_real_list_and_create_shapes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.params["head"] == "o:feat"
            return httpx.Response(
                200, json=[{"number": 9, "html_url": "https://github.com/o/r/pull/9"}]
            )
        return httpx.Response(
            201, json={"number": 10, "html_url": "https://github.com/o/r/pull/10"}
        )

    client = RealGitHubAPIClient(transport=_transport(handler))
    pulls = await client.list_pulls(credential="t", owner_repo="o/r", head="o:feat")
    assert [(p.number, p.url) for p in pulls] == [(9, "https://github.com/o/r/pull/9")]
    opened = await client.create_pull(
        credential="t", owner_repo="o/r", head="feat", base="main", title="T", body="B"
    )
    assert (opened.number, opened.state) == (10, "open")


async def test_real_auth_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = RealGitHubAPIClient(transport=_transport(handler))
    with pytest.raises(GitHubAuthError):
        await client.create_pull(
            credential="bad", owner_repo="o/r", head="b", base="main", title="T", body="B"
        )


async def test_real_rate_limit_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0"},
        )

    client = RealGitHubAPIClient(transport=_transport(handler))
    with pytest.raises(GitHubRateLimitError):
        await client.list_pulls(credential="t", owner_repo="o/r", head="o:b")


async def test_real_403_other_is_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible"})

    client = RealGitHubAPIClient(transport=_transport(handler))
    with pytest.raises(GitHubAuthError):
        await client.list_pulls(credential="t", owner_repo="o/r", head="o:b")


async def test_real_422_and_500_mapping() -> None:
    client = RealGitHubAPIClient(
        transport=_transport(lambda r: httpx.Response(422, json={"message": "taken"}))
    )
    with pytest.raises(GitHubAPIError) as err:
        await client.create_pull(
            credential="t", owner_repo="o/r", head="b", base="main", title="T", body="B"
        )
    assert err.value.status_code == 422

    old = RealGitHubAPIClient(transport=_transport(lambda r: httpx.Response(500, json={})))
    with pytest.raises(GitHubAPIError):
        await old.list_pulls(credential="t", owner_repo="o/r", head="o:b")


async def test_real_unexpected_shape() -> None:
    client = RealGitHubAPIClient(
        transport=_transport(lambda r: httpx.Response(200, json={"nope": 1}))
    )
    with pytest.raises(GitHubAPIError):
        await client.list_pulls(credential="t", owner_repo="o/r", head="o:b")
