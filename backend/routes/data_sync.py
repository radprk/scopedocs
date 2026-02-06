"""Data sync routes for Slack, Linear, and GitHub."""

import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
import httpx

from backend.integrations.auth import get_integration_token
from backend.storage.postgres import (
    upsert_conversation, upsert_work_item, upsert_pull_request, get_pool
)

router = APIRouter(prefix="/api/data", tags=["data-sync"])


@router.get("/slack/channels/{workspace_id}")
async def api_list_slack_channels(workspace_id: str):
    """List Slack channels available to the workspace."""
    token = await get_integration_token("slack", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Slack not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    
    async with httpx.AsyncClient() as client:
        channels = []
        cursor = None
        
        while True:
            params = {"types": "public_channel,private_channel", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            
            response = await client.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params
            )
            
            data = response.json()
            if not data.get("ok"):
                raise HTTPException(status_code=400, detail=data.get("error", "Slack API error"))
            
            for ch in data.get("channels", []):
                channels.append({
                    "id": ch["id"],
                    "name": ch["name"],
                    "is_private": ch.get("is_private", False),
                    "is_member": ch.get("is_member", False),
                })
            
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    
    return {"channels": channels}


@router.get("/linear/teams/{workspace_id}")
async def api_list_linear_teams(workspace_id: str):
    """List Linear teams available to the workspace."""
    token = await get_integration_token("linear", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Linear not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    
    query = """
    query {
        teams {
            nodes {
                id
                name
                key
                projects {
                    nodes {
                        id
                        name
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
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"query": query}
        )
        
        result = response.json()
        if "errors" in result:
            raise HTTPException(status_code=400, detail=result["errors"][0]["message"])
        
        teams = []
        for team in result.get("data", {}).get("teams", {}).get("nodes", []):
            teams.append({
                "id": team["id"],
                "name": team["name"],
                "key": team["key"],
                "projects": [
                    {"id": p["id"], "name": p["name"]}
                    for p in team.get("projects", {}).get("nodes", [])
                ]
            })
    
    return {"teams": teams}


@router.post("/sync/slack-messages")
async def api_sync_slack_messages(data: dict):
    """Sync messages from selected Slack channels."""
    workspace_id = data.get("workspace_id")
    channel_ids = data.get("channel_ids", [])
    lookback_days = data.get("lookback_days", 30)
    
    if not workspace_id or not channel_ids:
        raise HTTPException(status_code=400, detail="workspace_id and channel_ids required")
    
    token = await get_integration_token("slack", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Slack not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    oldest = (datetime.utcnow() - timedelta(days=lookback_days)).timestamp()
    stats = {"channels_synced": 0, "messages_synced": 0, "errors": []}
    
    async with httpx.AsyncClient() as client:
        for channel_id in channel_ids:
            try:
                info_resp = await client.get(
                    "https://slack.com/api/conversations.info",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"channel": channel_id}
                )
                channel_info = info_resp.json()
                channel_name = channel_info.get("channel", {}).get("name", channel_id)
                
                cursor = None
                messages = []
                while True:
                    params = {"channel": channel_id, "oldest": oldest, "limit": 200}
                    if cursor:
                        params["cursor"] = cursor
                    
                    response = await client.get(
                        "https://slack.com/api/conversations.history",
                        headers={"Authorization": f"Bearer {access_token}"},
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
                
                if messages:
                    conversation = {
                        "external_id": f"slack:{channel_id}",
                        "channel": channel_name,
                        "thread_ts": messages[0].get("ts", ""),
                        "messages": messages,
                        "participants": list(set(m.get("user", "") for m in messages if m.get("user"))),
                        "workspace_id": workspace_id,
                    }
                    await upsert_conversation(conversation, workspace_id)
                    stats["messages_synced"] += len(messages)
                
                stats["channels_synced"] += 1
                
            except Exception as e:
                stats["errors"].append(f"Channel {channel_id}: {str(e)}")
    
    return {"status": "success", "stats": stats}


@router.post("/sync/linear-issues")
async def api_sync_linear_issues(data: dict):
    """Sync issues from selected Linear teams/projects."""
    workspace_id = data.get("workspace_id")
    team_ids = data.get("team_ids", [])
    project_ids = data.get("project_ids", [])
    lookback_days = data.get("lookback_days", 30)
    
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    
    token = await get_integration_token("linear", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="Linear not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    stats = {"issues_synced": 0, "errors": []}
    
    filter_parts = []
    if team_ids:
        filter_parts.append(f'team: {{ id: {{ in: {json.dumps(team_ids)} }} }}')
    if project_ids:
        filter_parts.append(f'project: {{ id: {{ in: {json.dumps(project_ids)} }} }}')
    
    filter_str = f'filter: {{ {", ".join(filter_parts)} }}' if filter_parts else ''
    
    query = f"""
    query Issues($after: String) {{
        issues({filter_str} orderBy: updatedAt, first: 50, after: $after) {{
            nodes {{
                id
                identifier
                title
                description
                state {{ name }}
                team {{ name }}
                assignee {{ name }}
                project {{ id }}
                labels {{ nodes {{ name }} }}
                createdAt
                updatedAt
            }}
            pageInfo {{
                hasNextPage
                endCursor
            }}
        }}
    }}
    """
    
    cursor = None
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.post(
                "https://api.linear.app/graphql",
                headers={
                    "Authorization": f"Bearer {access_token}",
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
                        "workspace_id": workspace_id,
                    }
                    await upsert_work_item(work_item, workspace_id)
                    stats["issues_synced"] += 1
                except Exception as e:
                    stats["errors"].append(f"Issue {issue.get('identifier')}: {str(e)}")
            
            page_info = issues_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
    
    return {"status": "success", "stats": stats}


@router.post("/sync/github-prs")
async def api_sync_github_prs(data: dict):
    """Sync pull requests from selected GitHub repos."""
    workspace_id = data.get("workspace_id")
    repos = data.get("repos", [])
    lookback_days = data.get("lookback_days", 30)
    
    if not workspace_id or not repos:
        raise HTTPException(status_code=400, detail="workspace_id and repos required")
    
    token = await get_integration_token("github", workspace_id)
    if not token:
        raise HTTPException(status_code=404, detail="GitHub not connected")
    
    access_token = token.access_token if hasattr(token, 'access_token') else token.get("access_token")
    since = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()
    stats = {"repos_synced": 0, "prs_synced": 0, "errors": []}
    
    async with httpx.AsyncClient() as client:
        for repo_full_name in repos:
            page = 1
            try:
                while True:
                    response = await client.get(
                        f"https://api.github.com/repos/{repo_full_name}/pulls",
                        headers={
                            "Authorization": f"Bearer {access_token}",
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
                                "files_changed": [],
                                "work_item_refs": [],
                                "created_at": pr["created_at"],
                                "merged_at": pr.get("merged_at"),
                                "reviewers": [r["login"] for r in pr.get("requested_reviewers", [])],
                                "workspace_id": workspace_id,
                            }
                            await upsert_pull_request(pr_data, workspace_id)
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
