"""
ScopeDocs API Server - Minimal MVP
OAuth + Database + Sync workflows only
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path

# Import routers
from backend.sync.routes import router as sync_router
from backend.integrations.oauth.routes import router as oauth_router
from backend.storage.postgres import init_pg, close_pool, list_workspaces, create_workspace, get_workspace

# AI router (optional - only loaded if TOGETHER_API_KEY is set)
ai_router = None
try:
    if os.environ.get("TOGETHER_API_KEY"):
        from backend.ai.routes import router as ai_router
except ImportError:
    pass  # AI module not available

ROOT_DIR = Path(__file__).parent
PROJECT_ROOT = ROOT_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
load_dotenv(ROOT_DIR / '.env')

# Create the main app
app = FastAPI(title="ScopeDocs API", version="1.0.0")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Include routers
app.include_router(sync_router)
app.include_router(oauth_router)
if ai_router:
    app.include_router(ai_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    endpoints = {
        "ui": "/ui",
        "oauth": "/api/oauth/{provider}/connect",
        "sync": "/api/sync/{integration}",
        "health": "/health"
    }
    if ai_router:
        endpoints.update({
            "ai_search": "/api/ai/search",
            "ai_chat": "/api/ai/chat",
            "ai_generate_doc": "/api/ai/generate/doc",
            "ai_embed": "/api/ai/embed/code",
            "ai_health": "/api/ai/health"
        })
    return {
        "name": "ScopeDocs API",
        "version": "1.0.0",
        "status": "running",
        "ai_enabled": ai_router is not None,
        "endpoints": endpoints
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ui")
async def serve_ui():
    """Serve the integration testing UI."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/pipeline.html")
async def serve_pipeline_ui():
    """Serve the pipeline viewer UI."""
    return FileResponse(FRONTEND_DIR / "pipeline.html")


# Serve output files (sample docs and references)
OUTPUT_DIR = PROJECT_ROOT / "output"


@app.get("/output/{filename}")
async def serve_output_file(filename: str):
    """Serve files from the output directory."""
    from fastapi import HTTPException
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(file_path)


# =============================================================================
# Workspace endpoints
# =============================================================================

@app.get("/api/workspaces")
async def api_list_workspaces():
    """List all workspaces."""
    workspaces = await list_workspaces()
    # Convert UUIDs to strings for JSON serialization
    for w in workspaces:
        w['id'] = str(w['id'])
        if w.get('created_at'):
            w['created_at'] = w['created_at'].isoformat()
    return {"workspaces": workspaces}


@app.get("/api/workspaces/{workspace_id}")
async def api_get_workspace(workspace_id: str):
    """Get a workspace by ID."""
    workspace = await get_workspace(workspace_id)
    if not workspace:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace['id'] = str(workspace['id'])
    if workspace.get('created_at'):
        workspace['created_at'] = workspace['created_at'].isoformat()
    return workspace


@app.post("/api/workspaces")
async def api_create_workspace(data: dict):
    """Create a new workspace."""
    from fastapi import HTTPException
    name = data.get("name", "").strip()
    slug = data.get("slug", "").strip()
    
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    
    # Auto-generate slug from name if not provided
    if not slug:
        slug = name.lower().replace(" ", "-").replace("_", "-")
        # Remove any non-alphanumeric characters except hyphens
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
    
    try:
        workspace = await create_workspace(name, slug)
        workspace['id'] = str(workspace['id'])
        if workspace.get('created_at'):
            workspace['created_at'] = workspace['created_at'].isoformat()
        return workspace
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail=f"Workspace with slug '{slug}' already exists")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# GitHub API endpoints
# =============================================================================

@app.get("/api/github/repos/{workspace_id}")
async def api_list_github_repos(workspace_id: str):
    """List all GitHub repos accessible by the workspace's GitHub token."""
    from fastapi import HTTPException
    import httpx
    from backend.integrations.auth import get_integration_token
    
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected for this workspace")
    
    repos = []
    page = 1
    per_page = 100
    
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                "https://api.github.com/user/repos",
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/vnd.github+json",
                },
                params={
                    "per_page": per_page,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"GitHub API error: {response.text}"
                )
            
            data = response.json()
            if not data:
                break
            
            for repo in data:
                repos.append({
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "private": repo["private"],
                    "description": repo.get("description"),
                    "language": repo.get("language"),
                    "updated_at": repo.get("updated_at"),
                    "default_branch": repo.get("default_branch", "main"),
                    "clone_url": repo.get("clone_url"),
                    "html_url": repo.get("html_url"),
                })
            
            # Check if there are more pages
            if len(data) < per_page:
                break
            page += 1
            
            # Limit to first 500 repos
            if len(repos) >= 500:
                break
    
    return {"repos": repos, "count": len(repos)}


@app.get("/api/github/prs/{workspace_id}/{owner}/{repo}")
async def api_list_github_prs(workspace_id: str, owner: str, repo: str):
    """List pull requests for a specific GitHub repo."""
    from fastapi import HTTPException
    import httpx
    from backend.integrations.auth import get_integration_token
    
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected")
    
    prs = []
    page = 1
    
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"state": "all", "per_page": 100, "page": page}
            )
            
            if response.status_code != 200:
                break
            
            data = response.json()
            if not data:
                break
            
            for pr in data:
                prs.append({
                    "id": pr["id"],
                    "number": pr["number"],
                    "title": pr["title"],
                    "state": pr["state"],
                    "user": pr["user"]["login"],
                    "created_at": pr["created_at"],
                    "updated_at": pr["updated_at"],
                    "merged_at": pr.get("merged_at"),
                    "html_url": pr["html_url"],
                })
            
            if len(data) < 100:
                break
            page += 1
            if len(prs) >= 500:
                break
    
    return {"prs": prs, "count": len(prs)}


# =============================================================================
# Slack API endpoints
# =============================================================================

@app.get("/api/slack/channels/{workspace_id}")
async def api_list_slack_channels(workspace_id: str):
    """List all Slack channels accessible to the user."""
    from fastapi import HTTPException
    import httpx
    from backend.integrations.auth import get_integration_token
    
    token = await get_integration_token("slack", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Slack not connected")
    
    channels = []
    cursor = None
    
    async with httpx.AsyncClient() as client:
        while True:
            params = {"types": "public_channel,private_channel", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            
            response = await client.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {token.access_token}"},
                params=params
            )
            
            data = response.json()
            if not data.get("ok"):
                raise HTTPException(status_code=400, detail=data.get("error", "Slack API error"))
            
            for channel in data.get("channels", []):
                channels.append({
                    "id": channel["id"],
                    "name": channel["name"],
                    "is_private": channel.get("is_private", False),
                    "is_member": channel.get("is_member", False),
                    "num_members": channel.get("num_members", 0),
                    "topic": channel.get("topic", {}).get("value", ""),
                    "purpose": channel.get("purpose", {}).get("value", ""),
                })
            
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    
    return {"channels": channels, "count": len(channels)}


# =============================================================================
# Linear API endpoints
# =============================================================================

@app.get("/api/linear/teams/{workspace_id}")
async def api_list_linear_teams(workspace_id: str):
    """List all Linear teams and their projects."""
    from fastapi import HTTPException
    import httpx
    from backend.integrations.auth import get_integration_token
    
    token = await get_integration_token("linear", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Linear not connected")
    
    query = """
    query {
        teams {
            nodes {
                id
                name
                key
                description
                projects {
                    nodes {
                        id
                        name
                        state
                    }
                }
            }
        }
    }
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.linear.app/graphql",
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json",
            },
            json={"query": query}
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Linear API error")
        
        data = response.json()
        if "errors" in data:
            raise HTTPException(status_code=400, detail=data["errors"][0]["message"])
        
        teams = []
        for team in data.get("data", {}).get("teams", {}).get("nodes", []):
            teams.append({
                "id": team["id"],
                "name": team["name"],
                "key": team["key"],
                "description": team.get("description", ""),
                "projects": [
                    {"id": p["id"], "name": p["name"], "state": p.get("state")}
                    for p in team.get("projects", {}).get("nodes", [])
                ]
            })
    
    return {"teams": teams, "count": len(teams)}


# =============================================================================
# Data Sync endpoints (fetch and store in database)
# =============================================================================

@app.post("/api/data/sync/slack-messages")
async def api_sync_slack_messages(data: dict):
    """Sync messages from selected Slack channels into the database."""
    from fastapi import HTTPException
    import httpx
    from datetime import datetime, timedelta
    from backend.integrations.auth import get_integration_token
    from backend.storage.postgres import get_pool, upsert_conversation
    
    workspace_id = data.get("workspace_id")
    channel_ids = data.get("channel_ids", [])
    lookback_days = data.get("lookback_days", 7)
    
    if not workspace_id or not channel_ids:
        raise HTTPException(status_code=400, detail="workspace_id and channel_ids required")
    
    token = await get_integration_token("slack", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Slack not connected")
    
    oldest = (datetime.utcnow() - timedelta(days=lookback_days)).timestamp()
    stats = {"channels_synced": 0, "messages_synced": 0, "errors": []}
    
    async with httpx.AsyncClient() as client:
        for channel_id in channel_ids:
            try:
                # Get channel info
                info_resp = await client.get(
                    "https://slack.com/api/conversations.info",
                    headers={"Authorization": f"Bearer {token.access_token}"},
                    params={"channel": channel_id}
                )
                channel_info = info_resp.json()
                channel_name = channel_info.get("channel", {}).get("name", channel_id)
                
                # Fetch messages
                cursor = None
                messages = []
                while True:
                    params = {"channel": channel_id, "oldest": oldest, "limit": 200}
                    if cursor:
                        params["cursor"] = cursor
                    
                    response = await client.get(
                        "https://slack.com/api/conversations.history",
                        headers={"Authorization": f"Bearer {token.access_token}"},
                        params=params
                    )
                    
                    msg_data = response.json()
                    if not msg_data.get("ok"):
                        stats["errors"].append(f"Channel {channel_id}: {msg_data.get('error')}")
                        break
                    
                    messages.extend(msg_data.get("messages", []))
                    
                    if not msg_data.get("has_more"):
                        break
                    cursor = msg_data.get("response_metadata", {}).get("next_cursor")
                
                # Store as conversation
                if messages:
                    conversation = {
                        "external_id": f"slack:{channel_id}",
                        "channel": channel_name,
                        "thread_ts": messages[0].get("ts", ""),
                        "messages": messages,
                        "participants": list(set(m.get("user", "") for m in messages if m.get("user"))),
                    }
                    await upsert_conversation(conversation, workspace_id=workspace_id)
                    stats["messages_synced"] += len(messages)
                
                stats["channels_synced"] += 1
                
            except Exception as e:
                stats["errors"].append(f"Channel {channel_id}: {str(e)}")
    
    return {"status": "success", "stats": stats}


@app.post("/api/data/sync/linear-issues")
async def api_sync_linear_issues(data: dict):
    """Sync issues from selected Linear teams/projects into the database."""
    from fastapi import HTTPException
    import httpx
    from datetime import datetime, timedelta
    from backend.integrations.auth import get_integration_token
    from backend.storage.postgres import upsert_work_item
    
    workspace_id = data.get("workspace_id")
    team_ids = data.get("team_ids", [])
    project_ids = data.get("project_ids", [])
    lookback_days = data.get("lookback_days", 30)
    
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    
    token = await get_integration_token("linear", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Linear not connected")
    
    since = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()
    stats = {"issues_synced": 0, "errors": []}
    
    # Build filter
    filter_parts = []
    if team_ids:
        filter_parts.append(f'team: {{ id: {{ in: {team_ids} }} }}')
    if project_ids:
        filter_parts.append(f'project: {{ id: {{ in: {project_ids} }} }}')
    
    filter_str = ", ".join(filter_parts) if filter_parts else ""
    
    query = f"""
    query($after: String) {{
        issues(
            first: 100
            after: $after
            filter: {{ updatedAt: {{ gte: "{since}" }}{", " + filter_str if filter_str else ""} }}
        ) {{
            pageInfo {{
                hasNextPage
                endCursor
            }}
            nodes {{
                id
                identifier
                title
                description
                state {{ name }}
                priority
                team {{ id name key }}
                project {{ id name }}
                assignee {{ id name email }}
                labels {{ nodes {{ id name }} }}
                createdAt
                updatedAt
            }}
        }}
    }}
    """
    
    async with httpx.AsyncClient() as client:
        cursor = None
        while True:
            response = await client.post(
                "https://api.linear.app/graphql",
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": {"after": cursor}}
            )
            
            result = response.json()
            if "errors" in result:
                stats["errors"].append(result["errors"][0]["message"])
                break
            
            issues_data = result.get("data", {}).get("issues", {})
            
            for issue in issues_data.get("nodes", []):
                try:
                    work_item = {
                        "external_id": f"linear:{issue['id']}",
                        "title": issue["title"],
                        "description": issue.get("description", ""),
                        "status": issue.get("state", {}).get("name", "Unknown"),
                        "team": issue.get("team", {}).get("name"),
                        "assignee": issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
                        "project_id": issue.get("project", {}).get("id") if issue.get("project") else None,
                        "labels": [l["name"] for l in issue.get("labels", {}).get("nodes", [])],
                        "created_at": issue["createdAt"],
                        "updated_at": issue["updatedAt"],
                    }
                    await upsert_work_item(work_item, workspace_id=workspace_id)
                    stats["issues_synced"] += 1
                except Exception as e:
                    stats["errors"].append(f"Issue {issue.get('identifier')}: {str(e)}")
            
            page_info = issues_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
    
    return {"status": "success", "stats": stats}


@app.post("/api/data/sync/github-prs")
async def api_sync_github_prs(data: dict):
    """Sync pull requests from selected GitHub repos into the database."""
    from fastapi import HTTPException
    import httpx
    from datetime import datetime, timedelta
    from backend.integrations.auth import get_integration_token
    from backend.storage.postgres import upsert_pull_request
    
    workspace_id = data.get("workspace_id")
    repos = data.get("repos", [])  # List of "owner/repo" strings
    lookback_days = data.get("lookback_days", 30)
    
    if not workspace_id or not repos:
        raise HTTPException(status_code=400, detail="workspace_id and repos required")
    
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected")
    
    since = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()
    stats = {"repos_synced": 0, "prs_synced": 0, "errors": []}
    
    async with httpx.AsyncClient() as client:
        for repo_full_name in repos:
            try:
                page = 1
                while True:
                    response = await client.get(
                        f"https://api.github.com/repos/{repo_full_name}/pulls",
                        headers={
                            "Authorization": f"Bearer {token.access_token}",
                            "Accept": "application/vnd.github+json",
                        },
                        params={
                            "state": "all",
                            "sort": "updated",
                            "direction": "desc",
                            "per_page": 100,
                            "page": page
                        }
                    )
                    
                    if response.status_code != 200:
                        stats["errors"].append(f"Repo {repo_full_name}: {response.status_code}")
                        break
                    
                    prs = response.json()
                    if not prs:
                        break
                    
                    for pr in prs:
                        # Check if within lookback period
                        if pr["updated_at"] < since:
                            break
                        
                        try:
                            pr_data = {
                                "external_id": f"github:{pr['id']}",
                                "title": pr["title"],
                                "description": pr.get("body", "") or "",
                                "author": pr["user"]["login"],
                                "status": "merged" if pr.get("merged_at") else pr["state"],
                                "repo": repo_full_name,
                                "files_changed": [],  # Would need separate API call
                                "work_item_refs": [],
                                "created_at": pr["created_at"],
                                "merged_at": pr.get("merged_at"),
                                "reviewers": [r["login"] for r in pr.get("requested_reviewers", [])],
                            }
                            await upsert_pull_request(pr_data, workspace_id=workspace_id)
                            stats["prs_synced"] += 1
                        except Exception as e:
                            stats["errors"].append(f"PR #{pr['number']}: {str(e)}")
                    
                    if len(prs) < 100:
                        break
                    page += 1
                
                stats["repos_synced"] += 1
                
            except Exception as e:
                stats["errors"].append(f"Repo {repo_full_name}: {str(e)}")
    
    return {"status": "success", "stats": stats}


# =============================================================================
# Code Indexing endpoints
# =============================================================================

@app.post("/api/index/repo")
async def api_index_repo(data: dict):
    """
    Index a GitHub repo into Supabase code_chunks table.
    
    Expected payload:
    {
        "workspace_id": "uuid",
        "repo_full_name": "owner/repo",  # e.g., "radprk/scopedocs"
        "branch": "main"  # optional, defaults to default_branch
    }
    """
    from fastapi import HTTPException
    import httpx
    import tempfile
    import subprocess
    import hashlib
    import sys
    from pathlib import Path
    from backend.integrations.auth import get_integration_token
    from backend.storage.postgres import get_pool
    
    workspace_id = data.get("workspace_id")
    repo_full_name = data.get("repo_full_name")
    branch = data.get("branch")
    
    if not workspace_id or not repo_full_name:
        raise HTTPException(status_code=400, detail="workspace_id and repo_full_name are required")
    
    # Get GitHub token
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected for this workspace")
    
    # Create a unique repo_id based on workspace + repo
    repo_id = hashlib.sha256(f"{workspace_id}:{repo_full_name}".encode()).hexdigest()[:32]
    
    # Import the chunker
    sys.path.insert(0, str(PROJECT_ROOT / "code-indexing" / "src"))
    try:
        from indexing.chunker import chunk_code_file, CodeChunk
    except ImportError as e:
        logger.warning(f"Chunker not available: {e}, using fallback")
        # Fallback: simple line-based chunking
        def chunk_code_file(content, path, max_tokens=512):
            lines = content.split("\n")
            chunk_hash = hashlib.sha256(content.encode()).hexdigest()
            return [type('Chunk', (), {
                'content': content,
                'start_line': 1,
                'end_line': len(lines),
                'chunk_hash': chunk_hash,
                'chunk_index': 0
            })()]
    
    stats = {
        "files_indexed": 0,
        "chunks_created": 0,
        "errors": []
    }
    
    # Use GitHub API to fetch repo contents (for simplicity, no git clone)
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get default branch if not specified
        if not branch:
            repo_response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}",
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/vnd.github+json",
                }
            )
            if repo_response.status_code != 200:
                raise HTTPException(status_code=404, detail=f"Repo not found: {repo_full_name}")
            branch = repo_response.json().get("default_branch", "main")
        
        # Get repo tree (all files)
        tree_response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1",
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Accept": "application/vnd.github+json",
            }
        )
        
        if tree_response.status_code != 200:
            raise HTTPException(
                status_code=tree_response.status_code,
                detail=f"Failed to fetch repo tree: {tree_response.text}"
            )
        
        tree_data = tree_response.json()
        
        # Filter for Python files only
        python_files = [
            item for item in tree_data.get("tree", [])
            if item["type"] == "blob" and item["path"].endswith(".py")
            and not any(skip in item["path"] for skip in ["venv/", "__pycache__", ".git/", "node_modules/"])
        ]
        
        logger.info(f"Found {len(python_files)} Python files in {repo_full_name}")
        
        pool = await get_pool()
        
        for file_item in python_files[:50]:  # Limit to 50 files for now
            file_path = file_item["path"]
            file_path_hash = hashlib.sha256(file_path.encode()).hexdigest()
            
            try:
                # Fetch file content
                content_response = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}?ref={branch}",
                    headers={
                        "Authorization": f"Bearer {token.access_token}",
                        "Accept": "application/vnd.github.raw+json",
                    }
                )
                
                if content_response.status_code != 200:
                    stats["errors"].append(f"Failed to fetch {file_path}")
                    continue
                
                content = content_response.text
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                
                # Chunk the file
                chunks = chunk_code_file(content, file_path)
                
                if not chunks:
                    continue
                
                # Store file path lookup
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO file_path_lookup (repo_id, file_path_hash, file_path, file_content_hash)
                        VALUES ($1::uuid, $2, $3, $4)
                        ON CONFLICT (repo_id, file_path_hash) 
                        DO UPDATE SET file_content_hash = $4, file_path = $3, updated_at = NOW()
                        """,
                        repo_id,
                        file_path_hash,
                        file_path,
                        content_hash,
                    )
                    
                    # Delete old chunks for this file
                    await conn.execute(
                        """
                        DELETE FROM code_chunks 
                        WHERE repo_id = $1::uuid AND file_path_hash = $2
                        """,
                        repo_id,
                        file_path_hash,
                    )
                    
                    # Insert new chunks
                    for chunk in chunks:
                        await conn.execute(
                            """
                            INSERT INTO code_chunks 
                            (repo_id, file_path_hash, chunk_hash, chunk_index, start_line, end_line)
                            VALUES ($1::uuid, $2, $3, $4, $5, $6)
                            """,
                            repo_id,
                            file_path_hash,
                            chunk.chunk_hash,
                            chunk.chunk_index,
                            chunk.start_line,
                            chunk.end_line,
                        )
                        stats["chunks_created"] += 1
                
                stats["files_indexed"] += 1
                logger.info(f"Indexed {file_path}: {len(chunks)} chunks")
                
            except Exception as e:
                error_msg = f"Error indexing {file_path}: {str(e)}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
    
    return {
        "status": "success",
        "repo_id": repo_id,
        "repo": repo_full_name,
        "branch": branch,
        "stats": stats
    }


@app.get("/api/index/stats/{workspace_id}")
async def api_index_stats(workspace_id: str):
    """Get indexing stats for a workspace."""
    from backend.storage.postgres import get_pool
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Get count of indexed files and chunks
        stats = await conn.fetchrow(
            """
            SELECT 
                (SELECT COUNT(DISTINCT file_path_hash) FROM file_path_lookup) as total_files,
                (SELECT COUNT(*) FROM code_chunks) as total_chunks
            """
        )
        
        # Get recent files
        recent_files = await conn.fetch(
            """
            SELECT file_path, updated_at 
            FROM file_path_lookup 
            ORDER BY updated_at DESC 
            LIMIT 10
            """
        )
    
    return {
        "total_files": stats["total_files"] if stats else 0,
        "total_chunks": stats["total_chunks"] if stats else 0,
        "recent_files": [
            {"path": r["file_path"], "updated_at": r["updated_at"].isoformat()}
            for r in recent_files
        ]
    }


@app.post("/api/index/embed")
async def api_generate_embeddings(data: dict):
    """
    Generate embeddings for indexed chunks and store in code_embeddings table.

    Expected payload:
    {
        "workspace_id": "uuid",
        "repo_full_name": "owner/repo"
    }
    """
    from fastapi import HTTPException
    import httpx
    import hashlib
    import os
    import json
    from backend.storage.postgres import get_pool
    from backend.integrations.auth import get_integration_token

    workspace_id = data.get("workspace_id")
    repo_full_name = data.get("repo_full_name")

    if not workspace_id or not repo_full_name:
        raise HTTPException(status_code=400, detail="workspace_id and repo_full_name are required")

    # Check Together.ai API key
    together_key = os.environ.get("TOGETHER_API_KEY")
    if not together_key:
        raise HTTPException(status_code=400, detail="TOGETHER_API_KEY environment variable not set")

    # Get GitHub token for fetching code
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected for this workspace")

    repo_id = hashlib.sha256(f"{workspace_id}:{repo_full_name}".encode()).hexdigest()[:32]

    pool = await get_pool()

    # Get all chunks that don't have embeddings yet
    async with pool.acquire() as conn:
        # Get chunks from code_chunks
        chunks = await conn.fetch(
            """
            SELECT c.id, c.chunk_hash, c.chunk_index, c.start_line, c.end_line,
                   f.file_path, f.file_content_hash
            FROM code_chunks c
            JOIN file_path_lookup f ON c.file_path_hash = f.file_path_hash AND c.repo_id = f.repo_id
            WHERE c.repo_id = $1
            LIMIT 500
            """,
            repo_id
        )

    if not chunks:
        raise HTTPException(status_code=404, detail="No chunks found. Run indexing first.")

    logger.info(f"Found {len(chunks)} chunks to embed for {repo_full_name}")

    stats = {
        "total_chunks": len(chunks),
        "new_embeddings": 0,
        "skipped": 0,
        "errors": []
    }

    # Fetch code and generate embeddings in batches
    async with httpx.AsyncClient(timeout=120.0) as http:
        batch_size = 20

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts_to_embed = []
            chunk_metadata = []

            for chunk in batch:
                file_path = chunk["file_path"]

                # Fetch code from GitHub
                try:
                    url = f"https://raw.githubusercontent.com/{repo_full_name}/main/{file_path}"
                    response = await http.get(
                        url,
                        headers={"Authorization": f"token {token.access_token}"}
                    )

                    if response.status_code != 200:
                        stats["errors"].append(f"Failed to fetch {file_path}")
                        continue

                    lines = response.text.split("\n")
                    code_content = "\n".join(lines[chunk["start_line"]-1:chunk["end_line"]])

                    texts_to_embed.append(code_content)
                    chunk_metadata.append({
                        "file_path": file_path,
                        "start_line": chunk["start_line"],
                        "end_line": chunk["end_line"],
                        "chunk_index": chunk["chunk_index"],
                        "content_hash": hashlib.sha256(code_content.encode()).hexdigest(),
                    })

                except Exception as e:
                    stats["errors"].append(f"Error fetching {file_path}: {str(e)}")

            if not texts_to_embed:
                continue

            # Generate embeddings via Together.ai
            try:
                embed_response = await http.post(
                    "https://api.together.xyz/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {together_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "BAAI/bge-large-en-v1.5",
                        "input": texts_to_embed,
                    }
                )

                if embed_response.status_code != 200:
                    stats["errors"].append(f"Together.ai error: {embed_response.text}")
                    continue

                embed_data = embed_response.json()
                embeddings = [item["embedding"] for item in sorted(embed_data["data"], key=lambda x: x["index"])]

                # Store in code_embeddings
                async with pool.acquire() as conn:
                    for idx, (embedding, meta) in enumerate(zip(embeddings, chunk_metadata)):
                        # Check if already exists
                        existing = await conn.fetchrow(
                            """
                            SELECT id, content_hash FROM code_embeddings
                            WHERE workspace_id = $1 AND repo_full_name = $2
                            AND file_path = $3 AND chunk_index = $4
                            """,
                            workspace_id, repo_full_name, meta["file_path"], meta["chunk_index"]
                        )

                        if existing and existing["content_hash"] == meta["content_hash"]:
                            stats["skipped"] += 1
                            continue

                        # Upsert embedding
                        await conn.execute(
                            """
                            INSERT INTO code_embeddings
                            (workspace_id, repo_full_name, file_path, commit_sha, chunk_index,
                             start_line, end_line, content_hash, embedding, language)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10)
                            ON CONFLICT (workspace_id, repo_full_name, file_path, chunk_index)
                            DO UPDATE SET
                                content_hash = EXCLUDED.content_hash,
                                embedding = EXCLUDED.embedding,
                                updated_at = now()
                            """,
                            workspace_id, repo_full_name, meta["file_path"], "main",
                            meta["chunk_index"], meta["start_line"], meta["end_line"],
                            meta["content_hash"], json.dumps(embedding), "python"
                        )
                        stats["new_embeddings"] += 1

                logger.info(f"Embedded batch {i//batch_size + 1}: {len(embeddings)} chunks")

            except Exception as e:
                stats["errors"].append(f"Embedding error: {str(e)}")

    # Get total embeddings count
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM code_embeddings WHERE workspace_id = $1 AND repo_full_name = $2",
            workspace_id, repo_full_name
        )

    stats["total_embeddings"] = total or 0

    return {
        "status": "success",
        "new_embeddings": stats["new_embeddings"],
        "skipped": stats["skipped"],
        "total_embeddings": stats["total_embeddings"],
        "errors": stats["errors"][:5]  # Limit error messages
    }


@app.get("/api/index/chunks/{workspace_id}")
async def api_get_chunks(workspace_id: str, file_path: str = None, limit: int = 50):
    """
    Get indexed chunks with their code content.
    Optionally filter by file_path.
    """
    from fastapi import HTTPException
    import httpx
    from backend.storage.postgres import get_pool
    from backend.integrations.auth import get_integration_token
    
    pool = await get_pool()
    
    async with pool.acquire() as conn:
        # Get file paths and chunks
        if file_path:
            files = await conn.fetch(
                """
                SELECT fpl.file_path, fpl.file_path_hash, fpl.repo_id,
                       cc.chunk_index, cc.start_line, cc.end_line, cc.chunk_hash
                FROM file_path_lookup fpl
                JOIN code_chunks cc ON fpl.repo_id = cc.repo_id AND fpl.file_path_hash = cc.file_path_hash
                WHERE fpl.file_path ILIKE $1
                ORDER BY fpl.file_path, cc.chunk_index
                LIMIT $2
                """,
                f"%{file_path}%",
                limit
            )
        else:
            files = await conn.fetch(
                """
                SELECT fpl.file_path, fpl.file_path_hash, fpl.repo_id,
                       cc.chunk_index, cc.start_line, cc.end_line, cc.chunk_hash
                FROM file_path_lookup fpl
                JOIN code_chunks cc ON fpl.repo_id = cc.repo_id AND fpl.file_path_hash = cc.file_path_hash
                ORDER BY fpl.updated_at DESC, cc.chunk_index
                LIMIT $1
                """,
                limit
            )
    
    # Group by file
    chunks_by_file = {}
    for row in files:
        fp = row["file_path"]
        if fp not in chunks_by_file:
            chunks_by_file[fp] = {
                "file_path": fp,
                "repo_id": str(row["repo_id"]),
                "chunks": []
            }
        chunks_by_file[fp]["chunks"].append({
            "chunk_index": row["chunk_index"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "chunk_hash": row["chunk_hash"],
        })
    
    return {
        "files": list(chunks_by_file.values()),
        "total_chunks": len(files)
    }


@app.get("/api/index/chunk-content/{workspace_id}")
async def api_get_chunk_content(
    workspace_id: str,
    repo_full_name: str,
    file_path: str,
    start_line: int,
    end_line: int
):
    """
    Fetch the actual code content for a specific chunk from GitHub.
    """
    from fastapi import HTTPException
    import httpx
    from backend.integrations.auth import get_integration_token
    
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Accept": "application/vnd.github.raw+json",
            }
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch file")
        
        content = response.text
        lines = content.split('\n')
        
        # Extract the chunk lines (1-indexed in our DB)
        chunk_lines = lines[start_line - 1:end_line]
        chunk_content = '\n'.join(chunk_lines)
        
        return {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_content,
            "language": file_path.split('.')[-1] if '.' in file_path else "text"
        }


@app.get("/api/index/files/{workspace_id}")
async def api_list_indexed_files(workspace_id: str):
    """List all indexed files for the workspace."""
    from backend.storage.postgres import get_pool
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        files = await conn.fetch(
            """
            SELECT 
                fpl.file_path, 
                fpl.file_path_hash,
                fpl.repo_id,
                fpl.updated_at,
                COUNT(cc.id) as chunk_count
            FROM file_path_lookup fpl
            LEFT JOIN code_chunks cc ON fpl.repo_id = cc.repo_id AND fpl.file_path_hash = cc.file_path_hash
            GROUP BY fpl.id, fpl.file_path, fpl.file_path_hash, fpl.repo_id, fpl.updated_at
            ORDER BY fpl.updated_at DESC
            LIMIT 100
            """
        )
    
    return {
        "files": [
            {
                "file_path": f["file_path"],
                "file_path_hash": f["file_path_hash"],
                "repo_id": str(f["repo_id"]),
                "chunk_count": f["chunk_count"],
                "updated_at": f["updated_at"].isoformat()
            }
            for f in files
        ]
    }


@app.on_event("startup")
async def startup():
    try:
        await init_pg()
        logger.info("PostgreSQL database initialized")
    except Exception as e:
        logger.warning(f"Database not available: {e}")
        logger.info("Running without database - OAuth testing still works")


@app.on_event("shutdown")
async def shutdown():
    await close_pool()
    logger.info("Database connection closed")
