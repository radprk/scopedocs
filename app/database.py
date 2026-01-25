"""
Database setup with multi-tenant support.
Each user has their own data isolated by user_id.
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


# Multi-tenant schema
SCHEMA_V2 = """
-- Users table (synced with Supabase Auth)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,  -- Same as Supabase Auth user id
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- OAuth tokens per user
CREATE TABLE IF NOT EXISTS user_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,  -- 'linear', 'github', 'slack'
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    workspace_info JSONB,  -- Store org name, workspace id, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, provider)
);

-- Linear issues (multi-tenant with user_id)
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
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_linear_issues_user ON linear_issues(user_id);
CREATE INDEX IF NOT EXISTS idx_linear_issues_identifier ON linear_issues(identifier);

-- GitHub PRs (multi-tenant with user_id)
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
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_github_prs_user ON github_prs(user_id);
CREATE INDEX IF NOT EXISTS idx_github_prs_repo ON github_prs(repo);

-- Slack messages (multi-tenant with user_id)
CREATE TABLE IF NOT EXISTS slack_messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    thread_ts TEXT,
    message_text TEXT,
    user_name TEXT,
    created_at TIMESTAMP WITH TIME ZONE,
    raw_data JSONB,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_slack_messages_user ON slack_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_slack_messages_channel ON slack_messages(channel_id);

-- Links between artifacts (multi-tenant with user_id)
CREATE TABLE IF NOT EXISTS links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,  -- 'github_pr', 'slack_message'
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,  -- 'linear_issue'
    target_id TEXT NOT NULL,
    link_type TEXT,  -- 'implements', 'discusses'
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(source_type, source_id, target_type, target_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_links_user ON links(user_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_type, target_id);

-- Sync jobs tracking
CREATE TABLE IF NOT EXISTS sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    items_synced INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sync_jobs_user ON sync_jobs(user_id);
"""


async def run_migrations():
    """Run database migrations."""
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_V2)
