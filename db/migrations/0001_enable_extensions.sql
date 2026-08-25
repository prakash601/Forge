-- 0001_enable_extensions.sql
--
-- Enable the PostgreSQL extensions required by the Forge database design.
--
--   - uuid-ossp: provides gen_random_uuid() (used as the default for primary
--                keys) and other UUID helpers.
--   - vector:    pgvector extension for storing and querying embeddings used
--                by semantic memory retrieval.
--
-- This is the ONLY Phase 0 migration. Application tables are introduced
-- starting in Phase 1 (see docs/design/DATABASE_DESIGN_v0.1.md).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
