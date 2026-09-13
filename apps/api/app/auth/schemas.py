"""Pydantic schemas for the auth API (Phase 4, Issue #015).

User views are reused from :mod:`app.users.schemas`; this module holds
only auth-flow-specific shapes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    """Response view for ``POST /api/v1/auth/logout``."""

    ok: bool = Field(default=True, description="Logout completed.")


__all__ = ["AuthStatus"]
