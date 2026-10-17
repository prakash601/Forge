"""0004 projects

Apply the SQL file db/migrations/0004_projects.sql, which adds the
``projects`` table. The full project surface (members, repositories,
settings) is added in later issues.

Revision ID: 0004_projects
Revises: 0003_users
Create Date: 2026-09-02 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0004_projects"
down_revision = "0003_users"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0004_projects.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS projects_touch_updated_at_trigger ON projects;")
    op.execute("DROP FUNCTION IF EXISTS projects_touch_updated_at();")
    op.execute("DROP TABLE IF EXISTS projects;")
