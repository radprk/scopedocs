"""
ScopeDocs MVP - Main FastAPI Application

Features:
- Workspace-based multi-tenancy (data scoped to workspaces, not users)
- User authentication (via Supabase Auth JWT)
- OAuth connection for Linear, GitHub, Slack (at workspace level)
- Invite links for workspace membership
- Data sync triggers
- Query API for context
"""
import os
import sys
import json
import secrets
from pathlib import Path
from datetime import datetime, timedelta
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
import httpx
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

def get_redirect_uri(provider: str) -> str:
    """Get the OAuth redirect URI for a provider.
    Allows per-provider overrides (e.g. Slack needs HTTPS via ngrok).
    Config priority: SLACK_REDIRECT_URL > BASE_URL
    """
    env_key = f"{provider.upper()}_REDIRECT_URL"
    override = os.environ.get(env_key)
    if override:
        return override
    return f"{BASE_URL}/oauth/{provider}/callback"


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


async def get_user_workspaces(user_id: UUID) -> list:
    """Get all workspaces a user is a member of."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.id, w.name, wm.role, w.created_at
            FROM workspaces w
            JOIN workspace_members wm ON w.id = wm.workspace_id
            WHERE wm.user_id = $1
            ORDER BY w.created_at DESC
        """, user_id)
        return [dict(r) for r in rows]


async def verify_workspace_access(user_id: UUID, workspace_id: UUID) -> dict:
    """Verify user has access to workspace, return membership info."""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("""
            SELECT wm.role, w.name as workspace_name
            FROM workspace_members wm
            JOIN workspaces w ON w.id = wm.workspace_id
            WHERE wm.user_id = $1 AND wm.workspace_id = $2
        """, user_id, workspace_id)
        if not row:
            raise HTTPException(status_code=403, detail="Not a member of this workspace")
        return dict(row)


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


# ============ WORKSPACE ENDPOINTS ============

@app.post("/workspaces", tags=["Workspaces"])
async def create_workspace(name: str, user_id: UUID = Depends(get_current_user)):
    """Create a new workspace. Creator becomes owner."""
    async with get_pool().acquire() as conn:
        # Create workspace
        row = await conn.fetchrow(
            "INSERT INTO workspaces (name, created_by) VALUES ($1, $2) RETURNING id",
            name, user_id
        )
        workspace_id = row['id']

        # Add creator as owner
        await conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
            workspace_id, user_id
        )

        return {"workspace_id": str(workspace_id), "name": name, "role": "owner"}


@app.get("/workspaces", tags=["Workspaces"])
async def list_workspaces(user_id: UUID = Depends(get_current_user)):
    """List all workspaces the user is a member of."""
    workspaces = await get_user_workspaces(user_id)
    return {
        "workspaces": [
            {"id": str(w['id']), "name": w['name'], "role": w['role']}
            for w in workspaces
        ]
    }


@app.get("/workspaces/{workspace_id}", tags=["Workspaces"])
async def get_workspace(workspace_id: UUID, user_id: UUID = Depends(get_current_user)):
    """Get workspace details including integrations."""
    await verify_workspace_access(user_id, workspace_id)

    async with get_pool().acquire() as conn:
        workspace = await conn.fetchrow(
            "SELECT id, name, created_at FROM workspaces WHERE id = $1",
            workspace_id
        )

        members = await conn.fetch("""
            SELECT u.id, u.email, u.name, wm.role, wm.joined_at
            FROM workspace_members wm
            JOIN users u ON u.id = wm.user_id
            WHERE wm.workspace_id = $1
        """, workspace_id)

        integrations = await conn.fetch(
            "SELECT provider, provider_info, created_at FROM workspace_integrations WHERE workspace_id = $1",
            workspace_id
        )

        return {
            "id": str(workspace['id']),
            "name": workspace['name'],
            "members": [
                {"id": str(m['id']), "email": m['email'], "name": m['name'], "role": m['role']}
                for m in members
            ],
            "integrations": [
                {"provider": i['provider'], "info": json.loads(i['provider_info']) if i['provider_info'] else None}
                for i in integrations
            ]
        }


# ============ INVITE ENDPOINTS ============

@app.post("/workspaces/{workspace_id}/invites", tags=["Invites"])
async def create_invite(
    workspace_id: UUID,
    expires_hours: int = Query(72, description="Hours until invite expires"),
    max_uses: int = Query(None, description="Max number of uses (null=unlimited)"),
    user_id: UUID = Depends(get_current_user)
):
    """Create an invite link for a workspace. Only owners/admins can create invites."""
    membership = await verify_workspace_access(user_id, workspace_id)
    if membership['role'] not in ['owner', 'admin']:
        raise HTTPException(status_code=403, detail="Only owners and admins can create invites")

    code = secrets.token_urlsafe(16)
    expires_at = datetime.now() + timedelta(hours=expires_hours) if expires_hours else None

    async with get_pool().acquire() as conn:
        await conn.execute("""
            INSERT INTO workspace_invites (workspace_id, code, created_by, expires_at, max_uses)
            VALUES ($1, $2, $3, $4, $5)
        """, workspace_id, code, user_id, expires_at, max_uses)

    invite_url = f"{FRONTEND_URL}/invite/{code}"
    return {"code": code, "url": invite_url, "expires_at": str(expires_at) if expires_at else None}


@app.post("/invites/{code}/redeem", tags=["Invites"])
async def redeem_invite(code: str, user_id: UUID = Depends(get_current_user)):
    """Redeem an invite code to join a workspace."""
    async with get_pool().acquire() as conn:
        # Get invite
        invite = await conn.fetchrow("""
            SELECT wi.*, w.name as workspace_name
            FROM workspace_invites wi
            JOIN workspaces w ON w.id = wi.workspace_id
            WHERE wi.code = $1
        """, code)

        if not invite:
            raise HTTPException(status_code=404, detail="Invalid invite code")

        # Check expiration
        if invite['expires_at'] and invite['expires_at'] < datetime.now():
            raise HTTPException(status_code=400, detail="Invite has expired")

        # Check max uses
        if invite['max_uses'] and invite['use_count'] >= invite['max_uses']:
            raise HTTPException(status_code=400, detail="Invite has reached max uses")

        # Check if already a member
        existing = await conn.fetchrow(
            "SELECT 1 FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
            invite['workspace_id'], user_id
        )
        if existing:
            return {"message": "Already a member", "workspace_id": str(invite['workspace_id'])}

        # Add as member
        await conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'member')",
            invite['workspace_id'], user_id
        )

        # Increment use count
        await conn.execute(
            "UPDATE workspace_invites SET use_count = use_count + 1 WHERE code = $1",
            code
        )

        return {
            "message": "Joined workspace",
            "workspace_id": str(invite['workspace_id']),
            "workspace_name": invite['workspace_name']
        }


# ============ OAUTH ENDPOINTS ============

@app.get("/oauth/{provider}/authorize", tags=["OAuth"])
async def oauth_authorize(
    provider: str,
    workspace_id: UUID = Query(..., description="Workspace to connect this integration to"),
    user_id: UUID = Depends(get_current_user)
):
    """Start OAuth flow for a provider. Connects to specified workspace."""
    if provider not in ['linear', 'github', 'slack']:
        raise HTTPException(status_code=400, detail="Invalid provider")

    # Verify user has access to workspace
    await verify_workspace_access(user_id, workspace_id)

    state = secrets.token_urlsafe(32)
    oauth_states[state] = {
        "user_id": str(user_id),
        "workspace_id": str(workspace_id),
        "provider": provider
    }

    redirect_uri = get_redirect_uri(provider)
    authorize_url = get_authorize_url(provider, redirect_uri, state)

    # Debug: show what URL we're generating
    print(f"[OAuth] {provider.upper()} authorize for workspace {workspace_id}:")
    print(f"        Redirect URI: {redirect_uri}")
    print(f"        Authorize URL: {authorize_url[:120]}...")

    # Check if client_id is missing
    if 'client_id=None' in authorize_url or 'client_id=&' in authorize_url:
        print(f"[OAuth] WARNING: {provider.upper()}_CLIENT_ID is not set in .env!")
        raise HTTPException(
            status_code=500,
            detail=f"{provider.upper()}_CLIENT_ID not configured. Add it to backend/.env"
        )

    return {"authorize_url": authorize_url}


@app.get("/oauth/{provider}/callback", tags=["OAuth"])
async def oauth_callback(provider: str, code: str, state: str):
    """OAuth callback - exchange code for token and store at workspace level."""
    print(f"[OAuth] Callback received for {provider}, state={state[:20]}...")

    if state not in oauth_states:
        print(f"[OAuth] ERROR: Invalid state. Known states: {list(oauth_states.keys())}")
        return RedirectResponse(f"{FRONTEND_URL}/?error=invalid_state")

    state_data = oauth_states.pop(state)
    user_id = UUID(state_data['user_id'])
    workspace_id = UUID(state_data['workspace_id'])
    print(f"[OAuth] Processing for user {user_id}, workspace {workspace_id}")

    redirect_uri = get_redirect_uri(provider)

    try:
        # Exchange code for token
        print(f"[OAuth] Exchanging code for token...")
        token_data = await exchange_code_for_token(provider, code, redirect_uri)
        print(f"[OAuth] Token response keys: {token_data.keys() if isinstance(token_data, dict) else 'not a dict'}")

        access_token = token_data.get('access_token')
        if not access_token:
            raise Exception(f"No access token in response: {token_data}")

        # Get provider info (org name, etc.)
        print(f"[OAuth] Getting provider info...")
        provider_info = await get_user_info(provider, access_token)
        print(f"[OAuth] Provider info: {provider_info}")

        # Store token at workspace level
        print(f"[OAuth] Storing token in workspace_integrations...")
        async with get_pool().acquire() as conn:
            await conn.execute("""
                INSERT INTO workspace_integrations (workspace_id, provider, access_token, refresh_token, provider_info, connected_by)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                ON CONFLICT (workspace_id, provider) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    provider_info = EXCLUDED.provider_info,
                    connected_by = EXCLUDED.connected_by,
                    updated_at = NOW()
            """,
                workspace_id, provider, access_token,
                token_data.get('refresh_token'),
                json.dumps(provider_info),
                user_id
            )

        print(f"[OAuth] SUCCESS! Redirecting to frontend...")
        # Redirect to frontend with workspace context
        return RedirectResponse(f"{FRONTEND_URL}/?connected={provider}&workspace={workspace_id}")

    except Exception as e:
        print(f"[OAuth] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(f"{FRONTEND_URL}/?error={str(e)}")


# ============ SYNC ENDPOINTS ============

@app.post("/workspaces/{workspace_id}/sync/{provider}", tags=["Sync"])
async def trigger_sync(
    workspace_id: UUID,
    provider: str,
    repos: str = Query(None, description="Comma-separated repos for GitHub"),
    channels: str = Query(None, description="Comma-separated channels for Slack"),
    user_id: UUID = Depends(get_current_user)
):
    """Trigger a data sync for a provider within a workspace."""
    if provider not in ['linear', 'github', 'slack', 'all']:
        raise HTTPException(status_code=400, detail="Invalid provider")

    # Verify user has access to workspace
    await verify_workspace_access(user_id, workspace_id)

    async with get_pool().acquire() as conn:
        # Get workspace's OAuth tokens
        integrations = await conn.fetch(
            "SELECT provider, access_token FROM workspace_integrations WHERE workspace_id = $1",
            workspace_id
        )
        tokens = {i['provider']: i['access_token'] for i in integrations}

        results = {}

        # Linear sync
        if provider in ['linear', 'all']:
            if 'linear' not in tokens:
                results['linear_error'] = "Not connected. Click Connect on Linear first."
            else:
                count = await sync_linear(conn, workspace_id, tokens['linear'])
                results['linear_issues'] = count

        # GitHub sync
        if provider in ['github', 'all']:
            if 'github' not in tokens:
                results['github_error'] = "Not connected. Click Connect on GitHub first."
            else:
                repo_list = [r.strip() for r in (repos or "").split(",") if r.strip()]
                if not repo_list:
                    results['github_error'] = "No repos specified. Use ?repos=org/repo1,org/repo2"
                else:
                    count = await sync_github(conn, workspace_id, tokens['github'], repo_list)
                    results['github_prs'] = count

        # Slack sync
        if provider in ['slack', 'all']:
            if 'slack' not in tokens:
                results['slack_error'] = "Not connected. Click Connect on Slack first."
            else:
                channel_list = [c.strip() for c in (channels or "").split(",") if c.strip()]
                if not channel_list:
                    results['slack_error'] = "No channels specified. Use ?channels=general,engineering"
                else:
                    count = await sync_slack(conn, workspace_id, tokens['slack'], channel_list)
                    results['slack_messages'] = count

        # Create links
        links = await create_links(conn, workspace_id)
        results['links_created'] = links

        return results


# ============ INTEGRATION DATA ENDPOINTS ============

@app.get("/workspaces/{workspace_id}/integrations/github/repos", tags=["Integrations"])
async def get_github_repos(workspace_id: UUID, user_id: UUID = Depends(get_current_user)):
    """Fetch list of repos the workspace has access to (requires OAuth connection)."""
    await verify_workspace_access(user_id, workspace_id)

    async with get_pool().acquire() as conn:
        integration = await conn.fetchrow(
            "SELECT access_token, provider_info FROM workspace_integrations WHERE workspace_id = $1 AND provider = 'github'",
            workspace_id
        )

        if not integration:
            raise HTTPException(status_code=400, detail="GitHub not connected. Click Connect to authorize.")

        access_token = integration['access_token']
        account = json.loads(integration['provider_info']) if integration['provider_info'] else {}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://api.github.com/user/repos",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"},
                params={"sort": "updated", "per_page": 100}
            )
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"GitHub API error: {response.status_code}")

            repos = response.json()
            return {
                "account": account,
                "repos": [{"full_name": r["full_name"], "private": r["private"], "updated_at": r["updated_at"]} for r in repos]
            }


@app.get("/workspaces/{workspace_id}/integrations/slack/channels", tags=["Integrations"])
async def get_slack_channels(workspace_id: UUID, user_id: UUID = Depends(get_current_user)):
    """Fetch list of Slack channels the workspace has access to (requires OAuth connection)."""
    await verify_workspace_access(user_id, workspace_id)

    async with get_pool().acquire() as conn:
        integration = await conn.fetchrow(
            "SELECT access_token, provider_info FROM workspace_integrations WHERE workspace_id = $1 AND provider = 'slack'",
            workspace_id
        )

        if not integration:
            raise HTTPException(status_code=400, detail="Slack not connected. Click Connect to authorize.")

        access_token = integration['access_token']
        account = json.loads(integration['provider_info']) if integration['provider_info'] else {}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"types": "public_channel,private_channel", "limit": 200}
            )
            data = response.json()
            if not data.get("ok"):
                raise HTTPException(status_code=500, detail=f"Slack API error: {data.get('error')}")

            return {
                "account": account,
                "channels": [{"name": c["name"], "id": c["id"], "is_private": c.get("is_private", False)} for c in data.get("channels", [])]
            }


# ============ QUERY ENDPOINTS ============

@app.get("/workspaces/{workspace_id}/stats", tags=["Query"])
async def get_stats(workspace_id: UUID, user_id: UUID = Depends(get_current_user)):
    """Get sync statistics for a workspace."""
    await verify_workspace_access(user_id, workspace_id)

    workspace_id_str = str(workspace_id)
    async with get_pool().acquire() as conn:
        stats = {
            "linear_issues": await conn.fetchval(
                "SELECT COUNT(*) FROM linear_issues WHERE workspace_id = $1::uuid", workspace_id_str
            ),
            "github_prs": await conn.fetchval(
                "SELECT COUNT(*) FROM github_prs WHERE workspace_id = $1::uuid", workspace_id_str
            ),
            "slack_messages": await conn.fetchval(
                "SELECT COUNT(*) FROM slack_messages WHERE workspace_id = $1::uuid", workspace_id_str
            ),
            "links": await conn.fetchval(
                "SELECT COUNT(*) FROM links WHERE workspace_id = $1::uuid", workspace_id_str
            ),
        }
        return stats


@app.get("/workspaces/{workspace_id}/context/{issue_id}", tags=["Query"])
async def get_context(workspace_id: UUID, issue_id: str, user_id: UUID = Depends(get_current_user)):
    """
    Get full context for a Linear issue - THE MAIN VALUE!
    Returns the issue with all linked PRs and Slack discussions.
    """
    await verify_workspace_access(user_id, workspace_id)

    workspace_id_str = str(workspace_id)
    async with get_pool().acquire() as conn:
        # Get issue
        issue = await conn.fetchrow(
            "SELECT * FROM linear_issues WHERE identifier = $1 AND workspace_id = $2::uuid",
            issue_id, workspace_id_str
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
            WHERE l.target_id = $1 AND l.target_type = 'linear_issue' AND l.workspace_id = $2::uuid
        """, issue_id, workspace_id_str)

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
            SELECT DISTINCT s.channel_name, s.message_text, s.user_name as slack_user, s.created_at
            FROM slack_messages s
            JOIN links l ON l.source_id = s.id
            WHERE l.target_id = $1 AND l.target_type = 'linear_issue' AND l.workspace_id = $2::uuid
        """, issue_id, workspace_id_str)

        for msg in messages:
            result["discussions"].append({
                "channel": msg["channel_name"],
                "text": msg["message_text"],
                "user": msg["slack_user"],
            })

        return result


@app.get("/workspaces/{workspace_id}/issues", tags=["Query"])
async def list_issues(
    workspace_id: UUID,
    team: str = None,
    status: str = None,
    limit: int = Query(50, le=200),
    user_id: UUID = Depends(get_current_user)
):
    """List Linear issues for a workspace."""
    await verify_workspace_access(user_id, workspace_id)

    workspace_id_str = str(workspace_id)
    async with get_pool().acquire() as conn:
        query = "SELECT identifier, title, status, team_name, assignee_name FROM linear_issues WHERE workspace_id = $1::uuid"
        params = [workspace_id_str]

        if team:
            params.append(team)
            query += f" AND team_name = ${len(params)}"
        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"

        query += f" ORDER BY updated_at DESC LIMIT {limit}"
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


@app.get("/workspaces/{workspace_id}/search", tags=["Query"])
async def search(workspace_id: UUID, q: str, user_id: UUID = Depends(get_current_user)):
    """Search across all data sources within a workspace."""
    await verify_workspace_access(user_id, workspace_id)

    workspace_id_str = str(workspace_id)
    async with get_pool().acquire() as conn:
        results = {"issues": [], "prs": [], "messages": []}

        issues = await conn.fetch("""
            SELECT identifier, title, status FROM linear_issues
            WHERE workspace_id = $1::uuid AND (title ILIKE $2 OR description ILIKE $2)
            LIMIT 20
        """, workspace_id_str, f"%{q}%")
        results["issues"] = [dict(r) for r in issues]

        prs = await conn.fetch("""
            SELECT repo, number, title, state FROM github_prs
            WHERE workspace_id = $1::uuid AND (title ILIKE $2 OR body ILIKE $2)
            LIMIT 20
        """, workspace_id_str, f"%{q}%")
        results["prs"] = [dict(r) for r in prs]

        messages = await conn.fetch("""
            SELECT id, channel_name, message_text FROM slack_messages
            WHERE workspace_id = $1::uuid AND message_text ILIKE $2
            LIMIT 20
        """, workspace_id_str, f"%{q}%")
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
