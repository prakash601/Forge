-- 0003_users.sql
--
-- Users table (Phase 1, Issue #003).
--
-- Per docs/design/DATABASE_DESIGN_v0.1.md §7. The ``users`` table is a
-- prerequisite for the ``projects`` table (which references
-- ``users.id`` as its owner). Auth and the full user-management
-- surface (sessions, OAuth providers, password hashing) are
-- intentionally NOT in this migration — they belong to a later issue.
-- This migration establishes only the minimum shape needed for
-- referential integrity.
--
-- The ``id`` column uses ``gen_random_uuid()`` from the ``uuid-ossp``
-- extension enabled in migration 0001.

CREATE TABLE users (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(320) NOT NULL,
    display_name    VARCHAR(255),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Email is the natural unique key. Index it explicitly because the
-- auth flow (later issue) will hit it on every login.
CREATE UNIQUE INDEX users_email_unique
    ON users (email);

-- updated_at honesty: same trigger pattern as the runs table.
CREATE OR REPLACE FUNCTION users_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_touch_updated_at_trigger
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION users_touch_updated_at();