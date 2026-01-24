"""
Linear sync module - fetches issues from Linear GraphQL API.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.ingest.normalize import normalize_linear_issue
from backend.storage.postgres import upsert_work_item, upsert_relationship
from backend.sync.base import (
    SyncResult,
    get_env_token,
    get_last_sync_time,
    set_last_sync_time,
    get_sync_cursor,
    set_sync_cursor,
)

LINEAR_API_URL = "https://api.linear.app/graphql"

ISSUES_QUERY = """
query Issues($updatedAfter: DateTime, $after: String) {
    issues(
        filter: { updatedAt: { gt: $updatedAfter } }
        first: 50
        after: $after
        orderBy: updatedAt
    ) {
        pageInfo {
            hasNextPage
            endCursor
        }
        nodes {
            id
            identifier
            title
            description
            url
            createdAt
            updatedAt
            state {
                id
                name
                type
            }
            team {
                id
                name
                key
            }
            assignee {
                id
                name
                email
            }
            project {
                id
                name
            }
            labels {
                nodes {
                    id
                    name
                    color
                }
            }
            priority
            priorityLabel
        }
    }
}
"""


async def fetch_issues(
    token: str,
    updated_after: datetime,
    cursor: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    Fetch issues from Linear API.
    
    Returns:
        Tuple of (issues, next_cursor, has_more)
    """
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    
    variables: Dict[str, Any] = {
        "updatedAfter": updated_after.isoformat(),
    }
    if cursor:
        variables["after"] = cursor
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            LINEAR_API_URL,
            headers=headers,
            json={"query": ISSUES_QUERY, "variables": variables},
        )
        response.raise_for_status()
        
        data = response.json()
        
        if "errors" in data:
            errors = data["errors"]
            error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
            raise ValueError(f"Linear API error: {error_msg}")
        
        issues_data = data.get("data", {}).get("issues", {})
        nodes = issues_data.get("nodes", [])
        page_info = issues_data.get("pageInfo", {})
        
        has_next = page_info.get("hasNextPage", False)
        end_cursor = page_info.get("endCursor")
        
        return nodes, end_cursor, has_next


async def sync_linear(
    team_keys: Optional[List[str]] = None,
    lookback_days: int = 7,
) -> SyncResult:
    """
    Sync issues from Linear.
    
    Args:
        team_keys: Optional list of team keys to filter by (not implemented in query).
        lookback_days: Number of days to look back for initial sync.
    
    Returns:
        SyncResult with sync statistics.
    """
    result = SyncResult("linear")
    
    token = get_env_token("linear")
    if not token:
        result.add_error("LINEAR_ACCESS_TOKEN not set")
        result.finish()
        return result
    
    # Get last sync time
    since = await get_last_sync_time("linear", default_days=lookback_days)
    
    # Get cursor from previous incomplete sync (if any)
    cursor = await get_sync_cursor("linear", "issues_cursor")
    
    try:
        while True:
            issues, next_cursor, has_more = await fetch_issues(token, since, cursor)
            
            for issue in issues:
                # Apply team filter if specified
                if team_keys:
                    team = issue.get("team", {})
                    team_key = team.get("key") if isinstance(team, dict) else None
                    if team_key and team_key not in team_keys:
                        continue
                
                # Normalize and store
                work_item, relationships = await normalize_linear_issue(issue)
                
                # Upsert work item
                await upsert_work_item(work_item.model_dump())
                
                # Upsert relationships
                for rel in relationships:
                    await upsert_relationship(rel.model_dump())
                
                result.items_synced += 1
            
            # Save cursor for resumption
            if next_cursor:
                await set_sync_cursor("linear", next_cursor, "issues_cursor")
            
            if not has_more:
                break
            
            cursor = next_cursor
        
        # Clear cursor on successful completion
        await set_sync_cursor("linear", None, "issues_cursor")
        
        # Update last sync time
        await set_last_sync_time("linear")
    
    except httpx.HTTPStatusError as e:
        result.add_error(f"Linear API error: {e.response.status_code}")
    except ValueError as e:
        result.add_error(str(e))
    except Exception as e:
        result.add_error(f"Error syncing Linear: {str(e)}")
    
    result.finish()
    return result

