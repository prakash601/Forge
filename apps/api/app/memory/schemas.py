"""Pydantic schemas for the memory API.

The MVP exposes only create + list. The embedding is not part of the
request body — it is generated asynchronously by a later issue.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.memory.enums import MemoryStatus, MemoryType


class MemoryItemCreate(BaseModel):
    """Body for ``POST /api/v1/projects/{id}/memory``."""

    memory_type: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "Kind of fact. Suggested: decision, convention, observation, "
            "fact, preference. The application accepts any string that "
            "fits in VARCHAR(100)."
        ),
    )
    title: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=1, description="The fact to remember.")
    source_type: str | None = Field(default=None, max_length=100)
    source_id: uuid.UUID | None = None
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="0..1 confidence score. NULL means 'no score recorded'.",
    )
    repository_commit: str | None = Field(default=None, max_length=100)

    @field_validator("memory_type")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        # We accept any string but normalize the case for known enum
        # members so the DB column reads consistently.
        try:
            return MemoryType(value.lower()).value
        except ValueError:
            return value


class MemoryItemRead(BaseModel):
    """Response view for memory items.

    The embedding is intentionally not exposed; it is internal data
    that the Archaeologist (real, future) uses for retrieval.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    memory_type: str
    title: str | None
    content: str
    source_type: str | None
    source_id: uuid.UUID | None
    confidence: float | None
    status: MemoryStatus
    repository_commit: str | None
    created_at: datetime
    updated_at: datetime


class MemoryItemList(BaseModel):
    """Response wrapper for list endpoints. Empty for now; the
    pagination envelope can grow in a later issue."""

    items: list[MemoryItemRead] = Field(default_factory=list)
    count: int = Field(description="Total items returned in this page.")


__all__ = ["MemoryItemCreate", "MemoryItemList", "MemoryItemRead"]
