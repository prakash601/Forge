#!/usr/bin/env bash
#
# Local one-command startup (no domain, no TLS, no managed infra).
#
# Usage:
#   ./scripts/local-up.sh          # build + start everything, follow logs
#   ./scripts/local-up.sh -d       # start detached
#
# Then open:
#   Web: http://localhost:3000
#   API health: http://localhost:8000/health
#
# Log in with the "Continue locally" form (no GitHub OAuth needed).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .env ]; then
  echo "==> No .env found, copying .env.example (local dev defaults)"
  cp .env.example .env
fi

echo "==> Starting Forge locally (postgres + migrate + api + worker + web)"
docker compose up --build "$@"

echo ""
echo "Web: http://localhost:3000"
echo "API: http://localhost:8000/health"
