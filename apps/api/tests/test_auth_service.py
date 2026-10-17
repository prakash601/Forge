"""Service tests for GitHub linking + callback + credential seam (DB)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import (
    InvalidCredentialRefError,
    NoGitHubCredentialError,
    UnverifiedEmailError,
)
from app.auth.github import FakeGitHubOAuthClient, GitHubEmail, GitHubUser
from app.auth.service import handle_oauth_callback
from app.auth.tokens import TokenCipher, decode_session_token
from app.github.credentials import parse_credential_ref, resolve_credential
from app.users.errors import GitHubAccountLinkedError, UserNotFoundError
from app.users.service import (
    create_user,
    get_user_by_github_id,
    link_github_account,
)

_JWT_SECRET = "test-jwt-secret"
_KEY = Fernet.generate_key().decode()


def _cipher() -> TokenCipher:
    return TokenCipher(_KEY)


async def test_link_creates_user_on_first_login(session: AsyncSession) -> None:
    user, created = await link_github_account(
        session, email="new@example.com", github_id=111, encrypted_token="enc"
    )
    assert created is True
    assert user.email == "new@example.com"
    assert user.github_id == 111
    assert user.github_token_encrypted == "enc"


async def test_link_existing_email_user(session: AsyncSession) -> None:
    await create_user(session, email="old@example.com", display_name="Old")
    user, created = await link_github_account(session, email="old@example.com", github_id=222)
    assert created is False
    assert user.github_id == 222


async def test_link_relogin_refreshes_token(session: AsyncSession) -> None:
    await link_github_account(
        session, email="a@example.com", github_id=333, encrypted_token="enc-1"
    )
    user, created = await link_github_account(
        session, email="a@example.com", github_id=333, encrypted_token="enc-2"
    )
    assert created is False
    assert user.github_token_encrypted == "enc-2"


async def test_link_refuses_github_id_linked_elsewhere(session: AsyncSession) -> None:
    await link_github_account(session, email="one@example.com", github_id=444)
    await link_github_account(session, email="two@example.com", github_id=555)
    with pytest.raises(GitHubAccountLinkedError):
        await link_github_account(session, email="two@example.com", github_id=444)


async def test_link_same_github_new_email_updates(session: AsyncSession) -> None:
    user, created = await link_github_account(session, email="old@example.com", github_id=446)
    assert created is True
    user, created = await link_github_account(session, email="new@example.com", github_id=446)
    assert created is False
    assert user.email == "new@example.com"
    assert user.github_id == 446


async def test_get_user_by_github_id(session: AsyncSession) -> None:
    await link_github_account(session, email="g@example.com", github_id=555)
    user = await get_user_by_github_id(session, 555)
    assert user.email == "g@example.com"
    with pytest.raises(UserNotFoundError):
        await get_user_by_github_id(session, 556)


async def test_callback_creates_user_and_session(session: AsyncSession) -> None:
    client = FakeGitHubOAuthClient()
    user, token = await handle_oauth_callback(
        session,
        client=client,
        code="any",
        redirect_uri="http://x/cb",
        cipher=_cipher(),
        jwt_secret=_JWT_SECRET,
        jwt_expiry_seconds=3600,
    )
    assert user.email == "octocat@example.com"
    assert user.github_id == 424242
    assert decode_session_token(token=token, secret=_JWT_SECRET) == user.id
    # Token stored encrypted, never plaintext.
    assert user.github_token_encrypted != "fake-access-token"
    assert _cipher().decrypt(user.github_token_encrypted or "") == "fake-access-token"


async def test_callback_rejects_unverified_email(session: AsyncSession) -> None:
    client = FakeGitHubOAuthClient(
        emails=[GitHubEmail(email="u@x.com", primary=True, verified=False)]
    )
    with pytest.raises(UnverifiedEmailError):
        await handle_oauth_callback(
            session,
            client=client,
            code="any",
            redirect_uri="http://x/cb",
            cipher=_cipher(),
            jwt_secret=_JWT_SECRET,
            jwt_expiry_seconds=3600,
        )


async def test_callback_prefers_user_profile_name(session: AsyncSession) -> None:
    client = FakeGitHubOAuthClient(
        user=GitHubUser(id=777, login="coder", email=None, name="Coder Name")
    )
    user, _ = await handle_oauth_callback(
        session,
        client=client,
        code="any",
        redirect_uri="http://x/cb",
        cipher=_cipher(),
        jwt_secret=_JWT_SECRET,
        jwt_expiry_seconds=3600,
    )
    assert user.display_name == "Coder Name"


async def test_resolve_credential_returns_token(session: AsyncSession) -> None:
    user, _ = await link_github_account(
        session,
        email="c@example.com",
        github_id=888,
        encrypted_token=_cipher().encrypt("live-token"),
    )
    await session.commit()
    assert (
        await resolve_credential(session, ref=f"user:{user.id}", cipher=_cipher()) == "live-token"
    )


async def test_resolve_credential_missing(session: AsyncSession) -> None:
    user = await create_user(session, email="plain@example.com")
    await session.commit()
    with pytest.raises(NoGitHubCredentialError):
        await resolve_credential(session, ref=f"user:{user.id}", cipher=_cipher())


async def test_resolve_credential_rejects_malformed_ref(session: AsyncSession) -> None:
    with pytest.raises(InvalidCredentialRefError):
        await resolve_credential(session, ref="not-a-ref", cipher=_cipher())
    with pytest.raises(InvalidCredentialRefError):
        await resolve_credential(session, ref="user:not-a-uuid", cipher=_cipher())


def test_parse_credential_ref_roundtrip() -> None:
    import uuid as _uuid

    uid = _uuid.uuid4()
    assert parse_credential_ref(f"user:{uid}") == ("user", uid)
    assert parse_credential_ref(f"cred:{uid}") == ("cred", uid)
