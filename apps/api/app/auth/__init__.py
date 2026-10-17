"""Auth package (Phase 4, Issue #015, decided in #56).

GitHub OAuth login with session cookies + Bearer dual-accept.

Layering
--------
``errors``       — typed exceptions.
``tokens``       — session JWT mint/verify; Fernet envelope for tokens at rest.
``github``       — OAuth client seam (real httpx client + fake for tests).
``service``      — callback orchestration (exchange → verify → link → mint).
``dependencies`` — :func:`get_current_user` FastAPI dependency.
``schemas``      — auth-adjacent response shapes (user views live in users).
"""

from __future__ import annotations

from app.auth import dependencies, errors, github, service, tokens

__all__ = ["dependencies", "errors", "github", "service", "tokens"]
