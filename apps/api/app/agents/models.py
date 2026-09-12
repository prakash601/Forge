"""ORM model for the run_analyses table (migration 0007)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunAnalysis(Base):
    """Persisted Archaeologist findings for one Run."""

    __tablename__ = "run_analyses"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    findings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["RunAnalysis", "RunImplementation", "RunPlan"]


class RunPlan(Base):
    """Persisted Planner output for one Run (AGENT_CONTRACTS §7)."""

    __tablename__ = "run_plans"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunImplementation(Base):
    """Persisted Developer output for one Run (AGENT_CONTRACTS §8)."""

    __tablename__ = "run_implementations"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
