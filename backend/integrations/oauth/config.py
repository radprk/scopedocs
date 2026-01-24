"""
OAuth configuration for each provider.
"""

import os
from typing import Optional
from pydantic import BaseModel


class OAuthConfig(BaseModel):
    """OAuth configuration for a provider."""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    authorize_url: str
    token_url: str
    scopes: list[str]
    
    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def get_base_url() -> str:
    """Get the base URL for OAuth callbacks."""
    return os.environ.get("BASE_URL", "http://localhost:8000")


def get_frontend_url() -> str:
    """Get the frontend URL for redirects after OAuth."""
    return os.environ.get("FRONTEND_URL", "http://localhost:3000")


def get_linear_config() -> OAuthConfig:
    """Get Linear OAuth configuration."""
    base_url = get_base_url()
    return OAuthConfig(
        client_id=os.environ.get("LINEAR_CLIENT_ID"),
        client_secret=os.environ.get("LINEAR_CLIENT_SECRET"),
        redirect_uri=f"{base_url}/api/oauth/linear/callback",
        authorize_url="https://linear.app/oauth/authorize",
        token_url="https://api.linear.app/oauth/token",
        scopes=["read", "write"],  # read for issues, write for future features
    )


def get_github_config() -> OAuthConfig:
    """Get GitHub OAuth configuration."""
    base_url = get_base_url()
    return OAuthConfig(
        client_id=os.environ.get("GITHUB_CLIENT_ID"),
        client_secret=os.environ.get("GITHUB_CLIENT_SECRET"),
        redirect_uri=f"{base_url}/api/oauth/github/callback",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=["repo", "read:org", "read:user"],
    )


def get_slack_config() -> OAuthConfig:
    """Get Slack OAuth configuration."""
    base_url = get_base_url()
    return OAuthConfig(
        client_id=os.environ.get("SLACK_CLIENT_ID"),
        client_secret=os.environ.get("SLACK_CLIENT_SECRET"),
        redirect_uri=f"{base_url}/api/oauth/slack/callback",
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=[
            "channels:history",
            "channels:read", 
            "groups:history",
            "groups:read",
            "users:read",
        ],
    )

