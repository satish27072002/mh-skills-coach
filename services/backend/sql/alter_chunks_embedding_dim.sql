-- Adjust chunks.embedding vector dimension when switching embedding models/providers.
-- This script is idempotent for the target dimension.
-- IMPORTANT: It resets existing vectors to NULL when a dimension change is required.
-- Run reindex afterwards:
--   python -m app.scripts.reindex_embeddings
--
-- Usage:
--   psql "$DATABASE_URL" -v target_dim=1536 -f services/backend/sql/alter_chunks_embedding_dim.sql
--
-- Change target_dim as needed for your embedding model.

DO $$
DECLARE
    current_typmod integer;
    target_dim integer := :'target_dim';
BEGIN
    SELECT a.atttypmod
    INTO current_typmod
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'chunks'
      AND a.attname = 'embedding'
      AND a.attnum > 0
      AND NOT a.attisdropped
    LIMIT 1;

    IF current_typmod IS NULL THEN
        RAISE EXCEPTION 'chunks.embedding column not found';
    END IF;

    IF current_typmod <> target_dim + 4 THEN
        EXECUTE 'DROP INDEX IF EXISTS chunks_embedding_ivfflat_idx';
        EXECUTE format(
            'ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(%s) USING NULL',
            target_dim
        );
        EXECUTE 'CREATE INDEX IF NOT EXISTS chunks_embedding_ivfflat_idx ON chunks USING ivfflat (embedding) WITH (lists = 100)';
    END IF;
END
$$;
