"""0003 users

Apply the SQL file db/migrations/0003_users.sql, which adds the
``users`` table. Auth and the full user-management surface are added
in later issues.

Revision ID: 0003_users
Revises: 0002_runs_and_run_steps
Create Date: 2026-09-02 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0003_users"
down_revision = "0002_runs_and_run_steps"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0003_users.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS users_touch_updated_at_trigger ON users;")
    op.execute("DROP FUNCTION IF EXISTS users_touch_updated_at();")
    op.execute("DROP TABLE IF EXISTS users;")
