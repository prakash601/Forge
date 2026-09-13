"""GitHub credential seam (Phase 4, Issue #015; consumed by #018).

:func:`resolve_credential` decrypts the GitHub OAuth token behind an
opaque ``ref`` (``user:<uuid>``, stored on projects as
``github_credential_ref``) for one backend-only operation. It must
only be called from inside :mod:`app.github` (clone/push/PR
creation) — enforced by convention and code review; Python offers no
cheaper runtime boundary. Never pass its return value to agent code,
the sandbox, prompts, logs, or API responses.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import InvalidCredentialRefError, NoGitHubCredentialError
from app.auth.tokens import TokenCipher
from app.users.service import get_user


def parse_credential_ref(ref: str) -> uuid.UUID:
    """Parse an opaque ``user:<uuid>`` credential ref to a user id."""
    scheme, _, value = ref.partition(":")
    if scheme != "user" or not value:
        raise InvalidCredentialRefError(f"Malformed credential ref: {ref!r}.")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidCredentialRefError(f"Malformed credential ref: {ref!r}.") from exc


async def resolve_credential(
    session: AsyncSession,
    *,
    ref: str,
    cipher: TokenCipher,
) -> str:
    """Return the decrypted GitHub token behind ``ref`` (backend-only).

    Raises :class:`InvalidCredentialRefError` on malformed refs and
    :class:`NoGitHubCredentialError` when the user has no stored
    credential. The caller must use the token in-memory and never
    persist or expose it.
    """
    user_id = parse_credential_ref(ref)
    user = await get_user(session, user_id)
    if not user.github_token_encrypted:
        raise NoGitHubCredentialError(f"User {user_id} has no GitHub credential.")
    return cipher.decrypt(user.github_token_encrypted)


__all__ = ["NoGitHubCredentialError", "parse_credential_ref", "resolve_credential"]
