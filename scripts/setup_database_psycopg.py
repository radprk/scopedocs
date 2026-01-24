#!/usr/bin/env python3
"""
Setup Supabase database tables for ScopeDocs MVP.
Uses psycopg2 (more compatible with Supabase pooler than asyncpg).

Run once: python scripts/setup_database_psycopg.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

import psycopg2

# Simple, clean schema for MVP
SCHEMA = """
-- Drop existing tables (clean slate for MVP)
DROP TABLE IF EXISTS links CASCADE;
DROP TABLE IF EXISTS slack_messages CASCADE;
DROP TABLE IF EXISTS github_prs CASCADE;
DROP TABLE IF EXISTS linear_issues CASCADE;

-- Linear Issues (tickets)
CREATE TABLE linear_issues (
    id TEXT PRIMARY KEY,
    identifier TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
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
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- GitHub Pull Requests
CREATE TABLE github_prs (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    state TEXT,
    author TEXT,
    reviewers TEXT[],
    labels TEXT[],
    files_changed TEXT[],
    additions INTEGER,
    deletions INTEGER,
    created_at TIMESTAMP WITH TIME ZONE,
    merged_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    raw_data JSONB,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(repo, number)
);

-- Slack Messages
CREATE TABLE slack_messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    thread_ts TEXT NOT NULL,
    message_text TEXT,
    user_id TEXT,
    user_name TEXT,
    reply_count INTEGER DEFAULT 0,
    participants TEXT[],
    thread_messages JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    raw_data JSONB,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(channel_id, thread_ts)
);

-- Links between artifacts
CREATE TABLE links (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    context TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(source_type, source_id, target_type, target_id, link_type)
);

-- Indexes
CREATE INDEX idx_linear_issues_identifier ON linear_issues(identifier);
CREATE INDEX idx_linear_issues_team ON linear_issues(team_name);
CREATE INDEX idx_github_prs_repo ON github_prs(repo);
CREATE INDEX idx_slack_messages_channel ON slack_messages(channel_id);
CREATE INDEX idx_links_source ON links(source_type, source_id);
CREATE INDEX idx_links_target ON links(target_type, target_id);
"""


def setup_database():
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')

    if not dsn:
        print("❌ ERROR: POSTGRES_DSN not set!")
        print("   Create backend/.env with your Supabase connection string")
        return False

    print("🔧 Setting up ScopeDocs database...")
    print("")

    try:
        print("📡 Connecting to Supabase...")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cursor = conn.cursor()

        print("📝 Creating tables...")
        cursor.execute(SCHEMA)

        print("✅ Database setup complete!")
        print("")
        print("Tables created:")
        print("   • linear_issues  - Store Linear tickets")
        print("   • github_prs     - Store GitHub PRs")
        print("   • slack_messages - Store Slack threads")
        print("   • links          - Connections between artifacts")
        print("")
        print("Next steps:")
        print("   1. Get your Linear API key")
        print("   2. Run: python scripts/pull_linear.py")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = setup_database()
    sys.exit(0 if success else 1)
