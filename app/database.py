"""
Database setup with workspace-based multi-tenancy.
Data is scoped to workspaces, not individual users.
Users can be members of multiple workspaces.
"""
import os
import re
from contextlib import asynccontextmanager
import asyncpg

# Global connection pool
pool: asyncpg.Pool = None


def parse_supabase_dsn(dsn: str) -> dict:
    """Parse Supabase DSN into components."""
    pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
    match = re.match(pattern, dsn)
    if not match:
        raise ValueError(f"Invalid DSN format: {dsn}")
    return {
        'user': match.group(1),
        'password': match.group(2),
        'host': match.group(3),
        'port': int(match.group(4)),
        'database': match.group(5),
    }


async def init_pool():
    """Initialize the database connection pool."""
    global pool
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')
    if not dsn:
        raise ValueError("POSTGRES_DSN not set")

    db_config = parse_supabase_dsn(dsn)
    pool = await asyncpg.create_pool(**db_config, min_size=2, max_size=10)
    return pool


async def close_pool():
    """Close the database connection pool."""
    global pool
    if pool:
        await pool.close()


def get_pool():
    """Get the database pool."""
    return pool


async def get_connection():
    """Get a connection from the pool."""
    return pool.acquire()


# Workspace-based multi-tenant schema
SCHEMA_V3 = """
-- Users table (synced with Supabase Auth)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,  -- Same as Supabase Auth user id
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Workspaces (the core tenant entity)
CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Workspace membership
CREATE TABLE IF NOT EXISTS workspace_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',  -- 'owner', 'admin', 'member'
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members(user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace ON workspace_members(workspace_id);

-- Workspace invites (for invite links)
CREATE TABLE IF NOT EXISTS workspace_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    code TEXT UNIQUE NOT NULL,  -- The invite code/token
    created_by UUID REFERENCES users(id),
    expires_at TIMESTAMP WITH TIME ZONE,
    max_uses INTEGER,
    use_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workspace_invites_code ON workspace_invites(code);

-- OAuth tokens per workspace (not per user)
CREATE TABLE IF NOT EXISTS workspace_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,  -- 'linear', 'github', 'slack'
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    provider_info JSONB,  -- Store org name, workspace id from provider, etc.
    connected_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(workspace_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_workspace_integrations_workspace ON workspace_integrations(workspace_id);

-- Linear issues (scoped to workspace)
CREATE TABLE IF NOT EXISTS linear_issues (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL,
    title TEXT,
    description TEXT,
    status TEXT,
    priority TEXT,
    assignee_name TEXT,
    team_name TEXT,
    project_name TEXT,
    labels TEXT[],
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    raw_data JSONB,
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_linear_issues_workspace ON linear_issues(workspace_id);
CREATE INDEX IF NOT EXISTS idx_linear_issues_identifier ON linear_issues(identifier);

-- GitHub PRs (scoped to workspace)
CREATE TABLE IF NOT EXISTS github_prs (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    title TEXT,
    body TEXT,
    state TEXT,
    author TEXT,
    created_at TIMESTAMP WITH TIME ZONE,
    merged_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    raw_data JSONB,
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_github_prs_workspace ON github_prs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_github_prs_repo ON github_prs(repo);

-- Slack messages (scoped to workspace)
CREATE TABLE IF NOT EXISTS slack_messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    thread_ts TEXT,
    message_text TEXT,
    user_name TEXT,
    created_at TIMESTAMP WITH TIME ZONE,
    raw_data JSONB,
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_slack_messages_workspace ON slack_messages(workspace_id);
CREATE INDEX IF NOT EXISTS idx_slack_messages_channel ON slack_messages(channel_id);

-- Links between artifacts (scoped to workspace)
CREATE TABLE IF NOT EXISTS links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,  -- 'github_pr', 'slack_message'
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,  -- 'linear_issue'
    target_id TEXT NOT NULL,
    link_type TEXT,  -- 'implements', 'discusses'
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(source_type, source_id, target_type, target_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_links_workspace ON links(workspace_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_type, target_id);

-- Sync jobs tracking (scoped to workspace)
CREATE TABLE IF NOT EXISTS sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    triggered_by UUID REFERENCES users(id),
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    items_synced INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sync_jobs_workspace ON sync_jobs(workspace_id);

-- Keep old user_integrations for migration (will be removed later)
CREATE TABLE IF NOT EXISTS user_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    workspace_info JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, provider)
);
"""


async def run_migrations():
    """Run database migrations."""
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_V3)
