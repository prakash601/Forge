"""GitHub integration boundary (Phase 4).

Backend-only GitHub access. The single rule of this package: GitHub
credentials never leave it. Agent code, the sandbox, prompts, logs,
and API responses must never receive a token — only the functions
here may call :func:`resolve_credential`, and only to use the token
in-memory inside one backend operation (clone, push, ``POST /pulls``).
"""

from __future__ import annotations

from app.auth.errors import NoGitHubCredentialError
from app.github.credentials import parse_credential_ref, resolve_credential

__all__ = ["NoGitHubCredentialError", "parse_credential_ref", "resolve_credential"]
