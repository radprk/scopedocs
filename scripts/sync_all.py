#!/usr/bin/env python3
"""
One command to sync everything for a tenant.
Usage: python scripts/sync_all.py --tenant acme
"""
import asyncio
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

# Import sync functions from other scripts
from pull_linear import fetch_linear_issues, store_issues, create_links_from_issues
from pull_github import fetch_github_prs, store_prs, create_links_from_prs
from pull_slack import fetch_slack_messages, store_messages, create_links_from_messages

import asyncpg


def parse_supabase_dsn(dsn):
    import re
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


async def sync_all(tenant: str = "default"):
    """Sync all data sources for a tenant."""

    # For MVP: just use default env vars
    # For multi-tenant: prefix with tenant name
    prefix = f"{tenant.upper()}_" if tenant != "default" else ""

    linear_key = os.environ.get(f'{prefix}LINEAR_API_KEY') or os.environ.get('LINEAR_API_KEY')
    github_token = os.environ.get(f'{prefix}GITHUB_TOKEN') or os.environ.get('GITHUB_TOKEN')
    github_repos = os.environ.get(f'{prefix}GITHUB_REPOS') or os.environ.get('GITHUB_REPOS', '')
    slack_token = os.environ.get(f'{prefix}SLACK_BOT_TOKEN') or os.environ.get('SLACK_BOT_TOKEN')
    slack_channels = os.environ.get(f'{prefix}SLACK_CHANNELS') or os.environ.get('SLACK_CHANNELS', '')
    dsn = os.environ.get('POSTGRES_DSN')

    print(f"🔄 Syncing all data for tenant: {tenant}")
    print("=" * 50)

    # Connect to database
    db_config = parse_supabase_dsn(dsn)
    conn = await asyncpg.connect(**db_config)

    results = {
        "linear_issues": 0,
        "github_prs": 0,
        "slack_messages": 0,
        "links": 0
    }

    # Sync Linear
    if linear_key:
        print("\n📋 Syncing Linear...")
        try:
            issues = await fetch_linear_issues(linear_key)
            stored = await store_issues(conn, issues)
            links = await create_links_from_issues(conn, issues)
            results["linear_issues"] = stored
            results["links"] += links
            print(f"   ✅ {stored} issues, {links} links")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    else:
        print("\n⏭️  Skipping Linear (no API key)")

    # Sync GitHub
    if github_token and github_repos:
        print("\n🐙 Syncing GitHub...")
        for repo in github_repos.split(','):
            repo = repo.strip()
            if not repo:
                continue
            try:
                prs = await fetch_github_prs(github_token, repo)
                stored = await store_prs(conn, prs, repo)
                links = await create_links_from_prs(conn, prs, repo)
                results["github_prs"] += stored
                results["links"] += links
                print(f"   ✅ {repo}: {stored} PRs, {links} links")
            except Exception as e:
                print(f"   ❌ {repo}: {e}")
    else:
        print("\n⏭️  Skipping GitHub (no token or repos)")

    # Sync Slack
    if slack_token and slack_channels:
        print("\n💬 Syncing Slack...")
        for channel in slack_channels.split(','):
            channel = channel.strip()
            if not channel:
                continue
            try:
                messages = await fetch_slack_messages(slack_token, channel, days=30)
                stored = await store_messages(conn, messages)
                links = await create_links_from_messages(conn, messages)
                results["slack_messages"] += stored
                results["links"] += links
                print(f"   ✅ #{channel}: {stored} messages, {links} links")
            except Exception as e:
                print(f"   ❌ #{channel}: {e}")
    else:
        print("\n⏭️  Skipping Slack (no token or channels)")

    await conn.close()

    print("\n" + "=" * 50)
    print("✅ Sync complete!")
    print(f"   Linear issues: {results['linear_issues']}")
    print(f"   GitHub PRs: {results['github_prs']}")
    print(f"   Slack messages: {results['slack_messages']}")
    print(f"   Links created: {results['links']}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sync all data sources')
    parser.add_argument('--tenant', default='default', help='Tenant name (default: default)')
    args = parser.parse_args()

    asyncio.run(sync_all(args.tenant))
