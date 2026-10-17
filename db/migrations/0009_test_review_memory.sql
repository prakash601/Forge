-- 0009_test_review_memory.sql
--
-- Tester, Debugger, Reviewer, and memory-candidate stores (Phase 2, Issue #009).
--
-- * run_test_results: one Tester report per Run (AGENT_CONTRACTS §9).
-- * run_diagnoses: one Debugger diagnosis per Run (§10).
-- * run_reviews: one Reviewer decision per Run (§11).
-- * run_memories: outcome candidates for the next Archaeologist run.

CREATE TABLE run_test_results (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    result          JSONB        NOT NULL,
    provider        TEXT         NOT NULL,
    model           TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE run_diagnoses (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    diagnosis       JSONB        NOT NULL,
    provider        TEXT         NOT NULL,
    model           TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE run_reviews (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    review          JSONB        NOT NULL,
    provider        TEXT         NOT NULL,
    model           TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE run_memories (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    candidates      JSONB        NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
