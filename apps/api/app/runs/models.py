"""SQLAlchemy ORM models for the Run state machine.

The schema is owned by migration ``0002_runs_and_run_steps``. Any schema
change must come as a new migration; do not mutate these models without
also writing the corresponding SQL file.

The ORM mapping here is intentionally minimal:

  * ``Run`` represents the current state of the workflow.
  * ``RunStep`` is the append-only history of applied events.

The service layer (:mod:`app.runs.service`) is the only place that
mutates ``Run.state`` and inserts ``RunStep`` rows, and it always does
both in a single transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.runs.enums import RunState


class Base(DeclarativeBase):
    """Declarative base for the runs package models.

    Kept separate from any future global ``Base`` so Phase 1 owns its own
    schema and cannot be accidentally mutated by other packages.
    """


class Run(Base):
    """A durable Run record. See STATE_MACHINE_v0.1.md §2, §5, §6."""

    __tablename__ = "runs"
    __table_args__ = (
        Index(
            "runs_active_updated_at_idx",
            "updated_at",
            postgresql_where=text("is_terminal = FALSE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    state: Mapped[RunState] = mapped_column(
        SAEnum(
            RunState,
            name="run_state",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,  # created by migration 0002
        ),
        nullable=False,
        default=RunState.CREATED,
        server_default=RunState.CREATED.value,
    )
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    steps: Mapped[list[RunStep]] = relationship(
        "RunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunStep.sequence",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Run id={self.id} state={self.state.value} version={self.version}>"


class RunStep(Base):
    """An applied event in a Run's history. See STATE_MACHINE_v0.1.md §5."""

    __tablename__ = "run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="run_steps_run_sequence_unique"),
        Index("run_steps_run_id_created_at_idx", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_state: Mapped[RunState] = mapped_column(
        SAEnum(
            RunState,
            name="run_state",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,
        ),
        nullable=False,
    )
    event: Mapped[str] = mapped_column(Text, nullable=False)
    to_state: Mapped[RunState] = mapped_column(
        SAEnum(
            RunState,
            name="run_state",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[Run] = relationship("Run", back_populates="steps")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"<RunStep run_id={self.run_id} seq={self.sequence} "
            f"{self.from_state.value} --{self.event}--> {self.to_state.value}>"
        )


__all__ = ["Base", "Run", "RunStep"]
