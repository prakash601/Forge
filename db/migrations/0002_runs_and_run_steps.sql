-- 0002_runs_and_run_steps.sql
--
-- Run state machine foundation (Phase 1, Issue #001).
--
-- This migration introduces ONLY the database objects required by the durable
-- Run state machine described in docs/design/STATE_MACHINE_v0.1.md:
--
--   * the `run_state` enum  (matches §2 verbatim)
--   * the `runs` table      (one row per Run; the current state lives here)
--   * the `run_steps` table (one row per applied event; the append-only history)
--
-- Everything else from docs/design/DATABASE_DESIGN_v0.1.md
-- (projects, tasks, memories, decisions, conventions, executions, ...) is
-- added in later migrations and tracked in separate issues.
--
-- Durability contract (DATABASE_DESIGN_v0.1.md §2.1, §2.2):
--   * The state update and the run_steps insert MUST occur in the same
--     transaction. The application layer enforces this; the database only
--     guarantees the column types and FK.
--   * run_steps is append-only. We do not declare a trigger to forbid
--     UPDATE/DELETE because alembic downgrades legitimately drop and recreate
--     tables during local resets; the contract is enforced at the
--     application/service layer.

-- ---------------------------------------------------------------------------
-- Enum: run_state
-- ---------------------------------------------------------------------------
-- Must match docs/design/STATE_MACHINE_v0.1.md §2 exactly. Adding a value
-- here is a contract change and requires a STATE_MACHINE doc bump.
CREATE TYPE run_state AS ENUM (
    'CREATED',
    'ANALYZING',
    'PLANNING',
    'AWAITING_APPROVAL',
    'IMPLEMENTING',
    'TESTING',
    'DEBUGGING',
    'REVIEWING',
    'COMPLETED',
    'FAILED',
    'CANCELLED',
    'NEEDS_HUMAN'
);

-- ---------------------------------------------------------------------------
-- Table: runs
-- ---------------------------------------------------------------------------
-- One row per Run. `state` is the current state. `terminal` is a denormalized
-- boolean for cheap filtering (terminal states per STATE_MACHINE §10:
-- COMPLETED, FAILED, CANCELLED; NEEDS_HUMAN is operationally paused, not
-- terminal, so it is intentionally excluded).
CREATE TABLE runs (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    state           run_state    NOT NULL DEFAULT 'CREATED',
    -- Terminal denormalized flag. Kept in sync by the application layer on
    -- every transition. Stored alongside state so we can index it for
    -- operational queries (e.g. "list non-terminal runs older than X").
    is_terminal     BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Free-form task text from the user. Added now (rather than in a later
    -- migration) because the MVP flow requires it for planning context.
    -- Detailed project / repository / author fields arrive in later issues.
    task            TEXT         NOT NULL,
    -- Monotonic counter bumped on every transition. Used as an optimistic
    -- concurrency token: a transition applies only if `version` matches
    -- the value the caller observed. This makes the state machine safe
    -- under concurrent event application.
    version         BIGINT       NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Operational index: "find runs that are still active, oldest first."
CREATE INDEX runs_active_updated_at_idx
    ON runs (updated_at)
    WHERE is_terminal = FALSE;

-- ---------------------------------------------------------------------------
-- Table: run_steps
-- ---------------------------------------------------------------------------
-- Append-only history of every state transition applied to a Run. One row
-- per event. The (run_id, sequence) pair is unique. `sequence` starts at 1
-- for the first event applied to a given run.
CREATE TABLE run_steps (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID         NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    -- 1-based per-run sequence. Assigned by the application layer inside
    -- the same transaction as the state update.
    sequence        BIGINT       NOT NULL,
    -- State of the run at the moment the event was applied.
    from_state      run_state    NOT NULL,
    -- Event that was applied.
    -- We do NOT model the event set as an enum here because the transition
    -- table is the source of truth for which events exist; storing it as
    -- TEXT keeps the contract checkable in code and easy to extend.
    event           TEXT         NOT NULL,
    -- State the run transitioned to as a result of applying the event.
    to_state        run_state    NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT run_steps_run_sequence_unique UNIQUE (run_id, sequence)
);

CREATE INDEX run_steps_run_id_created_at_idx
    ON run_steps (run_id, created_at);

-- ---------------------------------------------------------------------------
-- Trigger: keep `updated_at` honest
-- ---------------------------------------------------------------------------
-- A simple BEFORE UPDATE trigger that bumps `updated_at`. We do NOT use
-- `BEFORE UPDATE` to mutate `state` or `version` — those are managed by the
-- application transaction so that the corresponding run_steps insert is
-- guaranteed to land in the same DB transaction.
CREATE OR REPLACE FUNCTION runs_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER runs_touch_updated_at_trigger
    BEFORE UPDATE ON runs
    FOR EACH ROW
    EXECUTE FUNCTION runs_touch_updated_at();