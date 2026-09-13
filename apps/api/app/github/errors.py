"""Typed exceptions for backend-only GitHub access (Phase 4, Issue #018).

Messages are always redacted: they never contain tokens, credential
refs resolve server-side, and URLs carry no embedded credentials.
"""

from __future__ import annotations


class GitHubAPIError(RuntimeError):
    """A GitHub REST call failed (message redacted)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubAuthError(GitHubAPIError):
    """The credential was rejected (401/403 bad credentials)."""


class GitHubRateLimitError(GitHubAPIError):
    """Rate-limited (429 or exhausted quota); safe to retry with backoff."""


class InvalidRepoURLError(ValueError):
    """A repo URL is not an acceptable ``https://github.com/owner/repo``."""


class InvalidRepoConfigError(ValueError):
    """Repo link configuration is invalid (branch empty, credential empty)."""


class GitOperationError(RuntimeError):
    """A backend git operation (clone/push) failed (output redacted)."""


__all__ = [
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "GitOperationError",
    "InvalidRepoConfigError",
    "InvalidRepoURLError",
]
