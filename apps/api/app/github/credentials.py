"""GitHub credential seam (Phase 4, Issues #015/#018).

Refs are opaque strings:

* ``user:<uuid>`` — the user's OAuth token from login (#015).
* ``cred:<uuid>`` — a stored PAT row from repo-connect (#018).

:func:`resolve_credential` decrypts either form for one backend-only
operation. It must only be called from inside :mod:`app.github`
(clone/push/PR creation) — enforced by convention and code review;
Python offers no cheaper runtime boundary. Never pass its return
value to agent code, the sandbox, prompts, logs, or API responses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import InvalidCredentialRefError, NoGitHubCredentialError
from app.auth.tokens import TokenCipher
from app.github.models import GitHubCredential
from app.users.service import get_user


def parse_credential_ref(ref: str) -> tuple[str, uuid.UUID]:
    """Parse an opaque ref into ``(scheme, id)``.

    Accepted schemes are ``user`` and ``cred``. Raises
    :class:`InvalidCredentialRefError` otherwise.
    """
    scheme, _, value = ref.partition(":")
    if scheme not in ("user", "cred") or not value:
        raise InvalidCredentialRefError(f"Malformed credential ref: {ref!r}.")
    try:
        return scheme, uuid.UUID(value)
    except ValueError as exc:
        raise InvalidCredentialRefError(f"Malformed credential ref: {ref!r}.") from exc


async def store_credential(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_encrypted: str,
) -> str:
    """Persist an encrypted PAT; return its opaque ``cred:<id>`` ref."""
    credential = GitHubCredential(
        user_id=user_id,
        token_encrypted=token_encrypted,
        created_at=datetime.now(UTC),
    )
    session.add(credential)
    await session.flush()
    return f"cred:{credential.id}"


async def resolve_credential(
    session: AsyncSession,
    *,
    ref: str,
    cipher: TokenCipher,
) -> str:
    """Return the decrypted GitHub token behind ``ref`` (backend-only).

    Raises :class:`InvalidCredentialRefError` on malformed refs and
    :class:`NoGitHubCredentialError` when nothing is stored behind it.
    The caller must use the token in-memory and never persist or
    expose it.
    """
    scheme, credential_id = parse_credential_ref(ref)
    encrypted: str | None = None
    if scheme == "user":
        user = await get_user(session, credential_id)
        encrypted = user.github_token_encrypted
    else:
        row = await session.get(GitHubCredential, credential_id)
        if row is not None:
            encrypted = row.token_encrypted
    if not encrypted:
        raise NoGitHubCredentialError("No GitHub credential stored for this ref.")
    return cipher.decrypt(encrypted)


__all__ = [
    "NoGitHubCredentialError",
    "parse_credential_ref",
    "resolve_credential",
    "store_credential",
]
