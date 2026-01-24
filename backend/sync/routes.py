"""
API routes for triggering manual syncs.
"""

import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.sync.sync_github import sync_github
from backend.sync.sync_slack import sync_slack
from backend.sync.sync_linear import sync_linear

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncRequest(BaseModel):
    """Request body for sync endpoints."""
    repos: Optional[List[str]] = None  # For GitHub
    channels: Optional[List[str]] = None  # For Slack
    team_keys: Optional[List[str]] = None  # For Linear
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


@router.post("/slack", response_model=SyncResponse)
async def trigger_slack_sync(request: SyncRequest):
    """
    Trigger a Slack sync manually.
    
    Fetches conversations from specified channels (or SLACK_CHANNELS env var).
    """
    channels = request.channels
    if not channels:
        channels_env = os.environ.get("SLACK_CHANNELS", "")
        channels = [c.strip() for c in channels_env.split(",") if c.strip()]
    
    if not channels:
        raise HTTPException(
            status_code=400,
            detail="No channels specified. Pass 'channels' in request body or set SLACK_CHANNELS env var."
        )
    
    result = await sync_slack(channels=channels, lookback_days=request.lookback_days)
    
    return SyncResponse(
        source=result.source,
        success=result.success,
        items_synced=result.items_synced,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
    )


@router.post("/linear", response_model=SyncResponse)
async def trigger_linear_sync(request: SyncRequest):
    """
    Trigger a Linear sync manually.
    
    Fetches issues from Linear, optionally filtered by team keys.
    """
    result = await sync_linear(
        team_keys=request.team_keys,
        lookback_days=request.lookback_days,
    )
    
    return SyncResponse(
        source=result.source,
        success=result.success,
        items_synced=result.items_synced,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
    )


@router.post("/all", response_model=List[SyncResponse])
async def trigger_all_syncs(request: SyncRequest):
    """
    Trigger all syncs (GitHub, Slack, Linear) manually.
    """
    results = []
    
    # GitHub
    repos = request.repos
    if not repos:
        repos_env = os.environ.get("GITHUB_REPOS", "")
        repos = [r.strip() for r in repos_env.split(",") if r.strip()]
    
    if repos:
        github_result = await sync_github(repos=repos, lookback_days=request.lookback_days)
        results.append(SyncResponse(
            source=github_result.source,
            success=github_result.success,
            items_synced=github_result.items_synced,
            errors=github_result.errors,
            duration_seconds=github_result.duration_seconds,
        ))
    
    # Slack
    channels = request.channels
    if not channels:
        channels_env = os.environ.get("SLACK_CHANNELS", "")
        channels = [c.strip() for c in channels_env.split(",") if c.strip()]
    
    if channels:
        slack_result = await sync_slack(channels=channels, lookback_days=request.lookback_days)
        results.append(SyncResponse(
            source=slack_result.source,
            success=slack_result.success,
            items_synced=slack_result.items_synced,
            errors=slack_result.errors,
            duration_seconds=slack_result.duration_seconds,
        ))
    
    # Linear (always runs)
    linear_result = await sync_linear(
        team_keys=request.team_keys,
        lookback_days=request.lookback_days,
    )
    results.append(SyncResponse(
        source=linear_result.source,
        success=linear_result.success,
        items_synced=linear_result.items_synced,
        errors=linear_result.errors,
        duration_seconds=linear_result.duration_seconds,
    ))
    
    return results

