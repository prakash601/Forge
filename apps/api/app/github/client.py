"""GitHub REST client seam (Phase 4, Issue #018).

The :class:`GitHubAPIClient` protocol covers the PR slice: reconcile
(``GET /pulls?head=``) and create (``POST /pulls``). Production uses
:class:`RealGitHubAPIClient` (httpx); tests use
:class:`FakeGitHubAPIClient` (scripted, no network).

The credential travels per call (never stored on the client) and only
in the ``Authorization`` header. Error messages are redacted: status
codes and safe summaries only, never tokens or bodies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.github.errors import GitHubAPIError, GitHubAuthError, GitHubRateLimitError

_API = "https://api.github.com"


@dataclass(frozen=True)
class PullInfo:
    """Subset of a pull object we depend on."""

    number: int
    url: str
    state: str


class GitHubAPIClient(Protocol):
    """Seam for the PR slice of the GitHub REST API."""

    async def list_pulls(self, *, credential: str, owner_repo: str, head: str) -> list[PullInfo]:
        """List PRs (any state) for ``owner:branch`` head."""
        ...

    async def create_pull(
        self,
        *,
        credential: str,
        owner_repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PullInfo:
        """Open a PR; 422 (taken/validation) and auth errors typed."""
        ...


def _is_rate_limited(*, status: int, payload: object, headers: object) -> bool:
    if status == 429:
        return True
    if status != 403:
        return False
    remaining: object = None
    if isinstance(headers, dict):
        remaining = headers.get("x-ratelimit-remaining")
    if remaining == "0" or remaining == 0:
        return True
    return isinstance(payload, dict) and "rate limit" in str(payload.get("message", "")).lower()


class RealGitHubAPIClient:
    """Production client over httpx. No network in CI."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._transport = transport

    def _headers(self, credential: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {credential}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        credential: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.request(
                    method,
                    f"{_API}{path}",
                    headers=self._headers(credential),
                    json=json_body,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"GitHub request failed: {method} {path}.") from exc
        status = response.status_code
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if status in (200, 201):
            return payload
        if status == 401:
            raise GitHubAuthError("GitHub rejected the credential.", status_code=status)
        if _is_rate_limited(status=status, payload=payload, headers=dict(response.headers)):
            raise GitHubRateLimitError("GitHub rate limit exceeded.", status_code=status)
        if status == 403:
            raise GitHubAuthError("GitHub refused the credential.", status_code=status)
        if status == 422:
            raise GitHubAPIError("GitHub rejected the pull request.", status_code=status)
        raise GitHubAPIError(f"GitHub request failed with status {status}.", status_code=status)

    @staticmethod
    def _to_pull(payload: object) -> PullInfo:
        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub returned an unexpected pull shape.")
        try:
            return PullInfo(
                number=int(payload["number"]),
                url=str(payload["html_url"]),
                state=str(payload.get("state", "open")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubAPIError("GitHub returned an unexpected pull shape.") from exc

    async def list_pulls(self, *, credential: str, owner_repo: str, head: str) -> list[PullInfo]:
        payload = await self._request(
            "GET",
            f"/repos/{owner_repo}/pulls",
            credential=credential,
            params={"head": head, "state": "all", "per_page": "30"},
        )
        if not isinstance(payload, list):
            raise GitHubAPIError("GitHub pull list returned an unexpected shape.")
        return [self._to_pull(entry) for entry in payload]

    async def create_pull(
        self,
        *,
        credential: str,
        owner_repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PullInfo:
        payload = await self._request(
            "POST",
            f"/repos/{owner_repo}/pulls",
            credential=credential,
            json_body={"head": head, "base": base, "title": title, "body": body},
        )
        return self._to_pull(payload)


@dataclass
class FakeGitHubAPIClient:
    """Scripted client for tests. No network, ever."""

    pulls: list[PullInfo] = field(default_factory=list)
    created: PullInfo | None = None
    create_error: Exception | None = None
    create_error_sequence: list[Exception] = field(default_factory=list)
    list_calls: list[dict[str, str]] = field(default_factory=list)
    create_calls: list[dict[str, str]] = field(default_factory=list)

    async def list_pulls(self, *, credential: str, owner_repo: str, head: str) -> list[PullInfo]:
        self.list_calls.append({"owner_repo": owner_repo, "head": head})
        return list(self.pulls)

    async def create_pull(
        self,
        *,
        credential: str,
        owner_repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PullInfo:
        self.create_calls.append(
            {"owner_repo": owner_repo, "head": head, "base": base, "title": title, "body": body}
        )
        if self.create_error_sequence:
            raise self.create_error_sequence.pop(0)
        if self.create_error is not None:
            raise self.create_error
        if self.created is not None:
            return self.created
        return PullInfo(number=7, url=f"https://github.com/{owner_repo}/pull/7", state="open")


__all__ = [
    "FakeGitHubAPIClient",
    "GitHubAPIClient",
    "PullInfo",
    "RealGitHubAPIClient",
]
