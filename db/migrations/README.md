# Forge database migrations

This directory holds versioned SQL migrations applied by Alembic.

## Layout

- `0001_enable_extensions.sql` — enables `uuid-ossp` and `vector`.
- Future migrations follow the pattern `NNNN_short_name.sql`.

## Why SQL files instead of `alembic revision --autogenerate`?

- The schema is locked by the LLD/Database Design. We do not want the
  application to silently change it.
- All migrations must be reviewed before commit.
- We use plain SQL with explicit `CREATE TABLE` / `ALTER TABLE` statements
  matching `docs/design/DATABASE_DESIGN_v0.1.md` verbatim.

## Workflow

Alembic orchestrates the migration metadata, but the actual schema is
written by hand in these SQL files. The migration helper script
(`scripts/migrate.sh`) executes the SQL files in order and records the
applied versions in `alembic_version`.

A new migration must:

1. Be added as a new file. **Never edit an applied migration.**
2. Be reversible (or be clearly marked one-way with a justification).
3. Match the contract in `docs/design/DATABASE_DESIGN_v0.1.md`.

## Local commands

```bash
# Apply all migrations
uv run --directory apps/api alembic upgrade head

# Roll back one step
uv run --directory apps/api alembic downgrade -1

# Show current version
uv run --directory apps/api alembic current
```
