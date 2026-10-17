-- 0013_project_auto_approve.sql
--
-- Per-project policy-approval opt-in (Phase 4, Issue #020).
--
-- The v1.0 default requires human plan approval
-- (``FORGE_AUTO_APPROVE=false``); a project opts back into machine
-- policy approval with ``auto_approve_policy``. Defaults FALSE so
-- existing projects keep the human gate.

ALTER TABLE projects
    ADD COLUMN auto_approve_policy BOOLEAN NOT NULL DEFAULT FALSE;
