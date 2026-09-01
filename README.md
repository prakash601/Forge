# Forge

> An AI software engineering system that maintains persistent project context and owns the engineering loop from understanding a task to producing and verifying a working change.

---

## What Forge is

Forge is not an AI coding assistant. It is an **AI software engineering platform** that:

1. Connects to a repository.
2. Understands the codebase.
3. Plans an engineering change.
4. Implements the change in isolation.
5. Runs validation.
6. Debugs failures.
7. Reviews the result.
8. Remembers the outcome as project memory.

The product thesis and target users are summarized below; the full PRD is maintained privately.

---

## Current project status

**Phase 1 — MVP Vertical Slice Foundations.** The Phase 0 repository
bootstrap is complete; we are now building the durable orchestration
backbone (Run state machine, schema, minimal API). Agents and the
autonomous loop come in Phase 2.

See [docs/STATUS.md](docs/STATUS.md) for the phase ledger, current goal,
and the index of all run-task issues.

**Not implemented yet (Phase 2+):**

- The AI agent runtime (Archaeologist, Architect, Developer, Tester, Debugger, Reviewer).
- The autonomous coding loop.
- GitHub repository integration and PR automation.
- Project memory retrieval.
- The execution sandbox and Docker-based code execution.
- Authentication, multi-tenant authorization, and the full API surface.
- The Forge dashboard.

The product can be brought up locally as a stack of three empty skeletons (API, web, worker) backed by PostgreSQL with `pgvector`. They expose health endpoints and a placeholder home page only.

See [Documentation](#documentation) below for how the design documents are managed.

---

## Architecture overview

Forge is designed as a **modular monolith** plus an isolated execution worker. The control plane (API + orchestrator + memory) and the execution plane (worker + sandbox) are deliberately separated so that untrusted generated code never runs on the API host.

```text
                          ┌───────────────┐
                          │     USER      │
                          └───────┬───────┘
                                  │
                                  ▼
                       ┌───────────────────┐
                       │   Next.js Web UI  │
                       └─────────┬─────────┘
                                 │
                          REST + SSE
                                 │
                                 ▼
                       ┌───────────────────┐
                       │      FastAPI      │
                       │    Control Plane  │
                       └─────────┬─────────┘
                                 │
                 ┌───────────────┼────────────────┐
                 ▼               ▼                ▼
            PostgreSQL        Memory         Orchestrator
                 │               │                │
                 │               ▼                ▼
                 │           pgvector        Agent Runtime
                 │                                │
                 │                                ▼
                 │                         Execution Worker
                 │                                │
                 │                                ▼
                 │                           Docker Sandbox
                 │                                │
                 │                     ┌──────────┼──────────┐
                 │                     ▼          ▼          ▼
                 │                  Source      Tests       Git
                 │                                           │
                 │                                           ▼
                 └─────────────────────────────────────── GitHub
```

The full architecture is described in the internal high-level design document (maintained privately).

---

## Repository structure

```text
forge/
├── apps/
│   ├── api/                  # FastAPI control plane
│   └── web/                  # Next.js dashboard
│
├── workers/
│   └── execution/            # Isolated execution worker (Phase 5+)
│
├── packages/
│   └── shared/               # Shared types and helpers
│
├── db/
│   ├── migrations/           # Alembic database migrations
│   └── seed/                 # Development seed data
│
├── docs/                     # Design documents (private, not in this repo)
│
├── infra/                    # Local infrastructure assets
├── scripts/                  # Local development scripts
├── .github/workflows/        # CI
│
├── docker-compose.yml
├── .env.example
└── README.md
```

This layout keeps the control plane (`apps/api`), execution plane (`workers/`), and shared code (`packages/`) cleanly separated.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router) + TypeScript |
| Frontend styling | Tailwind CSS |
| Backend | Python + FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2.x |
| Migrations | Alembic |
| Database | PostgreSQL 16 + pgvector |
| Worker | Python (asyncio) |
| Containerization | Docker / Docker Compose |
| CI | GitHub Actions |
| LLM | Provider abstraction (deferred — see LLD) |

Package managers:

- Python: `uv` (Astral) with a workspace `pyproject.toml` per app.
- JavaScript/TypeScript: `pnpm` workspaces at the repo root.

---

## Local development

### Prerequisites

- Docker and Docker Compose v2.
- Python 3.11+ and `uv` (https://docs.astral.sh/uv/).
- Node.js 24+ and `pnpm` (https://pnpm.io/).

### First-time setup

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start local infrastructure (PostgreSQL + pgvector)
docker compose up -d postgres

# 3. Install Python dependencies for the API and worker
export PATH="$HOME/.local/bin:$PATH"
uv sync --directory apps/api
uv sync --directory workers/execution

# 4. Run database migrations
uv run --directory apps/api alembic upgrade head

# 5. Install Node dependencies for the web app
pnpm install
```

### Running the applications

In three terminals (or with a process manager of your choice):

```bash
# Terminal 1 — API on :8000
uv run --directory apps/api uvicorn app.main:app --reload

# Terminal 2 — Worker
uv run --directory workers/execution python -m forge_worker

# Terminal 3 — Web on :3000
pnpm --filter @forge/web dev
```

Then open:

- Web: http://localhost:3000
- API health: http://localhost:8000/health
- API readiness: http://localhost:8000/ready

The Phase 0 home page shows the word **Forge** and a small indicator of backend connectivity. The API only exposes `GET /health` and `GET /ready` plus the versioned router under `/api/v1` (which is empty until Phase 1).

### Running everything with Docker

```bash
docker compose up
```

This starts PostgreSQL plus optional `api`, `worker`, and `web` profiles. See [`docker-compose.yml`](docker-compose.yml) for the current set of services and profiles.

---

## Running tests

```bash
# API tests
uv run --directory apps/api pytest

# Web tests
pnpm --filter @forge/web test

# Worker tests
uv run --directory workers/execution pytest
```

---

## Environment variables

All environment variables are declared in [`.env.example`](.env.example). Only variables actually consumed by the current skeleton are required. The application fails fast on startup if a required variable is missing.

Current variables:

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | API, worker | PostgreSQL DSN (async-friendly) |
| `API_PORT` | API | HTTP listen port (default 8000) |
| `WEB_PORT` | Web | Next.js dev port (default 3000) |
| `LOG_LEVEL` | API, worker | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ENVIRONMENT` | API, worker | `development`, `test`, or `production` |
| `API_BASE_URL` | Web | URL the browser uses to reach the API |
| `CORS_ALLOW_ORIGINS` | API | Comma-separated list of allowed origins |

Secrets (LLM provider keys, GitHub tokens, etc.) are **not** introduced in Phase 0. When they are added, they will be required from a secret manager — never committed to the repository.

---

## Database

- Engine: PostgreSQL 16.
- Extensions enabled: `uuid-ossp` and `vector` (pgvector).
- Migrations: Alembic, located in [`db/migrations`](db/migrations).
- Seeds: deterministic dev seed in [`db/seed`](db/seed), gated by `ENVIRONMENT=development`.

Phase 0 only enables the required extensions; application tables are introduced by later migrations in Phase 1+.

---

## CI/CD

GitHub Actions CI lives in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). It runs on every push and pull request to `main`:

1. Checkout.
2. Spin up PostgreSQL + pgvector.
3. Install Python dependencies with `uv`.
4. Install Node dependencies with `pnpm`.
5. Lint and type-check the API, worker, and web app.
6. Run unit tests.
7. Validate that Alembic migrations apply from an empty database.
8. Build the Next.js application.

Deployment workflows are not introduced in Phase 0.

---

## Development workflow

- Branch from `main`: `feature/<scope>`, `fix/<scope>`, `chore/<scope>`, `docs/<scope>`.
- No direct pushes to `main` (enforced by PR + CI).
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- All changes go through a Pull Request. CI must pass before merge.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow.

---

## Documentation

The architecture and design documents (PRD, HLD, LLD, database design,
OpenAPI spec, state machine, agent/tool contracts, observability spec,
and security threat model) are maintained **privately** and are not part
of this public repository. The code, CI, and local development setup in
this repo are self-contained.

---

## Roadmap / phases

| Phase | Scope |
|---|---|
| 0 | Repository bootstrap (this phase) |
| 1 | Database + domain models |
| 2 | Project + repository APIs |
| 3 | Task + run APIs |
| 4 | Orchestrator / state machine |
| 5 | Execution worker + Docker sandbox |
| 6 | Repository tools + Git |
| 7 | First agent: Archaeologist |
| 8 | Planner / Architect |
| 9 | Developer agent |
| 10 | Tester |
| 11 | Debug / retry loop |
| 12 | Reviewer + GitHub PR |
| 13 | Memory |
| 14 | Observability dashboard |
| 15 | Production hardening |
