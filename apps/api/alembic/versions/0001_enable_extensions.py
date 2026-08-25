"""0001 enable extensions

Apply the SQL file db/migrations/0001_enable_extensions.sql, which enables
the `uuid-ossp` and `vector` (pgvector) extensions required by every later
migration in the Forge schema.

Revision ID: 0001_enable_extensions
Revises:
Create Date: 2026-08-26 00:00:00

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_enable_extensions"
down_revision = None
branch_labels = None
depends_on = None


_SQL_FILE = Path(__file__).resolve().parents[4] / "db" / "migrations" / "0001_enable_extensions.sql"


def upgrade() -> None:
    sql = _SQL_FILE.read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    # Extensions are required by every later migration. Dropping them in a
    # downgrade would cascade into table failures, so we keep this as a
    # no-op. To reset, drop and recreate the database.
    pass
