-- 0005_memory.sql
--
-- Project memory tables (Phase 1, Issue #003).
--
-- Per docs/design/DATABASE_DESIGN_v0.1.md §19 (memory_items) and §20
-- (memory_embeddings). Memory is the durable record of what Forge has
-- learned about a project: decisions, conventions, observations, and
-- their embeddings for semantic search.
--
-- This migration establishes the schema only. Embedding generation is
-- NOT performed here — a later issue owns the embedding pipeline
-- (model selection, provider, ingestion flow). The VECTOR(1536)
-- column is a placeholder dimension that matches common embedding
-- models (e.g. OpenAI text-embedding-3-small, sentence-transformers
-- all-mpnet-base-v2 returns 768 — chosen 1536 with the intent to
-- match the former; revisit when the model is locked in).

-- ---------------------------------------------------------------------------
-- Enum: memory_status
-- ---------------------------------------------------------------------------
-- The LLD treats status as VARCHAR; we keep the same shape for
-- compatibility but add a CHECK so the database refuses unknown values.
CREATE TABLE memory_items (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID         NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    -- Type is a free-form string so the application can extend without
    -- a migration. Suggested values: "decision", "convention",
    -- "observation", "fact", "preference". The application validates
    -- against a Python enum.
    memory_type         VARCHAR(100) NOT NULL,
    title               VARCHAR(500),
    content             TEXT         NOT NULL,
    -- Source attribution. The LLD does not constrain these; the
    -- application sets them when it ingests a memory item.
    source_type         VARCHAR(100),
    source_id           UUID,
    -- Confidence is a 0..1 score, mirroring how RAG systems rate the
    -- quality of a retrieved fact. NULL means "no confidence recorded".
    confidence          NUMERIC(4, 3),
    status              VARCHAR(50)  NOT NULL DEFAULT 'ACTIVE',
    repository_commit   VARCHAR(100),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT memory_items_status_valid
        CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'INVALIDATED')),
    CONSTRAINT memory_items_confidence_range
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

-- Operational indexes.
CREATE INDEX memory_items_project_id_idx
    ON memory_items (project_id);
CREATE INDEX memory_items_project_id_memory_type_idx
    ON memory_items (project_id, memory_type);
CREATE INDEX memory_items_project_id_status_idx
    ON memory_items (project_id, status);
-- "Latest memory for a project" — useful for dashboards and the
-- Archaeologist's "what do we know about this project?" pass.
CREATE INDEX memory_items_project_id_created_at_idx
    ON memory_items (project_id, created_at DESC);

-- updated_at honesty.
CREATE OR REPLACE FUNCTION memory_items_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER memory_items_touch_updated_at_trigger
    BEFORE UPDATE ON memory_items
    FOR EACH ROW
    EXECUTE FUNCTION memory_items_touch_updated_at();

-- ---------------------------------------------------------------------------
-- Embeddings
-- ---------------------------------------------------------------------------
-- The dimension is a placeholder. The chosen model (decided in a
-- later issue) must match; a column type change requires a migration.
CREATE TABLE memory_embeddings (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_item_id      UUID         NOT NULL REFERENCES memory_items (id) ON DELETE CASCADE,
    embedding           VECTOR(1536),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT memory_embeddings_memory_item_id_unique UNIQUE (memory_item_id)
);

-- HNSW index for cosine-distance nearest-neighbor search. The
-- ``vector_cosine_ops`` operator class is the standard for normalized
-- embeddings and is the default for most RAG systems.
CREATE INDEX memory_embeddings_embedding_hnsw_idx
    ON memory_embeddings
    USING hnsw (embedding vector_cosine_ops);