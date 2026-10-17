"""Typed exceptions for the users service."""

from __future__ import annotations


class UserNotFoundError(LookupError):
    """No User exists with the given identifier or email."""

    def __init__(self, identifier: str) -> None:
        super().__init__(identifier)
        self.identifier = identifier

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"User {self.identifier!r} does not exist."


class DuplicateUserEmailError(ValueError):
    """A user with the same email already exists."""

    def __init__(self, email: str) -> None:
        super().__init__(email)
        self.email = email

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"A user with email {self.email!r} already exists."


class GitHubAccountLinkedError(ValueError):
    """A different user already linked this GitHub account."""

    def __init__(self, github_id: int) -> None:
        super().__init__(github_id)
        self.github_id = github_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"GitHub account {self.github_id!r} is already linked to another user."


__all__ = ["DuplicateUserEmailError", "GitHubAccountLinkedError", "UserNotFoundError"]
