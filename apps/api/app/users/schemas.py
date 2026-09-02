"""Pydantic schemas for the users API.

The shapes are deliberately minimal: ``UserRead`` is the response
view, ``UserCreate`` is the request body. Email format is validated
by Pydantic; uniqueness is enforced at the database level (raises
``DuplicateUserEmailError`` from the service layer).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Body for ``POST /api/v1/users``."""

    email: EmailStr = Field(description="Unique email address; serves as the login handle later.")
    display_name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional human-readable name.",
    )


class UserRead(BaseModel):
    """Response view for users."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime
    updated_at: datetime


__all__ = ["UserCreate", "UserRead"]
