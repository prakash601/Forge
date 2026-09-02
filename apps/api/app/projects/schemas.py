"""Pydantic schemas for the projects API.

Shapes follow the LLD and the DATABASE_DESIGN §8 contract. ``status``
is a string in the response (matches the column type) but the
service layer validates against the :class:`ProjectStatus` enum.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.projects.enums import ProjectStatus


class ProjectCreate(BaseModel):
    """Body for ``POST /api/v1/projects``."""

    owner_id: uuid.UUID = Field(description="UUID of the owning user.")
    name: str = Field(min_length=1, max_length=255, description="Project name.")
    description: str | None = Field(default=None, description="Optional description.")


class ProjectRead(BaseModel):
    """Response view for projects."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


__all__ = ["ProjectCreate", "ProjectRead"]
