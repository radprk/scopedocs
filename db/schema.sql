-- Schema for PostgreSQL representation of backend/models.py
-- Requires pgcrypto for UUID generation and optionally pgvector for embeddings.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- Uncomment if pgvector is installed
-- CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE work_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    team TEXT,
    assignee TEXT,
    project_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    labels TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE pull_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL,
    repo TEXT NOT NULL,
    files_changed TEXT[] NOT NULL DEFAULT '{}',
    work_item_refs TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    merged_at TIMESTAMPTZ,
    reviewers TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    messages JSONB NOT NULL DEFAULT '[]',
    participants TEXT[] NOT NULL DEFAULT '{}',
    decision_extracted TEXT,
    work_item_refs TEXT[] NOT NULL DEFAULT '{}',
    pr_refs TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE scopedocs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    sections JSONB NOT NULL,
    freshness_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    freshness_level TEXT NOT NULL,
    last_verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    evidence_links JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    path TEXT,
    repo TEXT,
    owners TEXT[] NOT NULL DEFAULT '{}',
    dependencies TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    email TEXT,
    team TEXT,
    github_username TEXT,
    slack_id TEXT
);

CREATE TABLE relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    source_type TEXT NOT NULL,
    target_id UUID NOT NULL,
    target_type TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    evidence TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT relationships_source_fk FOREIGN KEY (source_id) REFERENCES components(id) ON DELETE CASCADE,
    CONSTRAINT relationships_target_fk FOREIGN KEY (target_id) REFERENCES components(id) ON DELETE CASCADE
);

CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    -- If pgvector is not enabled, use: embedding DOUBLE PRECISION[]
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE drift_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    sections_affected TEXT[] NOT NULL DEFAULT '{}',
    trigger_event TEXT NOT NULL,
    trigger_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity TEXT NOT NULL DEFAULT 'medium'
);

CREATE TABLE artifact_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_type TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data JSONB NOT NULL,
    source TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX work_items_external_id_idx ON work_items (external_id);
CREATE INDEX work_items_project_id_idx ON work_items (project_id);
CREATE INDEX work_items_created_at_idx ON work_items (created_at);

CREATE INDEX pull_requests_external_id_idx ON pull_requests (external_id);
CREATE INDEX pull_requests_repo_idx ON pull_requests (repo);
CREATE INDEX pull_requests_created_at_idx ON pull_requests (created_at);
CREATE INDEX pull_requests_merged_at_idx ON pull_requests (merged_at);

CREATE INDEX conversations_external_id_idx ON conversations (external_id);
CREATE INDEX conversations_channel_idx ON conversations (channel);
CREATE INDEX conversations_created_at_idx ON conversations (created_at);

CREATE INDEX scopedocs_project_id_idx ON scopedocs (project_id);
CREATE INDEX scopedocs_created_at_idx ON scopedocs (created_at);

CREATE INDEX components_repo_idx ON components (repo);

CREATE INDEX people_external_id_idx ON people (external_id);

CREATE INDEX relationships_created_at_idx ON relationships (created_at);

CREATE INDEX embeddings_created_at_idx ON embeddings (created_at);

CREATE INDEX drift_alerts_created_at_idx ON drift_alerts (created_at);

CREATE INDEX artifact_events_created_at_idx ON artifact_events (event_time);
