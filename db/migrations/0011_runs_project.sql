-- 0011_runs_project.sql
--
-- Project ownership for runs (Phase 4, Issue #016, decided in #57).
--
-- ``runs.project_id`` is NULLABLE: pre-existing rows stay ownerless
-- (NULL) and are hidden from non-admin reads; all new creates set it
-- (enforced at the API layer). Follows the ON DELETE CASCADE
-- convention of projects/memory FKs.

ALTER TABLE runs
    ADD COLUMN project_id UUID NULL REFERENCES projects (id) ON DELETE CASCADE;

CREATE INDEX runs_project_id_idx
    ON runs (project_id);
