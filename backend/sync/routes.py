"""
API routes for triggering manual syncs.
Slack and Linear sync endpoints will be added in phase 2.
"""

import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.sync.sync_github import sync_github

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncRequest(BaseModel):
    """Request body for sync endpoints."""
    repos: Optional[List[str]] = None
    lookback_days: int = 7


class SyncResponse(BaseModel):
    """Response from sync endpoints."""
    source: str
    success: bool
    items_synced: int
    errors: List[str]
    duration_seconds: float


@router.post("/github", response_model=SyncResponse)
async def trigger_github_sync(request: SyncRequest):
    """
    Trigger a GitHub sync manually.

    Fetches pull requests from specified repos (or GITHUB_REPOS env var).
    """
    repos = request.repos
    if not repos:
        repos_env = os.environ.get("GITHUB_REPOS", "")
        repos = [r.strip() for r in repos_env.split(",") if r.strip()]

    if not repos:
        raise HTTPException(
            status_code=400,
            detail="No repos specified. Pass 'repos' in request body or set GITHUB_REPOS env var."
        )

    result = await sync_github(repos=repos, lookback_days=request.lookback_days)

    return SyncResponse(
        source=result.source,
        success=result.success,
        items_synced=result.items_synced,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
    )
