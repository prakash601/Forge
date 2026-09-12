"""0008 planning approval

Planner + Developer stores and approval audit (Phase 2, Issue #008).

Revision ID: 0008_planning_approval
Revises: 0007_run_analyses
Create Date: 2026-09-12 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0008_planning_approval"
down_revision = "0007_run_analyses"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0008_planning_approval.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE run_steps DROP COLUMN IF EXISTS approved_by;")
    op.execute("DROP TABLE IF EXISTS run_implementations;")
    op.execute("DROP TABLE IF EXISTS run_plans;")
