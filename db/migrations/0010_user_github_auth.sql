-- 00010_user_github_auth.sql
--
-- GitHub identity + encrypted OAuth token on users (Phase 4, Issue #015).
--
-- Per decision #56: users link on their GitHub verified primary email
-- (the existing unique ``email`` column stays the match key); ``github_id``
-- is persisted alongside for audit and PR mapping, and the OAuth access
-- token is stored Fernet-encrypted in ``github_token_encrypted`` behind
-- the ``resolve_credential`` seam (never API-exposed). Both columns are
-- NULL for pre-existing rows.

ALTER TABLE users
    ADD COLUMN github_id BIGINT NULL,
    ADD COLUMN github_token_encrypted TEXT NULL;

-- One GitHub account links to at most one user. NULLs (legacy rows)
-- are exempt from the uniqueness check in Postgres.
CREATE UNIQUE INDEX users_github_id_unique
    ON users (github_id);
