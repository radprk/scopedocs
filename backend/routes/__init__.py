"""API route modules."""

from .auth import router as auth_router
from .workspaces import router as workspaces_router
from .github import router as github_router
from .indexing import router as indexing_router
from .data_sync import router as data_sync_router

__all__ = [
    "auth_router",
    "workspaces_router",
    "github_router",
    "indexing_router",
    "data_sync_router",
]
