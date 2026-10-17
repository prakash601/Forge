"""0007 run analyses

Archaeologist findings store (Phase 2, Issue #007).

Revision ID: 0007_run_analyses
Revises: 0006_memory_embedding_status
Create Date: 2026-09-12 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0007_run_analyses"
down_revision = "0006_memory_embedding_status"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0007_run_analyses.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_analyses;")
