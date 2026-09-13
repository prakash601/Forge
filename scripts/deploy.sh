#!/usr/bin/env bash
# Forge single-host deploy (Phase 4, Issue #019).
#
# Usage (on the host, from the repo checkout):
#   TAG=<sha> DOMAIN=forge.example.com ./scripts/deploy.sh
#
# Steps: pull → migrate (one-shot, blocks on failure) → up → smoke.
# Any step failing exits nonzero LOUDLY (this script is the migration-
# failure signal: there is no metric for a failed one-shot migration).
#
# Required env: TAG (image tag, e.g. a main SHA), DOMAIN, DATABASE_URL
# (managed Postgres), API_IMAGE/WORKER_IMAGE/WEB_IMAGE default to
# ghcr.io/<owner>/forge-{api,worker,web}:${TAG} unless overridden.
set -euo pipefail

: "${TAG:?set TAG to the image tag to deploy (e.g. a main SHA)}"
: "${DOMAIN:?set DOMAIN to the public hostname}"
: "${DATABASE_URL:?set DATABASE_URL to the managed Postgres DSN}"

OWNER="${OWNER:-prakash601}"
API_IMAGE="${API_IMAGE:-ghcr.io/${OWNER}/forge-api:${TAG}}"
WORKER_IMAGE="${WORKER_IMAGE:-ghcr.io/${OWNER}/forge-worker:${TAG}}"
WEB_IMAGE="${WEB_IMAGE:-ghcr.io/${OWNER}/forge-web:${TAG}}"
export API_IMAGE WORKER_IMAGE WEB_IMAGE
export DOMAIN DATABASE_URL
export PUBLIC_URL="https://$DOMAIN"
COMPOSE="docker compose -f docker-compose.prod.yml"
# NOTE: $COMPOSE is intentionally unquoted below (word-splitting).
# shellcheck disable=SC2086

if [ ! -f .env.prod ]; then
  echo "FATAL: .env.prod missing (see infra/DEPLOY_RUNBOOK.md#env-matrix)" >&2
  exit 2
fi

echo "==> pull ${TAG}"
$COMPOSE pull api worker web caddy prometheus grafana

echo "==> migrate (blocks the deploy on failure)"
$COMPOSE run --rm --no-deps migrate

echo "==> up"
$COMPOSE up -d api worker web caddy prometheus grafana

echo "==> smoke"
for _ in $(seq 1 30); do
  if curl -fsS "https://$DOMAIN/healthz" >/dev/null 2>&1; then
    echo "OK: https://$DOMAIN/healthz live (tag ${TAG})"
    exit 0
  fi
  sleep 5
done
echo "FATAL: smoke failed — https://$DOMAIN/healthz never went live" >&2
$COMPOSE ps
exit 1
