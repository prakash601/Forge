"""SQLAlchemy ORM models for project memory.

The schema is owned by migration ``0005_memory``. The embedding
column uses pgvector's ``VECTOR(1536)`` type; SQLAlchemy exposes
it as a generic column that we treat as ``list[float] | None`` at
the Python layer. The actual encoding/decoding (numpy, str) is the
embedding pipeline's concern — not in this issue.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.memory.enums import MemoryStatus


class MemoryItem(Base):
    """A single fact about a project. See DATABASE_DESIGN_v0.1.md §19."""

    __tablename__ = "memory_items"
    __table_args__ = (
        Index("memory_items_project_id_idx", "project_id"),
        Index("memory_items_project_id_memory_type_idx", "project_id", "memory_type"),
        Index("memory_items_project_id_status_idx", "project_id", "status"),
        Index("memory_items_project_id_created_at_idx", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[MemoryStatus] = mapped_column(
        String(50),
        nullable=False,
        default=MemoryStatus.ACTIVE,
        server_default=MemoryStatus.ACTIVE.value,
    )
    repository_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # One-to-one: each memory item has at most one embedding. The
    # ``unique=True`` FK on ``MemoryEmbedding.memory_item_id`` is the
    # canonical source of truth; this relationship just makes it
    # convenient to navigate.
    embedding: Mapped[MemoryEmbedding | None] = relationship(
        "MemoryEmbedding",
        back_populates="memory_item",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<MemoryItem id={self.id} type={self.memory_type!r} project={self.project_id}>"


class MemoryEmbedding(Base):
    """Vector representation of a memory item. See DATABASE_DESIGN_v0.1.md §20.

    The ``embedding`` column is nullable: rows are created in this
    issue but the vector is filled in by a later embedding-pipeline
    issue. The HNSW index treats NULLs as not-indexed, so rows
    without a vector are simply not searchable until populated.
    """

    __tablename__ = "memory_embeddings"
    __table_args__ = (
        UniqueConstraint("memory_item_id", name="memory_embeddings_memory_item_id_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # The VECTOR type from pgvector. We declare it without a server
    # default; the column is populated by the embedding pipeline.
    embedding: Mapped[Any | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    memory_item: Mapped[MemoryItem] = relationship("MemoryItem", back_populates="embedding")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<MemoryEmbedding memory_item_id={self.memory_item_id}>"


__all__ = ["Base", "MemoryEmbedding", "MemoryItem"]
