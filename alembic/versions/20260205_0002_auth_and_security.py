"""Add auth, security, and job queue tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        -- Workspaces
        CREATE TABLE IF NOT EXISTS workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            github_org_id TEXT,
            slack_team_id TEXT,
            linear_org_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        -- OAuth state storage (database-backed)
        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at FLOAT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);
        
        -- Users for authentication
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        
        -- User-workspace memberships
        CREATE TABLE IF NOT EXISTS workspace_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'member',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, workspace_id)
        );
        
        -- Async job queue
        CREATE TABLE IF NOT EXISTS jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_type TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result JSONB,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status) WHERE status = 'pending';
        
        -- Code indexing tables
        CREATE TABLE IF NOT EXISTS file_path_lookup (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            repo_id UUID NOT NULL,
            file_path_hash TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_content_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (repo_id, file_path_hash)
        );
        
        CREATE TABLE IF NOT EXISTS code_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            repo_id UUID NOT NULL,
            file_path_hash TEXT NOT NULL,
            chunk_hash TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            embedding vector(768),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (repo_id, file_path_hash, chunk_index)
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS code_chunks;
        DROP TABLE IF EXISTS file_path_lookup;
        DROP TABLE IF EXISTS jobs;
        DROP TABLE IF EXISTS workspace_members;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS oauth_states;
        DROP TABLE IF EXISTS workspaces;
    """)
