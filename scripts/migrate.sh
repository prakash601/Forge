#!/usr/bin/env bash
#
# Apply all Forge database migrations to the local PostgreSQL instance.
#
# Usage:
#   ./scripts/migrate.sh
#
# Requires:
#   - `docker compose up -d postgres` (or a running PostgreSQL with pgvector)
#   - `uv` on PATH
#
# Honors $DATABASE_URL. Defaults to the value from .env.example.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . .env
  set +a
fi

DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://forge:forge@localhost:5432/forge}"
export DATABASE_URL

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found on PATH. Install: https://docs.astral.sh/uv/" >&2
  exit 1
fi

uv sync --directory apps/api --all-extras --quiet
uv run --directory apps/api alembic upgrade head
echo "Migrations applied successfully."
