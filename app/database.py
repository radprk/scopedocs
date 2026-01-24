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

-- Add user_id to existing tables (if not exists)
DO $$
BEGIN
    -- Linear issues
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='linear_issues' AND column_name='user_id') THEN
        ALTER TABLE linear_issues ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;
        CREATE INDEX idx_linear_issues_user ON linear_issues(user_id);
    END IF;

    -- GitHub PRs
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='github_prs' AND column_name='user_id') THEN
        ALTER TABLE github_prs ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;
        CREATE INDEX idx_github_prs_user ON github_prs(user_id);
    END IF;

    -- Slack messages
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='slack_messages' AND column_name='user_id') THEN
        ALTER TABLE slack_messages ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;
        CREATE INDEX idx_slack_messages_user ON slack_messages(user_id);
    END IF;

    -- Links
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='links' AND column_name='user_id') THEN
        ALTER TABLE links ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;
        CREATE INDEX idx_links_user ON links(user_id);
    END IF;
END $$;

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
