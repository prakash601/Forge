#!/usr/bin/env bash
#
# Run lint, format check, typecheck, and unit tests for the API, worker,
# shared package, and web app.
#
# Usage:
#   ./scripts/check.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export PATH="$HOME/.local/bin:$PATH"

echo "==> API: sync (dev extras)"
uv sync --directory apps/api --all-extras --quiet

echo "==> Worker: sync (dev extras)"
uv sync --directory workers/execution --all-extras --quiet

echo "==> Shared: sync (dev extras)"
uv sync --directory packages/shared --all-extras --quiet

echo "==> API: lint + format"
uv run --directory apps/api ruff check .
uv run --directory apps/api ruff format --check .

echo "==> Worker: lint + format"
uv run --directory workers/execution ruff check .
uv run --directory workers/execution ruff format --check .

echo "==> Shared: lint"
uv run --directory packages/shared ruff check .

echo "==> API: typecheck"
uv run --directory apps/api mypy app

echo "==> Worker: typecheck"
uv run --directory workers/execution mypy src

echo "==> API: tests"
uv run --directory apps/api pytest

echo "==> Worker: tests"
uv run --directory workers/execution pytest

echo "==> Shared: tests"
uv run --directory packages/shared pytest

echo "==> Web: install"
pnpm install --frozen-lockfile

echo "==> Web: lint + typecheck + tests + build"
pnpm --filter @forge/web lint
pnpm --filter @forge/web typecheck
pnpm --filter @forge/web test
pnpm --filter @forge/web build

echo "All checks passed."
