-- AI Layer Schema for ScopeDocs
-- Enables pgvector for semantic search
-- Uses 1024 dimensions for BAAI/bge-large-en-v1.5

CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- Code Embeddings (SOC 2 compliant: stores embeddings + pointers, not raw code)
-- =============================================================================
CREATE TABLE IF NOT EXISTS code_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repo_full_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    commit_sha TEXT NOT NULL,              -- Pointer to fetch actual code
    chunk_index INT NOT NULL,
    start_line INT NOT NULL,
    end_line INT NOT NULL,
    content_hash TEXT NOT NULL,            -- SHA256 of content, for change detection
    embedding vector(1024),                -- BGE-large embeddings
    symbol_names TEXT[],                   -- Function/class names in this chunk
    language TEXT,                         -- Detected programming language
    metadata JSONB DEFAULT '{}',           -- Additional metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, repo_full_name, file_path, chunk_index)
);

-- Indexes for fast similarity search
CREATE INDEX IF NOT EXISTS code_embeddings_workspace_idx ON code_embeddings(workspace_id);
CREATE INDEX IF NOT EXISTS code_embeddings_repo_idx ON code_embeddings(repo_full_name);
CREATE INDEX IF NOT EXISTS code_embeddings_file_idx ON code_embeddings(file_path);
CREATE INDEX IF NOT EXISTS code_embeddings_content_hash_idx ON code_embeddings(content_hash);

-- HNSW index for fast vector search (recommended for pgvector)
CREATE INDEX IF NOT EXISTS code_embeddings_vector_idx ON code_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- =============================================================================
-- Generated Documentation (we own this content, safe to store)
-- =============================================================================
CREATE TABLE IF NOT EXISTS generated_docs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repo_full_name TEXT NOT NULL,
    file_path TEXT,                        -- NULL for repo-level docs
    doc_type TEXT NOT NULL,                -- 'overview', 'module', 'function', 'file'
    title TEXT NOT NULL,
    content TEXT NOT NULL,                 -- The generated markdown
    embedding vector(1024),
    source_chunks UUID[],                  -- Which code_embeddings this came from
    source_commit_sha TEXT,                -- Commit SHA when doc was generated
    version INT NOT NULL DEFAULT 1,
    is_stale BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, repo_full_name, file_path, doc_type)
);

CREATE INDEX IF NOT EXISTS generated_docs_workspace_idx ON generated_docs(workspace_id);
CREATE INDEX IF NOT EXISTS generated_docs_repo_idx ON generated_docs(repo_full_name);
CREATE INDEX IF NOT EXISTS generated_docs_stale_idx ON generated_docs(is_stale) WHERE is_stale = TRUE;

CREATE INDEX IF NOT EXISTS generated_docs_vector_idx ON generated_docs
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- =============================================================================
-- Doc-to-Code Links (maps documentation sections to code lines)
-- =============================================================================
CREATE TABLE IF NOT EXISTS doc_code_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    doc_id UUID NOT NULL REFERENCES generated_docs(id) ON DELETE CASCADE,
    doc_section TEXT,                      -- Section within the doc (e.g., "## Overview")
    doc_line_start INT,                    -- Line in the doc
    doc_line_end INT,
    code_embedding_id UUID REFERENCES code_embeddings(id) ON DELETE CASCADE,
    repo_full_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    code_line_start INT NOT NULL,
    code_line_end INT NOT NULL,
    link_type TEXT NOT NULL,               -- 'explains', 'references', 'example_of'
    confidence FLOAT NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS doc_code_links_doc_idx ON doc_code_links(doc_id);
CREATE INDEX IF NOT EXISTS doc_code_links_code_idx ON doc_code_links(code_embedding_id);


-- =============================================================================
-- Message Embeddings (Slack/Linear - stores embeddings + IDs, not full content)
-- =============================================================================
CREATE TABLE IF NOT EXISTS message_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source TEXT NOT NULL,                  -- 'slack', 'linear'
    external_id TEXT NOT NULL,             -- Slack message ts, Linear issue ID
    channel_or_project TEXT,               -- Channel name or project name
    summary TEXT,                          -- AI-generated summary (safe to store)
    embedding vector(1024),
    linked_code_chunks UUID[],             -- References to code_embeddings
    linked_prs TEXT[],                     -- PR external IDs
    linked_issues TEXT[],                  -- Linear issue external IDs
    message_type TEXT,                     -- 'decision', 'question', 'update', 'discussion'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, source, external_id)
);

CREATE INDEX IF NOT EXISTS message_embeddings_workspace_idx ON message_embeddings(workspace_id);
CREATE INDEX IF NOT EXISTS message_embeddings_source_idx ON message_embeddings(source);

CREATE INDEX IF NOT EXISTS message_embeddings_vector_idx ON message_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- =============================================================================
-- Traceability Links (connects Linear issues <-> PRs <-> Code)
-- =============================================================================
CREATE TABLE IF NOT EXISTS traceability_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,

    -- Source artifact
    source_type TEXT NOT NULL,             -- 'linear_issue', 'github_pr', 'slack_message', 'code_file'
    source_external_id TEXT NOT NULL,
    source_title TEXT,

    -- Target artifact
    target_type TEXT NOT NULL,
    target_external_id TEXT NOT NULL,
    target_title TEXT,

    -- Link metadata
    link_type TEXT NOT NULL,               -- 'implements', 'discusses', 'mentions', 'modifies'
    confidence FLOAT NOT NULL DEFAULT 1.0,
    evidence TEXT,                         -- How we detected this link

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, source_type, source_external_id, target_type, target_external_id)
);

CREATE INDEX IF NOT EXISTS traceability_workspace_idx ON traceability_links(workspace_id);
CREATE INDEX IF NOT EXISTS traceability_source_idx ON traceability_links(source_type, source_external_id);
CREATE INDEX IF NOT EXISTS traceability_target_idx ON traceability_links(target_type, target_external_id);


-- =============================================================================
-- Chat History (for conversational Q&A)
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repo_full_name TEXT,                   -- Optional: scoped to a repo
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                    -- 'user', 'assistant'
    content TEXT NOT NULL,
    sources JSONB DEFAULT '[]',            -- Retrieved sources for this response
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS chat_messages_session_idx ON chat_messages(session_id);


-- =============================================================================
-- Embedding Jobs (track embedding generation progress)
-- =============================================================================
CREATE TABLE IF NOT EXISTS embedding_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,                -- 'code_index', 'doc_generate', 'message_embed'
    repo_full_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed'
    total_items INT,
    processed_items INT DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS embedding_jobs_workspace_idx ON embedding_jobs(workspace_id);
CREATE INDEX IF NOT EXISTS embedding_jobs_status_idx ON embedding_jobs(status);
