"""Unit tests for session JWTs and the credential cipher (no DB)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from app.auth.errors import CredentialDecryptionError, InvalidSessionTokenError
from app.auth.tokens import (
    SESSION_COOKIE,
    TokenCipher,
    create_session_token,
    decode_session_token,
)

_SECRET = "test-jwt-secret"
_USER_ID = uuid.uuid4()


def test_session_token_roundtrip() -> None:
    token = create_session_token(user_id=_USER_ID, secret=_SECRET)
    assert decode_session_token(token=token, secret=_SECRET) == _USER_ID


def test_session_token_rejects_wrong_secret() -> None:
    token = create_session_token(user_id=_USER_ID, secret=_SECRET)
    with pytest.raises(InvalidSessionTokenError):
        decode_session_token(token=token, secret="other-secret")


def test_session_token_rejects_garbage() -> None:
    with pytest.raises(InvalidSessionTokenError):
        decode_session_token(token="not-a-jwt", secret=_SECRET)


def test_session_token_rejects_expired() -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token = create_session_token(
        user_id=_USER_ID, secret=_SECRET, expires_in_seconds=3600, now=past
    )
    with pytest.raises(InvalidSessionTokenError):
        decode_session_token(token=token, secret=_SECRET)


def test_session_token_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        create_session_token(user_id=_USER_ID, secret="")
    with pytest.raises(ValueError, match="secret"):
        decode_session_token(token="x", secret="")


def test_cookie_name_is_stable() -> None:
    assert SESSION_COOKIE == "forge_session"


def test_cipher_roundtrip() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    ciphertext = cipher.encrypt("ghp_secret-token")
    assert ciphertext != "ghp_secret-token"
    assert cipher.decrypt(ciphertext) == "ghp_secret-token"


def test_cipher_rejects_bad_key() -> None:
    with pytest.raises(ValueError, match="Fernet key"):
        TokenCipher("not-a-key")


def test_cipher_rejects_tampered_ciphertext() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    other = TokenCipher(Fernet.generate_key().decode())
    ciphertext = other.encrypt("ghp_secret-token")
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt(ciphertext)
