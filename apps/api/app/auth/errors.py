"""Typed exceptions for the auth package (Phase 4, Issue #015)."""


class AuthNotConfiguredError(RuntimeError):
    """Auth was invoked without the required configuration (surfaces as 503)."""

    def __init__(self, missing: str) -> None:
        super().__init__(missing)
        self.missing = missing

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Auth is not configured (missing {self.missing})."


class InvalidSessionTokenError(ValueError):
    """A session JWT is malformed, signed wrongly, or expired."""


class CredentialDecryptionError(ValueError):
    """A stored GitHub credential cannot be decrypted (wrong key or corruption)."""


class NoGitHubCredentialError(LookupError):
    """The user has no stored GitHub credential."""


class InvalidCredentialRefError(ValueError):
    """A credential ref is malformed (expected ``user:<uuid>``)."""


class GitHubOAuthError(RuntimeError):
    """The GitHub OAuth flow failed (exchange, user fetch, or emails fetch)."""


class NoGitHubEmailError(ValueError):
    """GitHub returned no usable email address for the account."""


class UnverifiedEmailError(ValueError):
    """The GitHub primary email is not verified; linking is refused."""

    def __init__(self, email: str) -> None:
        super().__init__(email)
        self.email = email

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"GitHub email {self.email!r} is not verified; linking refused."


__all__ = [
    "AuthNotConfiguredError",
    "CredentialDecryptionError",
    "GitHubOAuthError",
    "InvalidCredentialRefError",
    "InvalidSessionTokenError",
    "NoGitHubCredentialError",
    "NoGitHubEmailError",
    "UnverifiedEmailError",
]
