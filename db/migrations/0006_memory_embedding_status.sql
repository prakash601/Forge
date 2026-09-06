-- 0006_memory_embedding_status.sql
--
-- Add EMBEDDING_FAILED to the memory_items status CHECK so the
-- embedding pipeline (Issue #004) can mark rows whose provider
-- calls failed after retries. No change to memory_embeddings itself.
ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_status_valid;
ALTER TABLE memory_items
    ADD CONSTRAINT memory_items_status_valid
    CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'INVALIDATED', 'EMBEDDING_FAILED'));
