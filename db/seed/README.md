# Forge development seed

This directory contains a deterministic seed used during local development
to verify that the migrations and the database connection work end-to-end.

Phase 0 only verifies that:

1. We can connect to PostgreSQL.
2. The `uuid-ossp` and `vector` extensions are installed.

Application-level seed data (demo users, projects, tasks, runs) is added in
later phases and must follow the rules in
`docs/design/DATABASE_DESIGN_v0.1.md`.

Seed scripts MUST:

- Be idempotent.
- Never run in `production`.
- Never insert credentials.
- Be gated by an explicit `FORGE_SEED=1` environment variable.
