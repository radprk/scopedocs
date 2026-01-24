"""
OAuth integration module for multi-tenant authentication.
Allows teams to connect their own GitHub, Slack, and Linear accounts.
"""

from backend.integrations.oauth.routes import router

__all__ = ["router"]

