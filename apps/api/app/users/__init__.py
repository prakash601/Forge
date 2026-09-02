"""Users package.

A minimal user table exists so that ``projects.owner_id`` has a
referential target. The full user-management surface (sessions,
password hashing, OAuth providers) is intentionally deferred to a
later issue; this package exposes only CRUD.

Layering
--------
``enums``    — :class:`UserStatus` (currently a placeholder).
``models``   — SQLAlchemy ORM mapping.
``errors``   — Typed exceptions.
``service``  — Repository-style functions over the ORM models.
``schemas``  — Pydantic request/response shapes.
"""

from __future__ import annotations

from app.users.enums import UserStatus
from app.users.errors import UserNotFoundError
from app.users.models import User
from app.users.service import create_user, get_user

__all__ = [
    "User",
    "UserNotFoundError",
    "UserStatus",
    "create_user",
    "get_user",
]
