"""Job handlers for async processing."""

import logging
from typing import Dict, Any

from .worker import register_handler, JobResult

logger = logging.getLogger(__name__)


def register_handlers():
    """Register all job handlers. Call this at startup."""
    pass  # Handlers are registered via decorators below


@register_handler("index_repo")
async def handle_index_repo(payload: Dict[str, Any]) -> JobResult:
    """Handle repository indexing job."""
    from backend.storage.postgres import get_pool
    import httpx
    import hashlib
    
    workspace_id = payload.get("workspace_id")
    repo_full_name = payload.get("repo_full_name")
    branch = payload.get("branch", "main")
    
    logger.info(f"Indexing repo {repo_full_name} ({branch})")
    
    try:
        # Import here to avoid circular imports
        from backend.integrations.auth import get_integration_token
        
        token = await get_integration_token("github", workspace_id)
        if not token:
            return JobResult(success=False, error="GitHub not connected")
        
        stats = {"files_indexed": 0, "chunks_created": 0, "errors": []}
        
        # Fetch repo tree
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1",
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/vnd.github+json",
                }
            )
            
            if response.status_code != 200:
                return JobResult(success=False, error=f"Failed to fetch repo tree: {response.status_code}")
            
            tree_data = response.json()
            
            # Filter for indexable files
            indexable_extensions = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java'}
            files_to_index = [
                item for item in tree_data.get("tree", [])
                if item["type"] == "blob" and any(item["path"].endswith(ext) for ext in indexable_extensions)
            ]
            
            stats["files_found"] = len(files_to_index)
            
            # Process files (chunking would happen here)
            for file_info in files_to_index[:50]:  # Limit for demo
                try:
                    # Fetch file content
                    content_response = await client.get(
                        f"https://api.github.com/repos/{repo_full_name}/contents/{file_info['path']}?ref={branch}",
                        headers={
                            "Authorization": f"Bearer {token.access_token}",
                            "Accept": "application/vnd.github.raw+json",
                        }
                    )
                    
                    if content_response.status_code == 200:
                        stats["files_indexed"] += 1
                        # Chunking would be done here
                        
                except Exception as e:
                    stats["errors"].append(f"{file_info['path']}: {str(e)}")
        
        return JobResult(success=True, data=stats)
        
    except Exception as e:
        logger.exception("Error in index_repo job")
        return JobResult(success=False, error=str(e))


@register_handler("sync_github")
async def handle_sync_github(payload: Dict[str, Any]) -> JobResult:
    """Handle GitHub sync job."""
    workspace_id = payload.get("workspace_id")
    repos = payload.get("repos", [])
    lookback_days = payload.get("lookback_days", 30)
    
    logger.info(f"Syncing GitHub PRs for {len(repos)} repos")
    
    try:
        from backend.integrations.auth import get_integration_token
        from backend.storage.postgres import upsert_pull_request
        import httpx
        from datetime import datetime, timedelta
        
        token = await get_integration_token("github", workspace_id)
        if not token:
            return JobResult(success=False, error="GitHub not connected")
        
        since = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()
        stats = {"repos_synced": 0, "prs_synced": 0, "errors": []}
        
        async with httpx.AsyncClient() as client:
            for repo in repos:
                try:
                    response = await client.get(
                        f"https://api.github.com/repos/{repo}/pulls",
                        headers={
                            "Authorization": f"Bearer {token.access_token}",
                            "Accept": "application/vnd.github+json",
                        },
                        params={"state": "all", "per_page": 100}
                    )
                    
                    if response.status_code == 200:
                        for pr in response.json():
                            await upsert_pull_request({
                                "external_id": f"github:{pr['id']}",
                                "title": pr["title"],
                                "repo": repo,
                            }, workspace_id=workspace_id)
                            stats["prs_synced"] += 1
                        stats["repos_synced"] += 1
                        
                except Exception as e:
                    stats["errors"].append(f"{repo}: {str(e)}")
        
        return JobResult(success=True, data=stats)
        
    except Exception as e:
        logger.exception("Error in sync_github job")
        return JobResult(success=False, error=str(e))


@register_handler("generate_docs")
async def handle_generate_docs(payload: Dict[str, Any]) -> JobResult:
    """Handle documentation generation job."""
    workspace_id = payload.get("workspace_id")
    file_path = payload.get("file_path")
    
    logger.info(f"Generating docs for {file_path}")
    
    try:
        # This would integrate with the AI layer
        return JobResult(
            success=True,
            data={"file": file_path, "status": "generated"}
        )
    except Exception as e:
        return JobResult(success=False, error=str(e))
