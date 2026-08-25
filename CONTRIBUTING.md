# Contributing to Forge

Thank you for your interest in contributing to Forge. This document covers how
to set up the project locally, the development workflow, and our quality
expectations.

> **Project status:** Phase 0 — repository bootstrap. The product code is a
> skeleton. The most useful contributions right now are bug fixes to the
> bootstrap, test coverage, documentation, and CI improvements. The product
> feature work begins in Phase 1.

---

## 1. Prerequisites

You will need:

| Tool | Version | Why |
|---|---|---|
| Git | 2.30+ | Version control |
| Docker Desktop / Docker Engine | 24+ with Compose v2 | Local PostgreSQL + pgvector |
| Python | 3.11+ | Backend, worker |
| `uv` | 0.4+ | Python package manager (https://docs.astral.sh/uv/) |
| Node.js | 24+ | Web app |
| `pnpm` | 9+ | Node package manager (https://pnpm.io/) |

On macOS you can install everything with Homebrew:

```bash
brew install git node python@3.11
curl -LsSf https://astral.sh/uv/install.sh | sh
corepack enable && corepack prepare pnpm@latest --activate
```

---

## 2. Local setup

```bash
# Clone your fork
git clone https://github.com/<you>/Forge.git
cd Forge

# Add the upstream remote
git remote add upstream https://github.com/forge/Forge.git

# Copy environment template
cp .env.example .env

# Install Node workspaces
pnpm install
```

---

## 3. Running PostgreSQL

```bash
docker compose up -d postgres
```

This starts PostgreSQL 16 with the `vector` (pgvector) extension pre-installed.
The data is persisted to a named volume; use `docker compose down -v` to
destroy it.

The default connection string is:

```text
postgresql+asyncpg://forge:forge@localhost:5432/forge
```

You can change credentials in `docker-compose.yml` (do not commit secrets).

---

## 4. Backend (API)

```bash
# Install dependencies (creates .venv inside apps/api/)
export PATH="$HOME/.local/bin:$PATH"
uv sync --directory apps/api

# Run database migrations
uv run --directory apps/api alembic upgrade head

# Start the API in development mode
uv run --directory apps/api uvicorn app.main:app --reload
```

The API listens on `http://localhost:8000` by default.

### Endpoints (Phase 0)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness — always 200 OK while the process is running |
| GET | `/ready` | Readiness — 200 OK only when the database is reachable |
| GET | `/api/v1/...` | Versioned application routes (empty in Phase 0) |

---

## 5. Frontend (Web)

```bash
pnpm --filter @forge/web dev
```

Web runs on `http://localhost:3000` and shows a placeholder home page that
displays **Forge** plus a small API connectivity indicator.

---

## 6. Worker

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --directory workers/execution
uv run --directory workers/execution python -m forge_worker
```

The Phase 0 worker does not consume jobs. It loads its configuration,
initializes structured logging, prints `Forge worker started`, and shuts down
cleanly on `SIGINT` / `SIGTERM`.

The worker skeleton intentionally does **not** execute arbitrary shell
commands, run queues, or talk to a database. Those capabilities land in
Phase 5 (Execution Worker + Docker Sandbox).

---

## 7. Running everything with Docker

```bash
docker compose up
```

This starts PostgreSQL and the `api`, `worker`, and `web` services. Each
service is opt-in via a profile (see `docker-compose.yml`). The `postgres`
service starts unconditionally.

---

## 8. Tests

```bash
# API
uv run --directory apps/api pytest

# Worker
uv run --directory workers/execution pytest

# Web
pnpm --filter @forge/web test
```

Each app ships a minimal smoke test in Phase 0:

- `apps/api/tests/test_health.py` — exercises `/health` and `/ready`.
- `apps/web/...` — a render test of the home page.
- `workers/execution/tests/test_lifecycle.py` — proves the worker starts and
  exits with the expected lifecycle log.

---

## 9. Lint and format

```bash
# API
uv run --directory apps/api ruff check .
uv run --directory apps/api ruff format --check .

# Worker
uv run --directory workers/execution ruff check .
uv run --directory workers/execution ruff format --check .

# Web
pnpm --filter @forge/web lint
pnpm --filter @forge/web typecheck
```

`ruff` is used for both linting and formatting in Python. ESLint and
TypeScript are used in the web app.

---

## 10. Database migrations

We use Alembic. Migrations live in [`db/migrations`](db/migrations).

```bash
# Create a new migration
uv run --directory apps/api alembic revision -m "add users table"

# Apply migrations
uv run --directory apps/api alembic upgrade head

# Roll back one migration
uv run --directory apps/api alembic downgrade -1
```

Rules:

- Never edit a migration that has already been applied. Create a new one.
- All migrations must be reversible.
- The first migration in Phase 0 only enables the `uuid-ossp` and `vector`
  extensions. Application tables are introduced starting in Phase 1.

---

## 11. Branch naming

Branches off `main` use one of:

- `feature/<scope>` — new user-visible capability.
- `fix/<scope>` — bug fix.
- `chore/<scope>` — refactor, dependency update, internal change.
- `docs/<scope>` — documentation only.

Examples:

- `feature/api-health-endpoint`
- `fix/db-pool-recycle`
- `chore/bump-fastapi`
- `docs/update-readme`

---

## 12. Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/).

```text
feat(api): add readiness endpoint
fix(web): render forge title on home page
chore(ci): cache pnpm store
docs(readme): add docker compose instructions
```

- Subject line ≤ 72 characters.
- Imperative mood.
- Reference issues with `Refs #123` or `Closes #123` in the body when relevant.

---

## 13. Pull request expectations

- All changes go through a Pull Request. Direct pushes to `main` are not
  allowed.
- CI must pass before merge. CI runs lint, type-check, unit tests, migration
  validation, and the web build.
- Keep commits focused. Avoid mixing unrelated changes in a single commit.
- Keep PRs reasonably small — prefer to split large work into stacked PRs.
- PR description should explain **what** changed and **why**.
- Update documentation if your change affects public behavior.

---

## 14. CI requirements

CI is defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). It
runs on every push and PR to `main`. A PR cannot be merged unless CI is green.

CI steps:

1. Checkout.
2. Start PostgreSQL with the `vector` extension.
3. Install Python deps with `uv` (cached).
4. Install Node deps with `pnpm` (cached).
5. Lint and type-check the API, worker, and web app.
6. Run unit tests for each app.
7. Apply Alembic migrations from an empty database.
8. Build the Next.js application.

---

## 15. Reporting security issues

Please do not open public issues for suspected security problems. The threat
model and disclosure process are documented in the project's private design
documents; contact the maintainers directly instead.

---

## 16. License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
