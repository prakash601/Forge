"""Session JWTs and at-rest credential encryption (Phase 4, Issue #015).

Sessions are stateless HS256 JWTs (``sub`` = user id, ``iat``/``exp``).
GitHub OAuth access tokens are stored Fernet-encrypted and are only
readable via the ``resolve_credential`` seam — never serialized into
API responses, logs, or agent contexts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.auth.errors import CredentialDecryptionError, InvalidSessionTokenError

#: Name of the session cookie (and the Bearer scheme carries the same JWT).
SESSION_COOKIE = "forge_session"

_ALGORITHM = "HS256"


def create_session_token(
    *,
    user_id: uuid.UUID,
    secret: str,
    expires_in_seconds: int = 86_400,
    now: datetime | None = None,
) -> str:
    """Mint a session JWT for ``user_id``."""
    if not secret:
        raise ValueError("secret must be a non-empty string")
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_session_token(*, token: str, secret: str) -> uuid.UUID:
    """Verify a session JWT and return the user id.

    Raises :class:`InvalidSessionTokenError` on any failure, including
    expiry. Callers map this to 401.
    """
    if not secret:
        raise ValueError("secret must be a non-empty string")
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        return uuid.UUID(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise InvalidSessionTokenError("Invalid or expired session token.") from exc


class TokenCipher:
    """Fernet envelope for GitHub OAuth tokens at rest."""

    def __init__(self, key: str | bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "credentials_key must be a valid Fernet key (generate with Fernet.generate_key)."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise CredentialDecryptionError(
                "Stored GitHub credential cannot be decrypted."
            ) from exc


__all__ = [
    "SESSION_COOKIE",
    "TokenCipher",
    "create_session_token",
    "decode_session_token",
]
