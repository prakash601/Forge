"""SQLAlchemy ORM models for backend-only GitHub access (Phase 4, Issue #018).

The schema is owned by migration ``0012_github_pr``.

* ``GitHubCredential``: one encrypted PAT per row, referenced by the
  opaque ``cred:<id>`` ref. Backend-only; never serialized.
* ``PullRequest``: one row per published run (``run_id`` UNIQUE for
  idempotency), with redacted failure info when publication fails.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GitHubCredential(Base):
    """An encrypted GitHub credential (PAT) for backend-only use."""

    __tablename__ = "github_credentials"
    __table_args__ = (Index("github_credentials_user_id_idx", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<GitHubCredential id={self.id} user_id={self.user_id}>"


class PullRequest(Base):
    """Publication record for one run's change as a GitHub PR."""

    __tablename__ = "pull_requests"
    __table_args__ = (Index("pull_requests_project_id_idx", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_branch: Mapped[str] = mapped_column(Text, nullable=False)
    base_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PUBLISHED", server_default="PUBLISHED"
    )
    error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<PullRequest run_id={self.run_id} status={self.status}>"


__all__ = ["Base", "GitHubCredential", "PullRequest"]
