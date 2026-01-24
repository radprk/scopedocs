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
    get_frontend_url,
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
    
    # Store token
    await store_token(
        integration="linear",
        workspace_id=workspace_id,
        access_token=token_data["access_token"],
        expires_in=token_data.get("expires_in"),
        metadata={"scope": token_data.get("scope")},
    )
    
    # Redirect to frontend
    frontend_url = get_frontend_url()
    return RedirectResponse(url=f"{frontend_url}/settings?connected=linear")


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
        },
    )
    
    # Redirect to frontend
    frontend_url = get_frontend_url()
    return RedirectResponse(url=f"{frontend_url}/settings?connected=github")


# =============================================================================
# Slack OAuth
# =============================================================================

@router.get("/slack/connect")
async def connect_slack(workspace_id: str = Query(..., description="Workspace ID")):
    """Start Slack OAuth flow."""
    config = get_slack_config()
    if not config.is_configured:
        raise HTTPException(
            status_code=500,
            detail="Slack OAuth not configured. Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET.",
        )
    
    state = generate_state(workspace_id, "slack")
    
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": ",".join(config.scopes),
        "state": state,
    }
    
    redirect_url = f"{config.authorize_url}?{urlencode(params)}"
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
    access_token = token_data.get("access_token")
    
    # Store token
    await store_token(
        integration="slack",
        workspace_id=workspace_id,
        access_token=access_token,
        metadata={
            "team_id": token_data.get("team", {}).get("id"),
            "team_name": token_data.get("team", {}).get("name"),
            "scope": token_data.get("scope"),
            "bot_user_id": token_data.get("bot_user_id"),
        },
    )
    
    # Redirect to frontend
    frontend_url = get_frontend_url()
    return RedirectResponse(url=f"{frontend_url}/settings?connected=slack")


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

