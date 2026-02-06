-- =============================================================================
-- ScopeDocs MVP Database Schema
-- =============================================================================
-- Single file containing all tables needed for MVP.
-- Run with: psql -d scopedocs -f schema.sql
--
-- Required extensions: pgcrypto, vector (pgvector)
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- =============================================================================
-- Core Tables
-- =============================================================================

-- Workspaces: Multi-tenant support
CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OAuth tokens for integrations (GitHub, Slack, Linear)
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,  -- 'github', 'slack', 'linear'
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_type TEXT DEFAULT 'Bearer',
    scope TEXT,
    expires_at TIMESTAMPTZ,
    raw_data JSONB DEFAULT '{}',  -- Full OAuth response
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, provider)
);

-- =============================================================================
-- Code Indexing Tables
-- =============================================================================

-- File path lookup: Maps hash -> actual path (security: separate from embeddings)
CREATE TABLE IF NOT EXISTS file_path_lookup (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL,  -- SHA256 hash of "workspace_id:repo_full_name"
    file_path_hash TEXT NOT NULL,  -- SHA256 hash of file path
    file_path TEXT NOT NULL,  -- Actual path, e.g., "backend/server.py"
    file_content_hash TEXT NOT NULL,  -- SHA256 of content, for change detection
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(repo_id, file_path_hash)
);

-- Code chunks: Stores chunk metadata (NO code content stored)
CREATE TABLE IF NOT EXISTS code_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL,
    file_path_hash TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,  -- SHA256 of chunk content
    chunk_index INTEGER NOT NULL,  -- 0-indexed position in file
    start_line INTEGER NOT NULL,  -- 1-indexed
    end_line INTEGER NOT NULL,
    embedding vector(1024),  -- Together.ai BGE-large embeddings (1024 dims)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(repo_id, file_path_hash, chunk_index)
);

-- Code embeddings: Alternative table for workspace-scoped embeddings
-- (Used by the AI routes, stores more metadata)
CREATE TABLE IF NOT EXISTS code_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repo_full_name TEXT NOT NULL,  -- e.g., "owner/repo"
    file_path TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content_hash TEXT NOT NULL,  -- For change detection
    embedding vector(1024),
    symbol_names TEXT[] DEFAULT '{}',
    language TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, repo_full_name, file_path, chunk_index)
);

-- =============================================================================
-- Generated Documentation Tables
-- =============================================================================

-- Generated docs: Stores AI-generated documentation
CREATE TABLE IF NOT EXISTS generated_docs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repo_full_name TEXT,
    file_path TEXT,  -- NULL for repo-level docs
    doc_type TEXT NOT NULL,  -- 'file', 'module', 'repo_overview', etc.
    title TEXT NOT NULL,
    content TEXT NOT NULL,  -- Markdown content
    references_json JSONB DEFAULT '{}',  -- {"[1]": {"file_path": "...", "start_line": 15}}
    source_commit_sha TEXT,
    is_stale BOOLEAN DEFAULT FALSE,
    version INTEGER DEFAULT 1,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, repo_full_name, file_path, doc_type)
);

-- =============================================================================
-- Integration Data Tables (for Phase 2)
-- =============================================================================

-- Work items: Linear issues, GitHub issues
CREATE TABLE IF NOT EXISTS work_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,  -- e.g., "linear:abc123"
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL,
    team TEXT,
    assignee TEXT,
    project_id TEXT,
    labels TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, external_id)
);

-- Pull requests: GitHub PRs
CREATE TABLE IF NOT EXISTS pull_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,  -- e.g., "github:12345"
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    author TEXT NOT NULL,
    status TEXT NOT NULL,
    repo TEXT NOT NULL,
    files_changed TEXT[] DEFAULT '{}',
    work_item_refs TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    merged_at TIMESTAMPTZ,
    reviewers TEXT[] DEFAULT '{}',
    UNIQUE(workspace_id, external_id)
);

-- Conversations: Slack threads
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,  -- e.g., "slack:C123:1234567890.123456"
    channel TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    messages JSONB DEFAULT '[]',
    participants TEXT[] DEFAULT '{}',
    decision_extracted TEXT,
    work_item_refs TEXT[] DEFAULT '{}',
    pr_refs TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, external_id)
);

-- Message embeddings: For Slack/Linear messages (Phase 2)
CREATE TABLE IF NOT EXISTS message_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source TEXT NOT NULL,  -- 'slack' or 'linear'
    external_id TEXT NOT NULL,
    channel_or_project TEXT,
    summary TEXT NOT NULL,  -- We store summary, not raw message
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, source, external_id)
);

-- =============================================================================
-- Indexes
-- =============================================================================

-- Workspace lookups
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_workspace ON oauth_tokens(workspace_id);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_provider ON oauth_tokens(workspace_id, provider);

-- File path lookups
CREATE INDEX IF NOT EXISTS idx_file_path_lookup_repo ON file_path_lookup(repo_id);
CREATE INDEX IF NOT EXISTS idx_file_path_lookup_hash ON file_path_lookup(repo_id, file_path_hash);

-- Code chunks
CREATE INDEX IF NOT EXISTS idx_code_chunks_repo ON code_chunks(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_chunks_file ON code_chunks(repo_id, file_path_hash);

-- Code embeddings
CREATE INDEX IF NOT EXISTS idx_code_embeddings_workspace ON code_embeddings(workspace_id);
CREATE INDEX IF NOT EXISTS idx_code_embeddings_repo ON code_embeddings(workspace_id, repo_full_name);
CREATE INDEX IF NOT EXISTS idx_code_embeddings_file ON code_embeddings(workspace_id, repo_full_name, file_path);

-- Generated docs
CREATE INDEX IF NOT EXISTS idx_generated_docs_workspace ON generated_docs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_generated_docs_repo ON generated_docs(workspace_id, repo_full_name);

-- Integration data
CREATE INDEX IF NOT EXISTS idx_work_items_workspace ON work_items(workspace_id);
CREATE INDEX IF NOT EXISTS idx_pull_requests_workspace ON pull_requests(workspace_id);
CREATE INDEX IF NOT EXISTS idx_conversations_workspace ON conversations(workspace_id);

-- =============================================================================
-- Vector Indexes (HNSW for fast similarity search)
-- =============================================================================
-- Uncomment when you have data and want to enable vector search:
--
-- CREATE INDEX idx_code_chunks_embedding ON code_chunks
-- USING hnsw (embedding vector_cosine_ops);
--
-- CREATE INDEX idx_code_embeddings_embedding ON code_embeddings
-- USING hnsw (embedding vector_cosine_ops);
--
-- CREATE INDEX idx_generated_docs_embedding ON generated_docs
-- USING hnsw (embedding vector_cosine_ops);

-- =============================================================================
-- Triggers for updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to all tables with updated_at
DO $$
DECLARE
    t TEXT;
BEGIN
    FOR t IN SELECT unnest(ARRAY[
        'workspaces', 'oauth_tokens', 'file_path_lookup', 'code_chunks',
        'code_embeddings', 'generated_docs', 'work_items', 'pull_requests',
        'conversations', 'message_embeddings'
    ])
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS update_%s_updated_at ON %s;
            CREATE TRIGGER update_%s_updated_at
                BEFORE UPDATE ON %s
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        ', t, t, t, t);
    END LOOP;
END $$;

-- =============================================================================
-- Helper: Create a default workspace for testing
-- =============================================================================
-- INSERT INTO workspaces (name, slug) VALUES ('Default Workspace', 'default')
-- ON CONFLICT (slug) DO NOTHING;
