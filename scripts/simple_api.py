#!/usr/bin/env python3
"""
Simple API to view ingested data.
Run: python scripts/simple_api.py
Then open: http://localhost:8000/docs
"""
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import uvicorn

# Database pool
pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup database connection."""
    global pool
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')
    if not dsn:
        print("❌ ERROR: POSTGRES_DSN not set!")
        sys.exit(1)

    print("📡 Connecting to Supabase...")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    print("✅ Connected!")
    yield
    await pool.close()


app = FastAPI(
    title="ScopeDocs MVP API",
    description="Simple API to view ingested Linear, GitHub, and Slack data",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ STATS ============

@app.get("/stats", tags=["Overview"])
async def get_stats():
    """Get overview statistics of all ingested data."""
    async with pool.acquire() as conn:
        stats = {}

        # Count Linear issues
        stats["linear_issues"] = await conn.fetchval("SELECT COUNT(*) FROM linear_issues")

        # Count GitHub PRs
        stats["github_prs"] = await conn.fetchval("SELECT COUNT(*) FROM github_prs")

        # Count Slack messages
        stats["slack_messages"] = await conn.fetchval("SELECT COUNT(*) FROM slack_messages")

        # Count links
        stats["links"] = await conn.fetchval("SELECT COUNT(*) FROM links")

        # Get recent syncs
        recent = await conn.fetchrow("""
            SELECT
                (SELECT MAX(synced_at) FROM linear_issues) as linear_last_sync,
                (SELECT MAX(synced_at) FROM github_prs) as github_last_sync,
                (SELECT MAX(synced_at) FROM slack_messages) as slack_last_sync
        """)

        stats["last_syncs"] = {
            "linear": str(recent["linear_last_sync"]) if recent["linear_last_sync"] else None,
            "github": str(recent["github_last_sync"]) if recent["github_last_sync"] else None,
            "slack": str(recent["slack_last_sync"]) if recent["slack_last_sync"] else None,
        }

        return stats


# ============ LINEAR ISSUES ============

@app.get("/linear/issues", tags=["Linear"])
async def list_linear_issues(
    team: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    """List Linear issues with optional filters."""
    async with pool.acquire() as conn:
        query = "SELECT id, identifier, title, status, team_name, assignee_name, created_at FROM linear_issues WHERE 1=1"
        params = []

        if team:
            params.append(team)
            query += f" AND team_name = ${len(params)}"
        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"

        query += f" ORDER BY updated_at DESC LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


@app.get("/linear/issues/{identifier}", tags=["Linear"])
async def get_linear_issue(identifier: str):
    """Get a single Linear issue with all its linked items."""
    async with pool.acquire() as conn:
        # Get issue
        issue = await conn.fetchrow(
            "SELECT * FROM linear_issues WHERE identifier = $1",
            identifier
        )
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

        result = dict(issue)
        result.pop("raw_data", None)  # Remove raw data for cleaner response

        # Get linked PRs
        pr_links = await conn.fetch("""
            SELECT l.*, p.title as pr_title, p.state as pr_state, p.repo
            FROM links l
            LEFT JOIN github_prs p ON p.id = l.source_id OR (p.repo || '#' || p.number) = l.source_id
            WHERE l.target_type = 'linear_issue' AND l.target_id = $1
            AND l.source_type = 'github_pr'
        """, identifier)

        result["linked_prs"] = [dict(r) for r in pr_links]

        # Get linked Slack messages
        slack_links = await conn.fetch("""
            SELECT l.*, s.message_text, s.channel_name, s.user_name
            FROM links l
            LEFT JOIN slack_messages s ON s.id = l.source_id
            WHERE l.target_type = 'linear_issue' AND l.target_id = $1
            AND l.source_type = 'slack_message'
        """, identifier)

        result["linked_slack"] = [dict(r) for r in slack_links]

        return result


@app.get("/linear/teams", tags=["Linear"])
async def list_linear_teams():
    """List all teams with issue counts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT team_name, COUNT(*) as issue_count
            FROM linear_issues
            WHERE team_name IS NOT NULL
            GROUP BY team_name
            ORDER BY issue_count DESC
        """)
        return [dict(r) for r in rows]


# ============ GITHUB PRS ============

@app.get("/github/prs", tags=["GitHub"])
async def list_github_prs(
    repo: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    """List GitHub PRs with optional filters."""
    async with pool.acquire() as conn:
        query = "SELECT id, number, repo, title, state, author, created_at, merged_at FROM github_prs WHERE 1=1"
        params = []

        if repo:
            params.append(repo)
            query += f" AND repo = ${len(params)}"
        if state:
            params.append(state)
            query += f" AND state = ${len(params)}"

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


@app.get("/github/prs/{repo}/{number}", tags=["GitHub"])
async def get_github_pr(repo: str, number: int):
    """Get a single GitHub PR with linked items."""
    async with pool.acquire() as conn:
        pr = await conn.fetchrow(
            "SELECT * FROM github_prs WHERE repo = $1 AND number = $2",
            repo, number
        )
        if not pr:
            raise HTTPException(status_code=404, detail="PR not found")

        result = dict(pr)
        result.pop("raw_data", None)

        # Get linked Linear issues
        pr_id = f"{repo}#{number}"
        issue_links = await conn.fetch("""
            SELECT l.*, i.title as issue_title, i.status as issue_status
            FROM links l
            LEFT JOIN linear_issues i ON i.identifier = l.target_id
            WHERE l.source_type = 'github_pr' AND l.source_id = $1
            AND l.target_type = 'linear_issue'
        """, pr_id)

        result["linked_issues"] = [dict(r) for r in issue_links]

        return result


@app.get("/github/repos", tags=["GitHub"])
async def list_github_repos():
    """List all repos with PR counts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT repo, COUNT(*) as pr_count,
                   SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count
            FROM github_prs
            GROUP BY repo
            ORDER BY pr_count DESC
        """)
        return [dict(r) for r in rows]


# ============ SLACK MESSAGES ============

@app.get("/slack/messages", tags=["Slack"])
async def list_slack_messages(
    channel: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    """List Slack messages with optional channel filter."""
    async with pool.acquire() as conn:
        query = """
            SELECT id, channel_name, message_text, user_name, reply_count, created_at
            FROM slack_messages WHERE 1=1
        """
        params = []

        if channel:
            params.append(channel)
            query += f" AND channel_name = ${len(params)}"

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


@app.get("/slack/messages/{message_id}", tags=["Slack"])
async def get_slack_message(message_id: str):
    """Get a single Slack message with linked items."""
    async with pool.acquire() as conn:
        msg = await conn.fetchrow(
            "SELECT * FROM slack_messages WHERE id = $1",
            message_id
        )
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")

        result = dict(msg)
        result.pop("raw_data", None)

        # Get linked items
        links = await conn.fetch("""
            SELECT * FROM links
            WHERE source_type = 'slack_message' AND source_id = $1
        """, message_id)

        result["links"] = [dict(r) for r in links]

        return result


@app.get("/slack/channels", tags=["Slack"])
async def list_slack_channels():
    """List all channels with message counts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT channel_name, COUNT(*) as message_count
            FROM slack_messages
            WHERE channel_name IS NOT NULL
            GROUP BY channel_name
            ORDER BY message_count DESC
        """)
        return [dict(r) for r in rows]


# ============ LINKS / CONTEXT ============

@app.get("/context/{issue_id}", tags=["Context"])
async def get_full_context(issue_id: str):
    """
    Get FULL context for a Linear issue - the main value of ScopeDocs!
    Returns the issue with all linked PRs and Slack discussions.
    """
    async with pool.acquire() as conn:
        # Get the issue
        issue = await conn.fetchrow(
            "SELECT * FROM linear_issues WHERE identifier = $1",
            issue_id
        )
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

        result = {
            "issue": {
                "identifier": issue["identifier"],
                "title": issue["title"],
                "description": issue["description"],
                "status": issue["status"],
                "team": issue["team_name"],
                "assignee": issue["assignee_name"],
            },
            "prs": [],
            "discussions": [],
        }

        # Get all PRs that mention this issue
        prs = await conn.fetch("""
            SELECT DISTINCT p.*
            FROM github_prs p
            JOIN links l ON (l.source_id = p.repo || '#' || p.number OR l.source_id = p.id)
            WHERE l.target_id = $1 AND l.target_type = 'linear_issue'
        """, issue_id)

        for pr in prs:
            result["prs"].append({
                "repo": pr["repo"],
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "author": pr["author"],
                "files_changed": pr["files_changed"],
                "created_at": str(pr["created_at"]) if pr["created_at"] else None,
                "merged_at": str(pr["merged_at"]) if pr["merged_at"] else None,
            })

        # Get all Slack discussions about this issue
        messages = await conn.fetch("""
            SELECT DISTINCT s.*
            FROM slack_messages s
            JOIN links l ON l.source_id = s.id
            WHERE l.target_id = $1 AND l.target_type = 'linear_issue'
        """, issue_id)

        for msg in messages:
            result["discussions"].append({
                "channel": msg["channel_name"],
                "user": msg["user_name"],
                "text": msg["message_text"],
                "reply_count": msg["reply_count"],
                "participants": msg["participants"],
                "created_at": str(msg["created_at"]) if msg["created_at"] else None,
            })

        return result


@app.get("/search", tags=["Search"])
async def search_all(q: str, limit: int = Query(20, le=100)):
    """Search across all data sources."""
    async with pool.acquire() as conn:
        results = {"issues": [], "prs": [], "messages": []}

        # Search Linear issues
        issues = await conn.fetch("""
            SELECT identifier, title, status, team_name
            FROM linear_issues
            WHERE title ILIKE $1 OR description ILIKE $1 OR identifier ILIKE $1
            LIMIT $2
        """, f"%{q}%", limit)
        results["issues"] = [dict(r) for r in issues]

        # Search GitHub PRs
        prs = await conn.fetch("""
            SELECT repo, number, title, state
            FROM github_prs
            WHERE title ILIKE $1 OR body ILIKE $1
            LIMIT $2
        """, f"%{q}%", limit)
        results["prs"] = [dict(r) for r in prs]

        # Search Slack messages
        messages = await conn.fetch("""
            SELECT id, channel_name, message_text, user_name
            FROM slack_messages
            WHERE message_text ILIKE $1
            LIMIT $2
        """, f"%{q}%", limit)
        results["messages"] = [dict(r) for r in messages]

        return results


if __name__ == '__main__':
    print("")
    print("🚀 Starting ScopeDocs MVP API...")
    print("   Open http://localhost:8000/docs for Swagger UI")
    print("")
    uvicorn.run(app, host="0.0.0.0", port=8000)
