-- Code Indexing ETL Pipeline: Database Schema
-- Migration: 001_code_chunks.sql
--
-- This migration creates tables for storing code chunk metadata and embeddings.
-- SECURITY NOTE: We do NOT store raw code content. Only embeddings, hashes, and
-- line numbers are persisted. Actual code is fetched from GitHub at query time.

-- Enable pgvector extension (should already be enabled in Supabase)
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- Table: code_chunks
-- =============================================================================
-- Stores embeddings and metadata for code chunks. Each chunk represents a
-- semantic unit (function, class, etc.) from a source file.
--
-- Security: file_path_hash is a SHA256 hash, not the actual path.
-- The actual path is stored separately in file_path_lookup.

CREATE TABLE IF NOT EXISTS code_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reference to the repository (assumes repos table exists)
    repo_id UUID NOT NULL,

    -- SHA256 hash of the file path (NOT the plaintext path)
    -- Links to file_path_lookup for reverse resolution
    file_path_hash TEXT NOT NULL,

    -- SHA256 hash of the chunk content, for deduplication
    chunk_hash TEXT NOT NULL,

    -- Position of this chunk within the file (0-indexed)
    chunk_index INTEGER NOT NULL,

    -- Line range in the original file (1-indexed)
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,

    -- Vector embedding for semantic search (768 dimensions)
    -- Nullable to allow staged indexing (insert metadata first, embed later)
    embedding vector(768),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Table: file_path_lookup
-- =============================================================================
-- Stores the mapping from file_path_hash to actual file paths.
-- This table is kept separate for security isolation - in case of breach,
-- embeddings alone cannot reveal code structure without this lookup.

CREATE TABLE IF NOT EXISTS file_path_lookup (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reference to the repository
    repo_id UUID NOT NULL,

    -- SHA256 hash of the file path (matches code_chunks.file_path_hash)
    file_path_hash TEXT NOT NULL,

    -- Actual file path (e.g., "src/auth.py")
    file_path TEXT NOT NULL,

    -- SHA256 hash of entire file content, for change detection
    -- When this changes, we know to re-index the file
    file_content_hash TEXT NOT NULL,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Constraints
-- =============================================================================

-- Ensure unique chunks per file (repo + file + position)
ALTER TABLE code_chunks
ADD CONSTRAINT code_chunks_unique_chunk
UNIQUE (repo_id, file_path_hash, chunk_index);

-- Ensure unique file paths per repo
ALTER TABLE file_path_lookup
ADD CONSTRAINT file_path_lookup_unique_file
UNIQUE (repo_id, file_path_hash);

-- =============================================================================
-- Indexes
-- =============================================================================

-- Index for filtering chunks by repository
CREATE INDEX IF NOT EXISTS idx_code_chunks_repo_id
ON code_chunks(repo_id);

-- Index for looking up chunks by file
CREATE INDEX IF NOT EXISTS idx_code_chunks_file_path_hash
ON code_chunks(repo_id, file_path_hash);

-- Index for file path lookups
CREATE INDEX IF NOT EXISTS idx_file_path_lookup_repo_id
ON file_path_lookup(repo_id);

CREATE INDEX IF NOT EXISTS idx_file_path_lookup_hash
ON file_path_lookup(repo_id, file_path_hash);

-- =============================================================================
-- Vector Index (HNSW)
-- =============================================================================
-- HNSW (Hierarchical Navigable Small World) index for fast approximate
-- nearest neighbor search on embeddings.
--
-- Uncomment when ready for production vector search:
-- CREATE INDEX idx_code_chunks_embedding ON code_chunks
-- USING hnsw (embedding vector_cosine_ops);
--
-- Note: HNSW indexes can be slow to build on large datasets.
-- Consider building during off-peak hours or using IVFFlat for initial testing.

-- =============================================================================
-- Triggers for updated_at
-- =============================================================================

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for code_chunks
DROP TRIGGER IF EXISTS update_code_chunks_updated_at ON code_chunks;
CREATE TRIGGER update_code_chunks_updated_at
    BEFORE UPDATE ON code_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger for file_path_lookup
DROP TRIGGER IF EXISTS update_file_path_lookup_updated_at ON file_path_lookup;
CREATE TRIGGER update_file_path_lookup_updated_at
    BEFORE UPDATE ON file_path_lookup
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Row Level Security (RLS) - Optional
-- =============================================================================
-- Uncomment to enable RLS for multi-tenant isolation
--
-- ALTER TABLE code_chunks ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE file_path_lookup ENABLE ROW LEVEL SECURITY;
--
-- Example policy (adjust based on your auth setup):
-- CREATE POLICY "Users can only access their repos' chunks"
-- ON code_chunks FOR ALL
-- USING (repo_id IN (SELECT id FROM repos WHERE owner_id = auth.uid()));
