-- 0004_projects.sql
--
-- Projects table (Phase 1, Issue #003).
--
-- Per docs/design/DATABASE_DESIGN_v0.1.md §8. A Project groups Runs
-- and Memory Items under a single owner (User). The MVP defines only
-- the shape needed for referential integrity; the full project
-- surface (repositories, members, settings) is introduced in later
-- issues.

CREATE TABLE projects (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    status          VARCHAR(50)  NOT NULL DEFAULT 'ACTIVE',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- Status must be one of the known values. The application enforces
    -- this with a Python enum; the database adds a CHECK so a stray
    -- writer cannot insert garbage.
    CONSTRAINT projects_status_valid CHECK (status IN ('ACTIVE', 'ARCHIVED', 'DELETED'))
);

-- Operational index: "list a user's projects, newest first".
CREATE INDEX projects_owner_id_created_at_idx
    ON projects (owner_id, created_at DESC);

-- Operational index: "find active projects globally" (used by admin
-- tools and the dashboard once it lands).
CREATE INDEX projects_status_idx
    ON projects (status)
    WHERE status = 'ACTIVE';

-- updated_at honesty.
CREATE OR REPLACE FUNCTION projects_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER projects_touch_updated_at_trigger
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION projects_touch_updated_at();