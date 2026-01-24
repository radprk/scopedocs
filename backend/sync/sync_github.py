"""
GitHub sync module - fetches PRs and commits from GitHub REST API.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.ingest.normalize import normalize_github_pull_request
from backend.storage.postgres import upsert_pull_request, upsert_relationship
from backend.sync.base import (
    SyncResult,
    get_env_token,
    get_last_sync_time,
    set_last_sync_time,
)

GITHUB_API_BASE = "https://api.github.com"


async def fetch_pull_requests(
    repo: str,
    token: str,
    since: datetime,
    state: str = "all",
) -> List[Dict[str, Any]]:
    """Fetch pull requests from a GitHub repository."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    prs: List[Dict[str, Any]] = []
    page = 1
    per_page = 100
    
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            url = f"{GITHUB_API_BASE}/repos/{repo}/pulls"
            params = {
                "state": state,
                "sort": "updated",
                "direction": "desc",
                "per_page": per_page,
                "page": page,
            }
            
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            batch = response.json()
            if not batch:
                break
            
            for pr in batch:
                updated_at_str = pr.get("updated_at")
                if updated_at_str:
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    if updated_at < since:
                        # PRs are sorted by updated_at desc, so we can stop
                        return prs
                
                prs.append(pr)
            
            # Check if we've fetched all pages
            if len(batch) < per_page:
                break
            
            page += 1
    
    return prs


async def fetch_pr_files(
    repo: str,
    pr_number: int,
    token: str,
) -> List[str]:
    """Fetch the list of files changed in a PR."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/files"
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        
        files = response.json()
        return [f.get("filename", "") for f in files if f.get("filename")]


async def sync_github(
    repos: Optional[List[str]] = None,
    lookback_days: int = 7,
) -> SyncResult:
    """
    Sync pull requests from GitHub repositories.
    
    Args:
        repos: List of repos in "owner/repo" format. If None, uses GITHUB_REPOS env var.
        lookback_days: Number of days to look back for initial sync.
    
    Returns:
        SyncResult with sync statistics.
    """
    result = SyncResult("github")
    
    token = get_env_token("github")
    if not token:
        result.add_error("GITHUB_ACCESS_TOKEN not set")
        result.finish()
        return result
    
    # Get repos from args or env
    if not repos:
        repos_env = os.environ.get("GITHUB_REPOS", "")
        repos = [r.strip() for r in repos_env.split(",") if r.strip()]
    
    if not repos:
        result.add_error("No repos specified. Set GITHUB_REPOS or pass --repos")
        result.finish()
        return result
    
    # Get last sync time
    since = await get_last_sync_time("github", default_days=lookback_days)
    
    for repo in repos:
        try:
            prs = await fetch_pull_requests(repo, token, since)
            
            for pr_data in prs:
                # Build payload in webhook format for normalize function
                payload = {
                    "pull_request": pr_data,
                    "repository": {"full_name": repo},
                }
                
                # Normalize and store
                pr_model, relationships = await normalize_github_pull_request(payload)
                
                # Fetch files changed
                pr_number = pr_data.get("number")
                if pr_number:
                    try:
                        files = await fetch_pr_files(repo, pr_number, token)
                        pr_model.files_changed = files
                    except Exception:
                        pass  # Files are optional
                
                # Upsert PR
                await upsert_pull_request(pr_model.model_dump())
                
                # Upsert relationships
                for rel in relationships:
                    await upsert_relationship(rel.model_dump())
                
                result.items_synced += 1
        
        except httpx.HTTPStatusError as e:
            result.add_error(f"GitHub API error for {repo}: {e.response.status_code}")
        except Exception as e:
            result.add_error(f"Error syncing {repo}: {str(e)}")
    
    # Update last sync time
    await set_last_sync_time("github")
    
    result.finish()
    return result

