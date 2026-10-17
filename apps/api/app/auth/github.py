"""GitHub OAuth client seam (Phase 4, Issue #015).

The :class:`GitHubOAuthClient` protocol is the seam: production uses
:class:`RealGitHubOAuthClient` (httpx against github.com), tests use
:class:`FakeGitHubOAuthClient` (canned user + emails, no network).

Security notes
--------------
* Access tokens travel only in ``Authorization`` headers and in-memory
  return values. They are never logged, never put in URLs, and never
  persisted except Fernet-encrypted via :class:`TokenCipher`.
* :func:`select_primary_verified_email` enforces decision #56: linking
  requires the GitHub ``verified=true`` primary email.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.auth.errors import GitHubOAuthError, NoGitHubEmailError, UnverifiedEmailError

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_API = "https://api.github.com"
_SCOPES = "read:user user:email"


@dataclass(frozen=True)
class GitHubUser:
    """Subset of ``GET /user`` we depend on."""

    id: int
    login: str
    email: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class GitHubEmail:
    """One entry of ``GET /user/emails``."""

    email: str
    primary: bool = False
    verified: bool = False


class GitHubOAuthClient(Protocol):
    """Seam for the GitHub OAuth dance."""

    def login_url(self, *, redirect_uri: str, state: str) -> str:
        """Build the github.com authorize URL (login scopes only)."""
        ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        """Exchange an authorize ``code`` for an access token."""
        ...

    async def get_user(self, *, access_token: str) -> GitHubUser:
        """Fetch the authenticated GitHub user."""
        ...

    async def list_emails(self, *, access_token: str) -> list[GitHubEmail]:
        """List the account's email addresses."""
        ...


def select_primary_verified_email(emails: list[GitHubEmail]) -> str:
    """Return the verified primary email.

    The account's flagged primary must be verified — an unverified
    primary is rejected (never matched) even when another verified
    address exists. With no flagged primary, any verified address
    proves ownership. Raises :class:`NoGitHubEmailError` when nothing
    is usable and :class:`UnverifiedEmailError` on an unverified
    primary (linking refused per #56).
    """
    if not emails:
        raise NoGitHubEmailError("GitHub returned no email addresses.")
    primary = next((e for e in emails if e.primary), None)
    if primary is not None:
        if not primary.verified:
            raise UnverifiedEmailError(primary.email)
        return primary.email
    verified = next((e for e in emails if e.verified), None)
    if verified is None:
        raise NoGitHubEmailError("GitHub returned no verified email addresses.")
    return verified.email


class RealGitHubOAuthClient:
    """Production client over httpx. No network in CI — tests use the fake."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_seconds
        self._transport = transport

    def login_url(self, *, redirect_uri: str, state: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": _SCOPES,
                "state": state,
            }
        )
        return f"{_GITHUB_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    _GITHUB_TOKEN_URL,
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GitHubOAuthError("GitHub code exchange failed.") from exc
        if payload.get("error"):
            raise GitHubOAuthError(f"GitHub code exchange failed: {payload.get('error')}.")
        token = payload.get("access_token")
        if not token:
            raise GitHubOAuthError("GitHub code exchange returned no access token.")
        return str(token)

    async def _api_get(self, path: str, *, access_token: str) -> object:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{_GITHUB_API}{path}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise GitHubOAuthError(f"GitHub API request failed: {path}.") from exc

    async def get_user(self, *, access_token: str) -> GitHubUser:
        payload = await self._api_get("/user", access_token=access_token)
        if not isinstance(payload, dict) or "id" not in payload:
            raise GitHubOAuthError("GitHub /user returned an unexpected shape.")
        return GitHubUser(
            id=int(payload["id"]),
            login=str(payload.get("login", "")),
            email=payload.get("email"),
            name=payload.get("name"),
        )

    async def list_emails(self, *, access_token: str) -> list[GitHubEmail]:
        payload = await self._api_get("/user/emails", access_token=access_token)
        if not isinstance(payload, list):
            raise GitHubOAuthError("GitHub /user/emails returned an unexpected shape.")
        emails: list[GitHubEmail] = []
        for entry in payload:
            if not isinstance(entry, dict) or "email" not in entry:
                raise GitHubOAuthError("GitHub /user/emails returned an unexpected shape.")
            emails.append(
                GitHubEmail(
                    email=str(entry["email"]),
                    primary=bool(entry.get("primary", False)),
                    verified=bool(entry.get("verified", False)),
                )
            )
        return emails


@dataclass
class FakeGitHubOAuthClient:
    """Canned OAuth client for tests. No network, ever."""

    user: GitHubUser = field(
        default_factory=lambda: GitHubUser(
            id=424242, login="octocat", email="octocat@example.com", name="Octocat"
        )
    )
    emails: list[GitHubEmail] = field(
        default_factory=lambda: [
            GitHubEmail(email="octocat@example.com", primary=True, verified=True)
        ]
    )
    access_token: str = "fake-access-token"

    def login_url(self, *, redirect_uri: str, state: str) -> str:
        query = urlencode({"redirect_uri": redirect_uri, "state": state})
        return f"https://github.com/fake/authorize?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        if code == "bad-code":
            raise GitHubOAuthError("Fake exchange failure.")
        return self.access_token

    async def get_user(self, *, access_token: str) -> GitHubUser:
        return self.user

    async def list_emails(self, *, access_token: str) -> list[GitHubEmail]:
        return list(self.emails)


__all__ = [
    "FakeGitHubOAuthClient",
    "GitHubEmail",
    "GitHubOAuthClient",
    "GitHubUser",
    "RealGitHubOAuthClient",
    "select_primary_verified_email",
]
