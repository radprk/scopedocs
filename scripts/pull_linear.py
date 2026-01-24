#!/usr/bin/env python3
"""
Pull issues from Linear and store in Supabase.
Run: python scripts/pull_linear.py

Requires: LINEAR_API_KEY in your .env file
Get it from: Linear → Settings → API → Personal API keys
"""
import asyncio
import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

import httpx
import asyncpg

LINEAR_API_URL = "https://api.linear.app/graphql"

# GraphQL query to fetch issues
ISSUES_QUERY = """
query Issues($first: Int!, $after: String) {
    issues(first: $first, after: $after, orderBy: updatedAt) {
        pageInfo {
            hasNextPage
            endCursor
        }
        nodes {
            id
            identifier
            title
            description
            priority
            priorityLabel
            createdAt
            updatedAt
            state {
                name
                type
            }
            assignee {
                name
                email
            }
            team {
                name
                key
            }
            project {
                name
            }
            labels {
                nodes {
                    name
                }
            }
            comments {
                nodes {
                    body
                    user {
                        name
                    }
                    createdAt
                }
            }
        }
    }
}
"""


def extract_issue_refs(text: str) -> List[str]:
    """Extract Linear issue references like ENG-123, PROD-456 from text."""
    if not text:
        return []
    pattern = r'\b[A-Z]{2,10}-\d+\b'
    return list(set(re.findall(pattern, text)))


def extract_pr_refs(text: str) -> List[str]:
    """Extract GitHub PR references like #123 or repo#123 from text."""
    if not text:
        return []
    pattern = r'(?:[\w-]+/[\w-]+)?#(\d+)'
    return list(set(re.findall(pattern, text)))


async def fetch_linear_issues(api_key: str, max_issues: int = 500) -> List[Dict[str, Any]]:
    """Fetch issues from Linear API."""
    issues = []
    cursor = None

    async with httpx.AsyncClient(timeout=30) as client:
        while len(issues) < max_issues:
            variables = {"first": min(50, max_issues - len(issues))}
            if cursor:
                variables["after"] = cursor

            response = await client.post(
                LINEAR_API_URL,
                headers={
                    "Authorization": api_key,
                    "Content-Type": "application/json",
                },
                json={"query": ISSUES_QUERY, "variables": variables},
            )

            if response.status_code != 200:
                print(f"❌ Linear API error: {response.status_code}")
                print(f"   {response.text[:200]}")
                break

            data = response.json()

            if "errors" in data:
                print(f"❌ GraphQL errors: {data['errors']}")
                break

            page = data.get("data", {}).get("issues", {})
            nodes = page.get("nodes", [])

            if not nodes:
                break

            issues.extend(nodes)
            print(f"   Fetched {len(issues)} issues...")

            if not page.get("pageInfo", {}).get("hasNextPage"):
                break

            cursor = page.get("pageInfo", {}).get("endCursor")

    return issues


async def store_issues(conn: asyncpg.Connection, issues: List[Dict[str, Any]]) -> int:
    """Store issues in Supabase."""
    stored = 0

    for issue in issues:
        try:
            # Extract fields
            labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]

            await conn.execute("""
                INSERT INTO linear_issues (
                    id, identifier, title, description, status, priority,
                    assignee_name, team_name, project_name, labels,
                    created_at, updated_at, raw_data
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    assignee_name = EXCLUDED.assignee_name,
                    team_name = EXCLUDED.team_name,
                    project_name = EXCLUDED.project_name,
                    labels = EXCLUDED.labels,
                    updated_at = EXCLUDED.updated_at,
                    raw_data = EXCLUDED.raw_data,
                    synced_at = NOW()
            """,
                issue["id"],
                issue["identifier"],
                issue["title"],
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
            )
            stored += 1

        except Exception as e:
            print(f"   ⚠️  Error storing {issue.get('identifier')}: {e}")

    return stored


async def create_links_from_issues(conn: asyncpg.Connection, issues: List[Dict[str, Any]]) -> int:
    """Create links between issues based on mentions in description/comments."""
    links_created = 0

    for issue in issues:
        # Check description for references
        description = issue.get("description", "") or ""

        # Find references to other issues
        for ref in extract_issue_refs(description):
            if ref != issue["identifier"]:  # Don't link to self
                try:
                    await conn.execute("""
                        INSERT INTO links (source_type, source_id, target_type, target_id, link_type, context)
                        VALUES ('linear_issue', $1, 'linear_issue', $2, 'mentions', $3)
                        ON CONFLICT DO NOTHING
                    """, issue["identifier"], ref, description[:200])
                    links_created += 1
                except:
                    pass

        # Find references to PRs
        for pr_num in extract_pr_refs(description):
            try:
                await conn.execute("""
                    INSERT INTO links (source_type, source_id, target_type, target_id, link_type, context)
                    VALUES ('linear_issue', $1, 'github_pr', $2, 'mentions', $3)
                    ON CONFLICT DO NOTHING
                """, issue["identifier"], pr_num, description[:200])
                links_created += 1
            except:
                pass

    return links_created


async def main():
    api_key = os.environ.get('LINEAR_API_KEY')
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')

    if not api_key:
        print("❌ ERROR: LINEAR_API_KEY not set!")
        print("")
        print("To get your Linear API key:")
        print("   1. Open Linear")
        print("   2. Go to Settings (gear icon)")
        print("   3. Click 'API' in the sidebar")
        print("   4. Under 'Personal API keys', click 'Create key'")
        print("   5. Copy the key and add to backend/.env:")
        print("")
        print('   LINEAR_API_KEY=lin_api_xxxxxxxxxxxxx')
        return False

    if not dsn:
        print("❌ ERROR: POSTGRES_DSN not set!")
        return False

    print("🔄 Pulling issues from Linear...")
    print("")

    try:
        # Fetch from Linear
        issues = await fetch_linear_issues(api_key)
        print(f"✅ Fetched {len(issues)} issues from Linear")

        if not issues:
            print("   No issues found. Make sure your API key has access to issues.")
            return True

        # Store in Supabase
        print("")
        print("💾 Storing in Supabase...")
        conn = await asyncpg.connect(dsn)

        stored = await store_issues(conn, issues)
        print(f"✅ Stored {stored} issues")

        # Create links
        print("")
        print("🔗 Creating links...")
        links = await create_links_from_issues(conn, issues)
        print(f"✅ Created {links} links")

        await conn.close()

        print("")
        print("=" * 50)
        print("✅ Linear sync complete!")
        print(f"   Issues: {stored}")
        print(f"   Links: {links}")
        print("")
        print("Next: Check your Supabase Table Editor to see the data!")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
