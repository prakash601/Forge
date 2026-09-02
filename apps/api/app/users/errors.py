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


__all__ = ["DuplicateUserEmailError", "UserNotFoundError"]
