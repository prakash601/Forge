"""SQLAlchemy ORM model for ``users``.

The schema is owned by migration ``0003_users``. Any schema change
must come as a new migration; do not mutate these models without
also writing the corresponding SQL file.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """A user record. See DATABASE_DESIGN_v0.1.md §7."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # GitHub identity (Phase 4, Issue #015; migration 0010). Users link
    # on their GitHub verified primary email; github_id is persisted
    # alongside for audit and PR mapping. The OAuth access token is
    # stored Fernet-encrypted and is only readable via the
    # ``resolve_credential`` seam — never serialized into API responses.
    github_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    github_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<User id={self.id} email={self.email!r}>"


__all__ = ["Base", "User"]
