-- 0007_run_analyses.sql
--
-- Archaeologist findings store (Phase 2, Issue #007).
--
-- One row per Run: the validated Archaeologist output plus the
-- provider/model that produced it (AGENT_CONTRACTS §12). The findings
-- column conforms to AGENT_CONTRACTS §6 (relevant_files, findings,
-- conventions, dependencies, risks, recommended_focus).
CREATE TABLE run_analyses (
    run_id          UUID         PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    findings        JSONB        NOT NULL,
    provider        TEXT         NOT NULL,
    model           TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
