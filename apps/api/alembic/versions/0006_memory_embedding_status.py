"""0006 memory embedding status

Add EMBEDDING_FAILED to the memory_items status CHECK constraint.

Revision ID: 0006_memory_embedding_status
Revises: 0005_memory
Create Date: 2026-09-06 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0006_memory_embedding_status"
down_revision = "0005_memory"
branch_labels = None
depends_on = None


_SQL_FILE = (
    Path(__file__).resolve().parents[4] / "db" / "migrations" / "0006_memory_embedding_status.sql"
)


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_status_valid;")
    op.execute(
        "ALTER TABLE memory_items ADD CONSTRAINT memory_items_status_valid "
        "CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'INVALIDATED'));"
    )
