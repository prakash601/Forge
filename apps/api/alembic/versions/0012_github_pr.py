"""0012 github pr

Apply the SQL file db/migrations/0012_github_pr.sql: repo link columns
on projects, branch/base_commit on runs, plus the github_credentials
and pull_requests tables (Phase 4, Issue #018).

Revision ID: 0012_github_pr
Revises: 0011_runs_project
Create Date: 2026-09-13 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0012_github_pr"
down_revision = "0011_runs_project"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0012_github_pr.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS pull_requests_project_id_idx;")
    op.execute("DROP TABLE IF EXISTS pull_requests;")
    op.execute("DROP INDEX IF EXISTS github_credentials_user_id_idx;")
    op.execute("DROP TABLE IF EXISTS github_credentials;")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS base_commit;")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS branch;")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS github_credential_ref;")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS default_branch;")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS repo_url;")
