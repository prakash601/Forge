"""0009 test review memory

Tester, Debugger, Reviewer, and memory-candidate stores (Phase 2, Issue #009).

Revision ID: 0009_test_review_memory
Revises: 0008_planning_approval
Create Date: 2026-09-12 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0009_test_review_memory"
down_revision = "0008_planning_approval"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0009_test_review_memory.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_memories;")
    op.execute("DROP TABLE IF EXISTS run_reviews;")
    op.execute("DROP TABLE IF EXISTS run_diagnoses;")
    op.execute("DROP TABLE IF EXISTS run_test_results;")
