"""
Data sync functions - pull data from integrations for a workspace.
All data is scoped to workspaces, not individual users.
"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID

import httpx
import asyncpg


# ============ LINEAR SYNC ============

ISSUES_QUERY = """
query Issues($first: Int!, $after: String) {
    issues(first: $first, after: $after, orderBy: updatedAt) {
        pageInfo { hasNextPage endCursor }
        nodes {
            id identifier title description priority priorityLabel
            createdAt updatedAt
            state { name type }
            assignee { name email }
            team { name key }
            project { name }
            labels { nodes { name } }
        }
    }
}
"""


async def sync_linear(conn: asyncpg.Connection, workspace_id: UUID, access_token: str, max_issues: int = 500) -> int:
    """Pull issues from Linear and store them for a workspace."""
    workspace_id_str = str(workspace_id)  # Convert UUID to string for DB
    issues = []
    cursor = None

    async with httpx.AsyncClient(timeout=30) as client:
        while len(issues) < max_issues:
            variables = {"first": min(50, max_issues - len(issues))}
            if cursor:
                variables["after"] = cursor

            response = await client.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": access_token, "Content-Type": "application/json"},
                json={"query": ISSUES_QUERY, "variables": variables},
            )

            if response.status_code != 200:
                raise Exception(f"Linear API error: {response.status_code}")

            data = response.json()
            if "errors" in data:
                raise Exception(f"GraphQL errors: {data['errors']}")

            page = data.get("data", {}).get("issues", {})
            nodes = page.get("nodes", [])
            if not nodes:
                break

            issues.extend(nodes)

            if not page.get("pageInfo", {}).get("hasNextPage"):
                break
            cursor = page.get("pageInfo", {}).get("endCursor")

    # Store issues
    stored = 0
    for issue in issues:
        try:
            labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
            await conn.execute("""
                INSERT INTO linear_issues (
                    id, identifier, title, description, status, priority,
                    assignee_name, team_name, project_name, labels,
                    created_at, updated_at, raw_data, workspace_id, synced_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::uuid, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title, description = EXCLUDED.description,
                    status = EXCLUDED.status, priority = EXCLUDED.priority,
                    assignee_name = EXCLUDED.assignee_name, team_name = EXCLUDED.team_name,
                    labels = EXCLUDED.labels, updated_at = EXCLUDED.updated_at,
                    raw_data = EXCLUDED.raw_data, synced_at = NOW()
            """,
                issue["id"], issue["identifier"], issue["title"],
                issue.get("description"),
                issue.get("state", {}).get("name"),
                issue.get("priorityLabel"),
                issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
                issue.get("team", {}).get("name") if issue.get("team") else None,
                issue.get("project", {}).get("name") if issue.get("project") else None,
                labels,
                datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00")) if issue.get("createdAt") else None,
                datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00")) if issue.get("updatedAt") else None,
                json.dumps(issue),
                workspace_id_str,
            )
            stored += 1
        except Exception as e:
            print(f"Error storing issue {issue.get('identifier')}: {e}")

    return stored


# ============ GITHUB SYNC ============

async def sync_github(conn: asyncpg.Connection, workspace_id: UUID, access_token: str, repos: List[str], max_prs: int = 100) -> int:
    """Pull PRs from GitHub and store them for a workspace."""
    workspace_id_str = str(workspace_id)
    total_stored = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for repo in repos:
            repo = repo.strip()
            if not repo:
                continue

            response = await client.get(
                f"https://api.github.com/repos/{repo}/pulls",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"},
                params={"state": "all", "per_page": max_prs, "sort": "updated"},
            )

            if response.status_code != 200:
                print(f"GitHub API error for {repo}: {response.status_code}")
                continue

            prs = response.json()

            for pr in prs:
                try:
                    await conn.execute("""
                        INSERT INTO github_prs (
                            id, number, repo, title, body, state, author,
                            created_at, merged_at, closed_at, raw_data, workspace_id, synced_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::uuid, NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title, body = EXCLUDED.body,
                            state = EXCLUDED.state, merged_at = EXCLUDED.merged_at,
                            closed_at = EXCLUDED.closed_at, raw_data = EXCLUDED.raw_data,
                            synced_at = NOW()
                    """,
                        str(pr["id"]), pr["number"], repo, pr["title"],
                        pr.get("body"),
                        "merged" if pr.get("merged_at") else pr["state"],
                        pr.get("user", {}).get("login"),
                        datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00")) if pr.get("created_at") else None,
                        datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")) if pr.get("merged_at") else None,
                        datetime.fromisoformat(pr["closed_at"].replace("Z", "+00:00")) if pr.get("closed_at") else None,
                        json.dumps(pr),
                        workspace_id_str,
                    )
                    total_stored += 1
                except Exception as e:
                    print(f"Error storing PR {repo}#{pr['number']}: {e}")

    return total_stored


# ============ SLACK SYNC ============

async def sync_slack(conn: asyncpg.Connection, workspace_id: UUID, access_token: str, channels: List[str], days: int = 30) -> int:
    """Pull messages from Slack and store them for a workspace."""
    workspace_id_str = str(workspace_id)
    total_stored = 0
    oldest = (datetime.now() - timedelta(days=days)).timestamp()

    async with httpx.AsyncClient(timeout=30) as client:
        # Get channel list
        response = await client.get(
            "https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"types": "public_channel,private_channel", "limit": 200},
        )
        channel_list = response.json().get("channels", [])
        channel_map = {c["name"]: c["id"] for c in channel_list}

        for channel_name in channels:
            channel_name = channel_name.strip().lstrip('#')
            channel_id = channel_map.get(channel_name)
            if not channel_id:
                print(f"Channel '{channel_name}' not found")
                continue

            # Get messages
            response = await client.get(
                "https://slack.com/api/conversations.history",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"channel": channel_id, "oldest": oldest, "limit": 200},
            )
            data = response.json()
            if not data.get("ok"):
                print(f"Slack API error for {channel_name}: {data.get('error')}")
                continue

            messages = data.get("messages", [])

            for msg in messages:
                if msg.get("type") != "message":
                    continue

                try:
                    msg_id = f"{channel_id}-{msg['ts']}"
                    await conn.execute("""
                        INSERT INTO slack_messages (
                            id, channel_id, channel_name, thread_ts, message_text,
                            user_name, created_at, raw_data, workspace_id, synced_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::uuid, NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            message_text = EXCLUDED.message_text,
                            raw_data = EXCLUDED.raw_data, synced_at = NOW()
                    """,
                        msg_id, channel_id, channel_name,
                        msg.get("thread_ts", msg["ts"]),
                        msg.get("text"),
                        msg.get("user"),  # Slack user ID as user_name
                        datetime.fromtimestamp(float(msg["ts"])),
                        json.dumps(msg),
                        workspace_id_str,  # Owner workspace_id
                    )
                    total_stored += 1
                except Exception as e:
                    print(f"Error storing message: {e}")

    return total_stored


# ============ CREATE LINKS ============

def extract_issue_refs(text: str) -> List[str]:
    """Extract Linear issue references like ENG-123."""
    if not text:
        return []
    return list(set(re.findall(r'\b[A-Z]{2,10}-\d+\b', text)))


async def create_links(conn: asyncpg.Connection, workspace_id: UUID) -> int:
    """Create links between artifacts based on mentions for a workspace."""
    links_created = 0
    workspace_id_str = str(workspace_id)  # Convert UUID to string

    # Link PRs to Linear issues
    prs = await conn.fetch(
        "SELECT id, repo, number, title, body FROM github_prs WHERE workspace_id = $1::uuid",
        workspace_id_str
    )

    for pr in prs:
        text = f"{pr['title']} {pr['body'] or ''}"
        for ref in extract_issue_refs(text):
            try:
                await conn.execute("""
                    INSERT INTO links (source_type, source_id, target_type, target_id, link_type, workspace_id)
                    VALUES ('github_pr', $1, 'linear_issue', $2, 'implements', $3::uuid)
                    ON CONFLICT DO NOTHING
                """, f"{pr['repo']}#{pr['number']}", ref, workspace_id_str)
                links_created += 1
            except:
                pass

    # Link Slack messages to Linear issues
    messages = await conn.fetch(
        "SELECT id, message_text FROM slack_messages WHERE workspace_id = $1::uuid",
        workspace_id_str
    )

    for msg in messages:
        for ref in extract_issue_refs(msg['message_text'] or ''):
            try:
                await conn.execute("""
                    INSERT INTO links (source_type, source_id, target_type, target_id, link_type, workspace_id)
                    VALUES ('slack_message', $1, 'linear_issue', $2, 'discusses', $3::uuid)
                    ON CONFLICT DO NOTHING
                """, msg['id'], ref, workspace_id_str)
                links_created += 1
            except:
                pass

    return links_created
