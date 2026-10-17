"""0013 project auto approve

Apply the SQL file db/migrations/0013_project_auto_approve.sql, which
adds ``projects.auto_approve_policy`` (Phase 4, Issue #020).

Revision ID: 0013_project_auto_approve
Revises: 0012_github_pr
Create Date: 2026-09-13 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0013_project_auto_approve"
down_revision = "0012_github_pr"
branch_labels = None
depends_on = None


_SQL_FILE = (
    Path(__file__).resolve().parents[4] / "db" / "migrations" / "0013_project_auto_approve.sql"
)


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS auto_approve_policy;")
