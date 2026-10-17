# Forge — Production Deploy Runbook (Phase 4, Issue #019)

Single-host Compose deployment: Caddy (TLS) → web + api, worker with
host Docker socket for sandboxes, managed Postgres, Prometheus +
Grafana inside the private network.

> `docs/` is local-only in this repo (gitignored), so this runbook
> lives under `infra/` where it ships with the deployment it
> describes.

## Prerequisites

- A host with Docker Engine 24+ and the Compose plugin, ports 80/443 open.
- DNS: `DOMAIN` (e.g. `forge.example.com`) → host.
- Managed Postgres with `pgvector` (Neon/Supabase/RDS — provider
  deferred per #60; any Postgres 16 + pgvector works). Record the DSN
  as `DATABASE_URL` (`postgresql+asyncpg://…`).
- GitHub OAuth app (login) + `FORGE_JWT_SECRET` + `FORGE_CREDENTIALS_KEY`
  (see `.env.example` for generation).
- Images published by `.github/workflows/deploy.yml` (runs on `main`).

## Env matrix

`scripts/deploy.sh` needs in its environment: `TAG`, `DOMAIN`,
`DATABASE_URL`. Image vars default to
`ghcr.io/prakash601/forge-{api,worker,web}:${TAG}` (`OWNER` overrides
the owner).

`.env.prod` (same host, never committed) carries the rest:

| Key | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` | managed Postgres, pooled DSN preferred |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | — | OAuth app with callback `https://DOMAIN/api/v1/auth/github/callback` |
| `FORGE_JWT_SECRET` | random 32+ chars | session signing |
| `FORGE_CREDENTIALS_KEY` | `Fernet.generate_key()` | token encryption at rest |
| `GRAFANA_ADMIN_PASSWORD` | strong password | Grafana admin |
| `CORS_ALLOW_ORIGINS` | `https://DOMAIN` | API CORS (defaults safe) |

Copy the shape from `.env.prod.example`.

## First deploy

1. `git clone` the repo at `main` on the host; `cd` in.
2. Write `.env.prod` per the matrix above.
3. `TAG=<main-SHA> DOMAIN=<domain> DATABASE_URL=<dsn> ./scripts/deploy.sh`
   — pull → `migrate` (`alembic upgrade head`, blocks on failure) →
   up → smoke (`https://DOMAIN/healthz`).
4. Verify: dashboard at `https://DOMAIN`, Grafana at host `:3000`
   (published port is internal-only; use an SSH tunnel), Prometheus
   targets `api:8000` UP.
5. Connect a repo (PAT), drive a run to COMPLETED, confirm the PR.

## Operations

- Logs: `docker compose -f docker-compose.prod.yml logs -f api worker`.
- Metrics: Grafana "Forge" dashboard (runs by state, approvals by
  actor, retries, duration p50/p95, LLM calls/tokens, 5xx rate, PR
  outcomes). Alerts: `ForgeAPIDown` (critical), `ForgeHighErrorRate`
  and `ForgePRPublicationFailing` (warning) — see
  `infra/prometheus/alerts.yml`.
- `/metrics` is reachable only inside the compose network (never
  through Caddy) and needs no session — firewall the host accordingly.

## Rollback

Re-run `scripts/deploy.sh` with the previous good `TAG` (images are
tagged per-`main`-SHA plus `latest`; prefer SHAs). Migrations run
forward only — downgrades are manual (`alembic downgrade`) and only
safe before dependent code paths execute; when in doubt, roll the
image back and leave the schema forward.

## Restore procedure

1. Postgres: point-in-time restore per the managed provider's docs,
   then set `DATABASE_URL` to the restored instance.
2. Re-run `scripts/deploy.sh` with the last good `TAG` (migrations
   re-apply idempotently: `alembic upgrade head` is a no-op when
   current).
3. Verify `/healthz`, dashboard login, and one read-only run read.
4. Rotate `FORGE_JWT_SECRET`/`FORGE_CREDENTIALS_KEY` only if the
   incident involved secret exposure (rotation invalidates sessions
   and stored GitHub credentials — users re-login and reconnect
   repos).

## What this stack is not

Single host, no replicas, no staging env, host-retained logs only —
all per PRD §14 and decision #60. Kubernetes/multi-region are out of
scope for v1.0.
