"""SQLAlchemy ORM model for ``projects``.

The schema is owned by migration ``0004_projects``. Any schema change
must come as a new migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.projects.enums import ProjectStatus


class Project(Base):
    """A project record. See DATABASE_DESIGN_v0.1.md §8."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Connected GitHub repository (Phase 4, Issue #018; migration
    # 0012). NULL until connected. The credential is an opaque ref
    # (``cred:<uuid>``) — never a plaintext token.
    repo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str] = mapped_column(
        String(255), nullable=False, default="main", server_default="main"
    )
    github_credential_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Policy-approval opt-in (Phase 4, Issue #020; migration 0013).
    # FALSE means plans wait for a human; TRUE restores machine policy
    # approval for this project's runs.
    auto_approve_policy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    status: Mapped[ProjectStatus] = mapped_column(
        String(50),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Project id={self.id} name={self.name!r} owner={self.owner_id}>"


__all__ = ["Base", "Project"]
