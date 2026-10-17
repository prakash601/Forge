"""0010 user github auth

Apply the SQL file db/migrations/0010_user_github_auth.sql, which adds
``github_id`` and ``github_token_encrypted`` to the ``users`` table
(Phase 4, Issue #015, decided in #56).

Revision ID: 0010_user_github_auth
Revises: 0009_test_review_memory
Create Date: 2026-09-13 00:00:00
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0010_user_github_auth"
down_revision = "0009_test_review_memory"
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0010_user_github_auth.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_github_id_unique;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS github_token_encrypted;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS github_id;")
