"""0011 runs project

Apply the SQL file db/migrations/0011_runs_project.sql, which adds the
nullable ``runs.project_id`` FK (Phase 4, Issue #016, decided in #57).

Revision ID: 0011_runs_project
Revises: 0010_user_github_auth
Create Date: 2026-09-13 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0011_runs_project"
down_revision = "0010_user_github_auth"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0011_runs_project.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS runs_project_id_idx;")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS project_id;")
