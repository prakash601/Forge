-- 0008_planning_approval.sql
--
-- Planner + Developer stores and approval audit (Phase 2, Issue #008).
--
-- * run_plans: one validated plan per Run (AGENT_CONTRACTS §7).
-- * run_implementations: one Developer result per Run (§8).
-- * run_steps.approved_by: actor recorded on plan_approved steps
--   ('human' | 'policy', see CONTEXT.md approval vocabulary).

CREATE TABLE run_plans (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    plan            JSONB        NOT NULL,
    provider        TEXT         NOT NULL,
    model           TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE run_implementations (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    result          JSONB        NOT NULL,
    provider        TEXT         NOT NULL,
    model           TEXT         NOT NULL,
    workspace_path  TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE run_steps ADD COLUMN approved_by TEXT;
