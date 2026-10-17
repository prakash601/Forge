-- 0012_github_pr.sql
--
-- GitHub PR automation stores (Phase 4, Issue #018, decided in #59).
--
-- * projects.repo_url / default_branch / github_credential_ref: the
--   connected repository (nullable until connected). The credential is
--   an opaque ref (``cred:<uuid>``) into github_credentials — never a
--   plaintext token column.
-- * runs.branch / runs.base_commit: task branch + cloned base commit,
--   recorded at run creation for repo-backed runs (NULL otherwise).
-- * github_credentials: encrypted per-user PATs for backend-only use.
-- * pull_requests: one row per published run (run_id UNIQUE for
--   idempotency), with redacted failure info when publication fails.

ALTER TABLE projects
    ADD COLUMN repo_url TEXT NULL,
    ADD COLUMN default_branch TEXT NOT NULL DEFAULT 'main',
    ADD COLUMN github_credential_ref TEXT NULL;

ALTER TABLE runs
    ADD COLUMN branch TEXT NULL,
    ADD COLUMN base_commit TEXT NULL;

CREATE TABLE github_credentials (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_encrypted TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX github_credentials_user_id_idx
    ON github_credentials (user_id);

CREATE TABLE pull_requests (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID         NOT NULL UNIQUE REFERENCES runs (id) ON DELETE CASCADE,
    project_id      UUID         NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    pr_number       INTEGER      NULL,
    pr_url          TEXT         NULL,
    head_branch     TEXT         NOT NULL,
    base_commit     TEXT         NULL,
    status          TEXT         NOT NULL DEFAULT 'PUBLISHED',
    error_redacted  TEXT         NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX pull_requests_project_id_idx
    ON pull_requests (project_id);
