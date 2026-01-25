"""
ScopeDocs MVP - Main FastAPI Application

Features:
- User authentication (via Supabase Auth JWT)
- OAuth connection for Linear, GitHub, Slack
- Data sync triggers
- Query API for context
"""
import os
import sys
import json
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
import uvicorn

# Security scheme for Swagger UI
security = HTTPBearer()

from .database import init_pool, close_pool, get_pool, run_migrations
from .oauth import get_authorize_url, exchange_code_for_token, get_user_info
from .sync import sync_linear, sync_github, sync_slack, create_links


# ============ APP SETUP ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup."""
    print("📡 Connecting to Supabase...")
    await init_pool()
    print("📝 Running migrations...")
    await run_migrations()
    print("✅ Ready!")
    yield
    await close_pool()


app = FastAPI(
    title="ScopeDocs",
    description="Connect your Linear, GitHub, and Slack to get full context on any ticket",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store OAuth states temporarily (in production, use Redis)
oauth_states = {}

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.environ.get("FRONTEND_URL", BASE_URL)  # Default to same origin


# ============ SIMPLE AUTH (for MVP) ============
# In production, validate Supabase JWT tokens

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UUID:
    """
    Get current user from Authorization header.
    For MVP: Pass user_id directly as Bearer token.
    For production: Validate Supabase JWT.
    """
    token = credentials.credentials

    # MVP: token is the user_id
    # Production: decode Supabase JWT and extract user_id
    try:
        return UUID(token)
    except:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_or_create_user(email: str, name: str = None) -> UUID:
    """Get or create a user by email."""
    async with get_pool().acquire() as conn:
        # Check if user exists
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if row:
            return row['id']

        # Create new user
        row = await conn.fetchrow(
            "INSERT INTO users (id, email, name) VALUES (gen_random_uuid(), $1, $2) RETURNING id",
            email, name
        )
        return row['id']


# ============ AUTH ENDPOINTS ============

@app.post("/auth/signup", tags=["Auth"])
async def signup(email: str, name: str = None):
    """
    Simple signup - creates a user and returns their ID.
    For MVP: Use this ID as Bearer token.
    For production: Use Supabase Auth.
    """
    user_id = await get_or_create_user(email, name)
    return {"user_id": str(user_id), "message": "Use this as Bearer token"}


@app.get("/auth/me", tags=["Auth"])
async def get_me(user_id: UUID = Depends(get_current_user)):
    """Get current user info."""
    async with get_pool().acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        integrations = await conn.fetch(
            "SELECT provider, workspace_info, created_at FROM user_integrations WHERE user_id = $1",
            user_id
        )

        return {
            "id": str(user['id']),
            "email": user['email'],
            "name": user['name'],
            "integrations": [
                {
                    "provider": i['provider'],
                    "workspace": i['workspace_info'],
                    "connected_at": str(i['created_at'])
                }
                for i in integrations
            ]
        }


# ============ OAUTH ENDPOINTS ============

@app.get("/oauth/{provider}/authorize", tags=["OAuth"])
async def oauth_authorize(provider: str, user_id: UUID = Depends(get_current_user)):
    """Start OAuth flow for a provider."""
    if provider not in ['linear', 'github', 'slack']:
        raise HTTPException(status_code=400, detail="Invalid provider")

    state = secrets.token_urlsafe(32)
    oauth_states[state] = {"user_id": str(user_id), "provider": provider}

    redirect_uri = f"{BASE_URL}/oauth/{provider}/callback"
    authorize_url = get_authorize_url(provider, redirect_uri, state)

    return {"authorize_url": authorize_url}


@app.get("/oauth/{provider}/callback", tags=["OAuth"])
async def oauth_callback(provider: str, code: str, state: str):
    """OAuth callback - exchange code for token."""
    print(f"[OAuth] Callback received for {provider}, state={state[:20]}...")

    if state not in oauth_states:
        print(f"[OAuth] ERROR: Invalid state. Known states: {list(oauth_states.keys())}")
        return RedirectResponse(f"{FRONTEND_URL}/?error=invalid_state")

    state_data = oauth_states.pop(state)
    user_id = UUID(state_data['user_id'])
    print(f"[OAuth] Processing for user {user_id}")

    redirect_uri = f"{BASE_URL}/oauth/{provider}/callback"

    try:
        # Exchange code for token
        print(f"[OAuth] Exchanging code for token...")
        token_data = await exchange_code_for_token(provider, code, redirect_uri)
        print(f"[OAuth] Token response keys: {token_data.keys() if isinstance(token_data, dict) else 'not a dict'}")

        access_token = token_data.get('access_token')
        if not access_token:
            raise Exception(f"No access token in response: {token_data}")

        # Get workspace info
        print(f"[OAuth] Getting workspace info...")
        workspace_info = await get_user_info(provider, access_token)
        print(f"[OAuth] Workspace info: {workspace_info}")

        # Store token
        print(f"[OAuth] Storing token in database...")
        async with get_pool().acquire() as conn:
            await conn.execute("""
                INSERT INTO user_integrations (user_id, provider, access_token, refresh_token, workspace_info)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (user_id, provider) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    workspace_info = EXCLUDED.workspace_info,
                    updated_at = NOW()
            """,
                user_id, provider, access_token,
                token_data.get('refresh_token'),
                json.dumps(workspace_info)
            )

        print(f"[OAuth] SUCCESS! Redirecting to frontend...")
        # Redirect to frontend
        return RedirectResponse(f"{FRONTEND_URL}/?connected={provider}")

    except Exception as e:
        print(f"[OAuth] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(f"{FRONTEND_URL}/?error={str(e)}")


# ============ SYNC ENDPOINTS ============

@app.post("/sync/{provider}", tags=["Sync"])
async def trigger_sync(
    provider: str,
    repos: str = Query(None, description="Comma-separated repos for GitHub"),
    channels: str = Query(None, description="Comma-separated channels for Slack"),
    user_id: UUID = Depends(get_current_user)
):
    """Trigger a data sync for a provider."""
    if provider not in ['linear', 'github', 'slack', 'all']:
        raise HTTPException(status_code=400, detail="Invalid provider")

    async with get_pool().acquire() as conn:
        # Get user's tokens
        integrations = await conn.fetch(
            "SELECT provider, access_token FROM user_integrations WHERE user_id = $1",
            user_id
        )
        tokens = {i['provider']: i['access_token'] for i in integrations}

        results = {}

        if provider in ['linear', 'all'] and 'linear' in tokens:
            count = await sync_linear(conn, user_id, tokens['linear'])
            results['linear_issues'] = count

        if provider in ['github', 'all'] and 'github' in tokens:
            repo_list = [r.strip() for r in (repos or "").split(",") if r.strip()]
            if not repo_list:
                results['github_error'] = "No repos specified. Use ?repos=org/repo1,org/repo2"
            else:
                count = await sync_github(conn, user_id, tokens['github'], repo_list)
                results['github_prs'] = count

        if provider in ['slack', 'all'] and 'slack' in tokens:
            channel_list = [c.strip() for c in (channels or "").split(",") if c.strip()]
            if not channel_list:
                results['slack_error'] = "No channels specified. Use ?channels=general,engineering"
            else:
                count = await sync_slack(conn, user_id, tokens['slack'], channel_list)
                results['slack_messages'] = count

        # Create links
        links = await create_links(conn, user_id)
        results['links_created'] = links

        return results


# ============ QUERY ENDPOINTS ============

@app.get("/stats", tags=["Query"])
async def get_stats(user_id: UUID = Depends(get_current_user)):
    """Get sync statistics for current user."""
    async with get_pool().acquire() as conn:
        stats = {
            "linear_issues": await conn.fetchval(
                "SELECT COUNT(*) FROM linear_issues WHERE user_id = $1", user_id
            ),
            "github_prs": await conn.fetchval(
                "SELECT COUNT(*) FROM github_prs WHERE user_id = $1", user_id
            ),
            "slack_messages": await conn.fetchval(
                "SELECT COUNT(*) FROM slack_messages WHERE user_id = $1", user_id
            ),
            "links": await conn.fetchval(
                "SELECT COUNT(*) FROM links WHERE user_id = $1", user_id
            ),
        }
        return stats


@app.get("/context/{issue_id}", tags=["Query"])
async def get_context(issue_id: str, user_id: UUID = Depends(get_current_user)):
    """
    Get full context for a Linear issue - THE MAIN VALUE!
    Returns the issue with all linked PRs and Slack discussions.
    """
    async with get_pool().acquire() as conn:
        # Get issue
        issue = await conn.fetchrow(
            "SELECT * FROM linear_issues WHERE identifier = $1 AND user_id = $2",
            issue_id, user_id
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

        # Get linked PRs
        prs = await conn.fetch("""
            SELECT DISTINCT p.repo, p.number, p.title, p.state, p.author, p.created_at, p.merged_at
            FROM github_prs p
            JOIN links l ON l.source_id = p.repo || '#' || p.number
            WHERE l.target_id = $1 AND l.target_type = 'linear_issue' AND l.user_id = $2
        """, issue_id, user_id)

        for pr in prs:
            result["prs"].append({
                "repo": pr["repo"],
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "author": pr["author"],
            })

        # Get linked Slack messages
        messages = await conn.fetch("""
            SELECT DISTINCT s.channel_name, s.message_text, s.user_id as slack_user, s.created_at
            FROM slack_messages s
            JOIN links l ON l.source_id = s.id
            WHERE l.target_id = $1 AND l.target_type = 'linear_issue' AND l.user_id = $2
        """, issue_id, user_id)

        for msg in messages:
            result["discussions"].append({
                "channel": msg["channel_name"],
                "text": msg["message_text"],
                "user": msg["slack_user"],
            })

        return result


@app.get("/issues", tags=["Query"])
async def list_issues(
    team: str = None,
    status: str = None,
    limit: int = Query(50, le=200),
    user_id: UUID = Depends(get_current_user)
):
    """List Linear issues for current user."""
    async with get_pool().acquire() as conn:
        query = "SELECT identifier, title, status, team_name, assignee_name FROM linear_issues WHERE user_id = $1"
        params = [user_id]

        if team:
            params.append(team)
            query += f" AND team_name = ${len(params)}"
        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"

        query += f" ORDER BY updated_at DESC LIMIT {limit}"
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


@app.get("/search", tags=["Query"])
async def search(q: str, user_id: UUID = Depends(get_current_user)):
    """Search across all data sources."""
    async with get_pool().acquire() as conn:
        results = {"issues": [], "prs": [], "messages": []}

        issues = await conn.fetch("""
            SELECT identifier, title, status FROM linear_issues
            WHERE user_id = $1 AND (title ILIKE $2 OR description ILIKE $2)
            LIMIT 20
        """, user_id, f"%{q}%")
        results["issues"] = [dict(r) for r in issues]

        prs = await conn.fetch("""
            SELECT repo, number, title, state FROM github_prs
            WHERE user_id = $1 AND (title ILIKE $2 OR body ILIKE $2)
            LIMIT 20
        """, user_id, f"%{q}%")
        results["prs"] = [dict(r) for r in prs]

        messages = await conn.fetch("""
            SELECT id, channel_name, message_text FROM slack_messages
            WHERE user_id = $1 AND message_text ILIKE $2
            LIMIT 20
        """, user_id, f"%{q}%")
        results["messages"] = [dict(r) for r in messages]

        return results


# ============ HEALTH CHECK ============

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ============ FRONTEND ============

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_frontend():
    """Serve the frontend."""
    static_path = Path(__file__).parent / "static" / "index.html"
    if static_path.exists():
        return FileResponse(static_path)
    return HTMLResponse("<h1>ScopeDocs API</h1><p>Go to <a href='/docs'>/docs</a> for API documentation.</p>")


# ============ RUN ============

if __name__ == '__main__':
    print("")
    print("🚀 Starting ScopeDocs...")
    print("   Frontend: http://localhost:8000")
    print("   API docs: http://localhost:8000/docs")
    print("")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
