"""0005 memory items and embeddings

Apply the SQL file db/migrations/0005_memory.sql, which adds the
``memory_items`` and ``memory_embeddings`` tables. Embedding
generation is owned by a later issue; this migration establishes the
schema only.

Revision ID: 0005_memory
Revises: 0004_projects
Create Date: 2026-09-02 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0005_memory"
down_revision = "0004_projects"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0005_memory.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Order matters: drop child tables before parents. Embeddings
    # references memory_items; memory_items references projects.
    op.execute("DROP TABLE IF EXISTS memory_embeddings;")
    op.execute("DROP TRIGGER IF EXISTS memory_items_touch_updated_at_trigger ON memory_items;")
    op.execute("DROP FUNCTION IF EXISTS memory_items_touch_updated_at();")
    op.execute("DROP TABLE IF EXISTS memory_items;")
