"""0002 runs and run steps

Apply the SQL file db/migrations/0002_runs_and_run_steps.sql, which adds:

  * the ``run_state`` enum
  * the ``runs`` and ``run_steps`` tables required by the durable Run state
    machine described in docs/design/STATE_MACHINE_v0.1.md (§2 and §4)

Revision ID: 0002_runs_and_run_steps
Revises: 0001_enable_extensions
Create Date: 2026-09-02 00:00:00

"""
from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_runs_and_run_steps"
down_revision = "0001_enable_extensions"
branch_labels = None
depends_on = None


_SQL_FILE = (
    Path(__file__).resolve().parents[4]
    / "db"
    / "migrations"
    / "0002_runs_and_run_steps.sql"
)


def upgrade() -> None:
    sql = _SQL_FILE.read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    # Reverse order matters because of the FK from run_steps.run_id -> runs.id
    # and because the enum type is referenced by both tables.
    op.execute("DROP TABLE IF EXISTS run_steps;")
    op.execute("DROP TABLE IF EXISTS runs;")
    op.execute("DROP TYPE IF EXISTS run_state;")
    op.execute("DROP FUNCTION IF EXISTS runs_touch_updated_at();")