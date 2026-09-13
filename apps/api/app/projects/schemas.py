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
    """Body for ``POST /api/v1/projects``.

    Ownership derives from the session (Phase 4, Issue #016); there is
    no owner field to spoof. Payloads that still send ``owner_id`` keep
    validating (extra fields are ignored) but it has no effect.
    """

    name: str = Field(min_length=1, max_length=255, description="Project name.")
    description: str | None = Field(default=None, description="Optional description.")
    auto_approve_policy: bool = Field(
        default=False,
        description="Opt into machine policy plan approval (default: human gate).",
    )


class ProjectRead(BaseModel):
    """Response view for projects."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    status: ProjectStatus
    repo_url: str | None = None
    default_branch: str = "main"
    auto_approve_policy: bool = False
    created_at: datetime
    updated_at: datetime


class RepoConnectRequest(BaseModel):
    """Body for ``POST /api/v1/projects/{id}/repo``.

    The PAT is write-only: accepted here, stored encrypted, never
    returned by any endpoint.
    """

    repo_url: str = Field(
        min_length=1,
        max_length=2000,
        description="https://github.com/<owner>/<repo> (no embedded credentials).",
    )
    default_branch: str = Field(
        default="main",
        min_length=1,
        max_length=255,
        description="Base branch for PRs.",
    )
    credential: str = Field(
        min_length=1,
        max_length=2000,
        description="GitHub PAT with repo scope (write-only).",
    )


class RepoRead(BaseModel):
    """Response view for a connected repository (credential never shown)."""

    repo_url: str
    default_branch: str
    credential_set: bool = Field(description="Whether a credential is stored.")


class ProjectPatch(BaseModel):
    """Body for ``PATCH /api/v1/projects/{id}`` (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    auto_approve_policy: bool | None = Field(
        default=None,
        description="Opt into/out of machine policy plan approval.",
    )


__all__ = ["ProjectCreate", "ProjectPatch", "ProjectRead", "RepoConnectRequest", "RepoRead"]
