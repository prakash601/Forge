"""Alembic environment.

Forge stores migration scripts as plain SQL files under
`../../db/migrations/`, but uses Alembic to track which files have been
applied. This script wires the database URL from application settings and
applies files in lexical order.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `app` importable so we can read settings.
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.config import get_settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
if settings.database_url is None:
    raise SystemExit(
        "DATABASE_URL is not configured. Copy .env.example to .env at the "
        "repository root (or export DATABASE_URL), then re-run migrations. "
        "See CONTRIBUTING.md -> 'Running PostgreSQL'."
    )
config.set_main_option(
    "sqlalchemy.url", str(settings.database_url).replace("postgresql+asyncpg", "postgresql+psycopg")
)

# Migrations are tracked in the standard Alembic version table; we do not
# use autogenerate or a metadata target.
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
