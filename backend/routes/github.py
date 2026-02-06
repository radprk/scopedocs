"""GitHub API routes."""

from fastapi import APIRouter, HTTPException
import httpx

from backend.integrations.auth import get_integration_token

router = APIRouter(prefix="/api/github", tags=["github"])


@router.get("/repos/{workspace_id}")
async def api_list_github_repos(workspace_id: str):
    """List all GitHub repos accessible by the workspace's GitHub token."""
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected for this workspace")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    if not access_token:
        raise HTTPException(status_code=404, detail="GitHub token not found")
    
    async with httpx.AsyncClient() as client:
        repos = []
        page = 1
        while True:
            response = await client.get(
                f"https://api.github.com/user/repos",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                params={
                    "per_page": 100,
                    "page": page,
                    "sort": "updated"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"GitHub API error: {response.text}"
                )
            
            page_repos = response.json()
            if not page_repos:
                break
                
            repos.extend([
                {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "private": repo["private"],
                    "default_branch": repo["default_branch"],
                    "language": repo.get("language"),
                    "updated_at": repo["updated_at"],
                }
                for repo in page_repos
            ])
            
            if len(page_repos) < 100:
                break
            page += 1
    
    return {"repos": repos}
