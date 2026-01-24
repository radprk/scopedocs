#!/usr/bin/env python3
"""
Pull PRs from GitHub and store in Supabase.
Run: python scripts/pull_github.py --repo org/repo-name

Requires: GITHUB_TOKEN in your .env file
Get it from: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
"""
import asyncio
import os
import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

import httpx
import asyncpg

GITHUB_API_URL = "https://api.github.com"


def parse_supabase_dsn(dsn):
    """Parse Supabase DSN into components (asyncpg struggles with the format)."""
    pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
    match = re.match(pattern, dsn)
    if not match:
        raise ValueError(f"Invalid DSN format: {dsn}")
    return {
        'user': match.group(1),
        'password': match.group(2),
        'host': match.group(3),
        'port': int(match.group(4)),
        'database': match.group(5),
    }


def extract_issue_refs(text: str) -> List[str]:
    """Extract Linear issue references like ENG-123 from text."""
    if not text:
        return []
    pattern = r'\b[A-Z]{2,10}-\d+\b'
    return list(set(re.findall(pattern, text)))


async def fetch_github_prs(token: str, repo: str, state: str = "all", max_prs: int = 100) -> List[Dict[str, Any]]:
    """Fetch PRs from GitHub API."""
    prs = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while len(prs) < max_prs:
            response = await client.get(
                f"{GITHUB_API_URL}/repos/{repo}/pulls",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                params={
                    "state": state,
                    "per_page": min(100, max_prs - len(prs)),
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                },
            )

            if response.status_code == 404:
                print(f"❌ Repository not found: {repo}")
                print("   Make sure the repo exists and your token has access")
                break

            if response.status_code == 401:
                print(f"❌ Authentication failed. Check your GITHUB_TOKEN")
                break

            if response.status_code != 200:
                print(f"❌ GitHub API error: {response.status_code}")
                print(f"   {response.text[:200]}")
                break

            data = response.json()

            if not data:
                break

            prs.extend(data)
            print(f"   Fetched {len(prs)} PRs...")

            if len(data) < 100:
                break

            page += 1

    return prs


async def fetch_pr_files(client: httpx.AsyncClient, token: str, repo: str, pr_number: int) -> List[str]:
    """Fetch files changed in a PR."""
    try:
        response = await client.get(
            f"{GITHUB_API_URL}/repos/{repo}/pulls/{pr_number}/files",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            params={"per_page": 100},
        )
        if response.status_code == 200:
            return [f["filename"] for f in response.json()]
    except:
        pass
    return []


async def store_prs(conn: asyncpg.Connection, prs: List[Dict[str, Any]], repo: str, token: str) -> int:
    """Store PRs in Supabase."""
    stored = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for pr in prs:
            try:
                # Fetch files changed
                files = await fetch_pr_files(client, token, repo, pr["number"])

                # Extract reviewers
                reviewers = [r["login"] for r in pr.get("requested_reviewers", [])]

                # Extract labels
                labels = [l["name"] for l in pr.get("labels", [])]

                await conn.execute("""
                    INSERT INTO github_prs (
                        id, number, repo, title, body, state, author,
                        reviewers, labels, files_changed, additions, deletions,
                        created_at, merged_at, closed_at, raw_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    ON CONFLICT (repo, number) DO UPDATE SET
                        title = EXCLUDED.title,
                        body = EXCLUDED.body,
                        state = EXCLUDED.state,
                        reviewers = EXCLUDED.reviewers,
                        labels = EXCLUDED.labels,
                        files_changed = EXCLUDED.files_changed,
                        additions = EXCLUDED.additions,
                        deletions = EXCLUDED.deletions,
                        merged_at = EXCLUDED.merged_at,
                        closed_at = EXCLUDED.closed_at,
                        raw_data = EXCLUDED.raw_data,
                        synced_at = NOW()
                """,
                    str(pr["id"]),
                    pr["number"],
                    repo,
                    pr["title"],
                    pr.get("body"),
                    "merged" if pr.get("merged_at") else pr["state"],
                    pr["user"]["login"],
                    reviewers,
                    labels,
                    files,
                    pr.get("additions", 0),
                    pr.get("deletions", 0),
                    datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00")) if pr.get("created_at") else None,
                    datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")) if pr.get("merged_at") else None,
                    datetime.fromisoformat(pr["closed_at"].replace("Z", "+00:00")) if pr.get("closed_at") else None,
                    json.dumps(pr),
                )
                stored += 1

            except Exception as e:
                print(f"   ⚠️  Error storing PR #{pr.get('number')}: {e}")

    return stored


async def create_links_from_prs(conn: asyncpg.Connection, prs: List[Dict[str, Any]], repo: str) -> int:
    """Create links between PRs and Linear issues."""
    links_created = 0

    for pr in prs:
        # Combine title and body for searching
        text = f"{pr.get('title', '')} {pr.get('body', '') or ''}"

        # Find Linear issue references
        for issue_ref in extract_issue_refs(text):
            try:
                await conn.execute("""
                    INSERT INTO links (source_type, source_id, target_type, target_id, link_type, context)
                    VALUES ('github_pr', $1, 'linear_issue', $2, 'implements', $3)
                    ON CONFLICT DO NOTHING
                """, f"{repo}#{pr['number']}", issue_ref, text[:200])
                links_created += 1
            except:
                pass

    return links_created


async def main():
    parser = argparse.ArgumentParser(description="Pull PRs from GitHub")
    parser.add_argument("--repo", "-r", required=True, help="Repository (e.g., org/repo-name)")
    parser.add_argument("--state", "-s", default="all", choices=["open", "closed", "all"], help="PR state filter")
    parser.add_argument("--max", "-m", type=int, default=100, help="Max PRs to fetch")
    args = parser.parse_args()

    token = os.environ.get('GITHUB_TOKEN')
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')

    if not token:
        print("❌ ERROR: GITHUB_TOKEN not set!")
        print("")
        print("To get your GitHub token:")
        print("   1. Go to GitHub → Settings → Developer settings")
        print("   2. Click 'Personal access tokens' → 'Tokens (classic)'")
        print("   3. Click 'Generate new token (classic)'")
        print("   4. Select scope: 'repo' (for private repos) or 'public_repo' (for public only)")
        print("   5. Copy the token and add to backend/.env:")
        print("")
        print('   GITHUB_TOKEN=ghp_xxxxxxxxxxxxx')
        return False

    if not dsn:
        print("❌ ERROR: POSTGRES_DSN not set!")
        return False

    print(f"🔄 Pulling PRs from GitHub: {args.repo}")
    print(f"   State: {args.state}, Max: {args.max}")
    print("")

    try:
        # Fetch from GitHub
        prs = await fetch_github_prs(token, args.repo, args.state, args.max)
        print(f"✅ Fetched {len(prs)} PRs from GitHub")

        if not prs:
            print("   No PRs found.")
            return True

        # Store in Supabase
        print("")
        print("💾 Storing in Supabase...")
        db_config = parse_supabase_dsn(dsn)
        conn = await asyncpg.connect(**db_config)

        stored = await store_prs(conn, prs, args.repo, token)
        print(f"✅ Stored {stored} PRs")

        # Create links
        print("")
        print("🔗 Creating links to Linear issues...")
        links = await create_links_from_prs(conn, prs, args.repo)
        print(f"✅ Created {links} links")

        await conn.close()

        print("")
        print("=" * 50)
        print("✅ GitHub sync complete!")
        print(f"   PRs: {stored}")
        print(f"   Links to Linear: {links}")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
