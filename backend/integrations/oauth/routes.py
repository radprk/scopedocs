"""
OAuth routes for connecting GitHub, Slack, and Linear.
"""

import secrets
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.integrations.oauth.config import (
    get_linear_config,
    get_github_config,
    get_slack_config,
)
from backend.storage.postgres import upsert_integration_token, get_pool

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

# In-memory state storage (use Redis in production)
_oauth_states: dict[str, dict] = {}


class OAuthStatus(BaseModel):
    """Status of OAuth connections for a workspace."""
    linear: bool = False
    github: bool = False
    slack: bool = False


class ConnectResponse(BaseModel):
    """Response from connect endpoints."""
    redirect_url: str


# =============================================================================
# Helper Functions
# =============================================================================

def generate_state(workspace_id: str, provider: str) -> str:
    """Generate a secure state parameter for OAuth."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "workspace_id": workspace_id,
        "provider": provider,
        "created_at": datetime.now(tz=timezone.utc),
    }
    return state


def validate_state(state: str) -> Optional[dict]:
    """Validate and consume an OAuth state."""
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return None
    # Check if state is expired (10 minutes)
    age = datetime.now(tz=timezone.utc) - state_data["created_at"]
    if age.total_seconds() > 600:
        return None
    return state_data


async def store_token(
    integration: str,
    workspace_id: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Store an OAuth token in the database."""
    expires_at = None
    if expires_in:
        expires_at = datetime.now(tz=timezone.utc).timestamp() + expires_in
        expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
    
    token_data = {
        "integration": integration,
        "workspace_id": workspace_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "metadata": metadata or {},
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    await upsert_integration_token(token_data)


async def check_token_exists(integration: str, workspace_id: str) -> bool:
    """Check if a token exists for a workspace."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM integration_tokens 
            WHERE integration = $1 AND workspace_id = $2
            """,
            integration,
            workspace_id,
        )
        return row is not None


# =============================================================================
# Status Endpoints
# =============================================================================

@router.get("/status/{workspace_id}", response_model=OAuthStatus)
async def get_oauth_status(workspace_id: str):
    """Get the OAuth connection status for a workspace."""
    return OAuthStatus(
        linear=await check_token_exists("linear", workspace_id),
        github=await check_token_exists("github", workspace_id),
        slack=await check_token_exists("slack", workspace_id),
    )


# =============================================================================
# Linear OAuth
# =============================================================================

@router.get("/linear/connect")
async def connect_linear(workspace_id: str = Query(..., description="Workspace ID")):
    """Start Linear OAuth flow."""
    config = get_linear_config()
    if not config.is_configured:
        raise HTTPException(
            status_code=500,
            detail="Linear OAuth not configured. Set LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET.",
        )
    
    state = generate_state(workspace_id, "linear")
    
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": ",".join(config.scopes),
        "state": state,
    }
    
    redirect_url = f"{config.authorize_url}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url)


@router.get("/linear/callback")
async def linear_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle Linear OAuth callback."""
    state_data = validate_state(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    
    config = get_linear_config()
    workspace_id = state_data["workspace_id"]
    
    # Exchange code for token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config.token_url,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to exchange code: {response.text}",
            )
        
        token_data = response.json()
    
    # Get Linear organization info
    linear_org_id = None
    linear_org_name = None
    async with httpx.AsyncClient() as client:
        org_response = await client.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            json={"query": "{ organization { id name } viewer { id email name } }"}
        )
        if org_response.status_code == 200:
            org_data = org_response.json().get("data", {})
            linear_org = org_data.get("organization", {})
            linear_org_id = linear_org.get("id")
            linear_org_name = linear_org.get("name")
            viewer = org_data.get("viewer", {})
    
    # Store token
    await store_token(
        integration="linear",
        workspace_id=workspace_id,
        access_token=token_data["access_token"],
        expires_in=token_data.get("expires_in"),
        metadata={
            "scope": token_data.get("scope"),
            "org_id": linear_org_id,
            "org_name": linear_org_name,
            "user_id": viewer.get("id") if 'viewer' in dir() else None,
            "user_email": viewer.get("email") if 'viewer' in dir() else None,
        },
    )
    
    # Update workspace with Linear org ID
    if linear_org_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspaces SET linear_org_id = $1 WHERE id = $2::uuid",
                linear_org_id, workspace_id
            )
            print(f"[OAuth] Updated workspace {workspace_id} with Linear org_id: {linear_org_id} ({linear_org_name})")
    
    # Redirect back to UI with workspace ID (always use relative path)
    return RedirectResponse(url=f"/ui#{workspace_id}", status_code=302)


# =============================================================================
# GitHub OAuth
# =============================================================================

@router.get("/github/connect")
async def connect_github(workspace_id: str = Query(..., description="Workspace ID")):
    """Start GitHub OAuth flow."""
    config = get_github_config()
    if not config.is_configured:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.",
        )
    
    state = generate_state(workspace_id, "github")
    
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(config.scopes),
        "state": state,
    }
    
    redirect_url = f"{config.authorize_url}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url)


@router.get("/github/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle GitHub OAuth callback."""
    state_data = validate_state(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    
    config = get_github_config()
    workspace_id = state_data["workspace_id"]
    
    # Exchange code for token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config.token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to exchange code: {response.text}",
            )
        
        token_data = response.json()
        
        if "error" in token_data:
            raise HTTPException(
                status_code=400,
                detail=f"GitHub error: {token_data.get('error_description', token_data['error'])}",
            )
    
    # Get user info for metadata
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token_data['access_token']}",
                "Accept": "application/vnd.github+json",
            },
        )
        user_data = user_response.json() if user_response.status_code == 200 else {}
        
        # Get user's organizations
        orgs_response = await client.get(
            "https://api.github.com/user/orgs",
            headers={
                "Authorization": f"Bearer {token_data['access_token']}",
                "Accept": "application/vnd.github+json",
            },
        )
        orgs_data = orgs_response.json() if orgs_response.status_code == 200 else []
    
    # Use first org if available, otherwise use user ID
    github_org_id = None
    github_org_login = None
    if orgs_data and len(orgs_data) > 0:
        github_org_id = str(orgs_data[0].get("id"))
        github_org_login = orgs_data[0].get("login")
    
    # Store token
    await store_token(
        integration="github",
        workspace_id=workspace_id,
        access_token=token_data["access_token"],
        metadata={
            "scope": token_data.get("scope"),
            "token_type": token_data.get("token_type"),
            "user_login": user_data.get("login"),
            "user_id": user_data.get("id"),
            "org_id": github_org_id,
            "org_login": github_org_login,
            "orgs": [{"id": o.get("id"), "login": o.get("login")} for o in (orgs_data or [])],
        },
    )
    
    # Update workspace with GitHub org ID
    if github_org_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspaces SET github_org_id = $1 WHERE id = $2::uuid",
                github_org_id, workspace_id
            )
            print(f"[OAuth] Updated workspace {workspace_id} with GitHub org_id: {github_org_id} ({github_org_login})")
    
    # Redirect back to UI with workspace ID (always use relative path)
    return RedirectResponse(url=f"/ui#{workspace_id}", status_code=302)


# =============================================================================
# Slack OAuth
# =============================================================================

@router.get("/slack/connect")
async def connect_slack(workspace_id: str = Query(..., description="Workspace ID")):
    """Start Slack OAuth flow.
    
    Uses user_scope instead of scope to request a USER token (xoxp-)
    instead of a bot token (xoxb-). User tokens can access channels
    the user is in without needing to invite a bot.
    """
    config = get_slack_config()
    if not config.is_configured:
        raise HTTPException(
            status_code=500,
            detail="Slack OAuth not configured. Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET.",
        )
    
    state = generate_state(workspace_id, "slack")
    
    # Use user_scope for USER token (xoxp-) instead of scope for bot token
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "user_scope": ",".join(config.scopes),  # user_scope gives us user token
        "state": state,
    }
    
    redirect_url = f"{config.authorize_url}?{urlencode(params)}"
    print(f"[OAuth] Slack user token flow: {redirect_url}")
    return RedirectResponse(url=redirect_url)


@router.get("/slack/callback")
async def slack_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle Slack OAuth callback."""
    state_data = validate_state(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    
    config = get_slack_config()
    workspace_id = state_data["workspace_id"]
    
    # Exchange code for token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config.token_url,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
        
        token_data = response.json()
        
        if not token_data.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=f"Slack error: {token_data.get('error', 'Unknown error')}",
            )
    
    # Store token (Slack returns access_token at top level or in authed_user)
    # For user tokens, check authed_user first
    access_token = token_data.get("authed_user", {}).get("access_token") or token_data.get("access_token")
    
    team_id = token_data.get("team", {}).get("id")
    team_name = token_data.get("team", {}).get("name")
    
    # Store token
    await store_token(
        integration="slack",
        workspace_id=workspace_id,
        access_token=access_token,
        metadata={
            "team_id": team_id,
            "team_name": team_name,
            "scope": token_data.get("scope") or token_data.get("authed_user", {}).get("scope"),
            "bot_user_id": token_data.get("bot_user_id"),
            "user_id": token_data.get("authed_user", {}).get("id"),
        },
    )
    
    # Update workspace with Slack team ID
    if team_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspaces SET slack_team_id = $1 WHERE id = $2::uuid",
                team_id, workspace_id
            )
            print(f"[OAuth] Updated workspace {workspace_id} with Slack team_id: {team_id}")
    
    # Redirect back to UI with workspace ID (always use relative path)
    return RedirectResponse(url=f"/ui#{workspace_id}", status_code=302)


# =============================================================================
# Disconnect Endpoints
# =============================================================================

@router.delete("/{provider}/disconnect")
async def disconnect_provider(
    provider: str,
    workspace_id: str = Query(..., description="Workspace ID"),
):
    """Disconnect an OAuth provider for a workspace."""
    if provider not in ["linear", "github", "slack"]:
        raise HTTPException(status_code=400, detail="Invalid provider")
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM integration_tokens 
            WHERE integration = $1 AND workspace_id = $2
            """,
            provider,
            workspace_id,
        )
    
    return {"status": "disconnected", "provider": provider}

