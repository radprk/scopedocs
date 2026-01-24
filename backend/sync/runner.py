"""
CLI runner for daily sync operations.

Usage:
    python -m backend.sync.runner --source github
    python -m backend.sync.runner --source slack
    python -m backend.sync.runner --source linear
    python -m backend.sync.runner --all
"""

import argparse
import asyncio
import sys
from typing import List

from dotenv import load_dotenv

from backend.storage.postgres import init_pg, close_pool
from backend.sync.base import SyncResult


async def run_github_sync(repos: List[str], days: int) -> SyncResult:
    """Run GitHub sync."""
    from backend.sync.sync_github import sync_github
    return await sync_github(repos=repos, lookback_days=days)


async def run_slack_sync(channels: List[str], days: int) -> SyncResult:
    """Run Slack sync."""
    from backend.sync.sync_slack import sync_slack
    return await sync_slack(channels=channels, lookback_days=days)


async def run_linear_sync(days: int) -> SyncResult:
    """Run Linear sync."""
    from backend.sync.sync_linear import sync_linear
    return await sync_linear(lookback_days=days)


async def run_sync(
    sources: List[str],
    repos: List[str],
    channels: List[str],
    days: int,
) -> List[SyncResult]:
    """Run sync for specified sources."""
    await init_pg()
    
    results: List[SyncResult] = []
    
    try:
        if "github" in sources:
            print(f"Syncing GitHub ({len(repos)} repos, last {days} days)...")
            result = await run_github_sync(repos, days)
            results.append(result)
            print(f"  {result}")
        
        if "slack" in sources:
            print(f"Syncing Slack ({len(channels)} channels, last {days} days)...")
            result = await run_slack_sync(channels, days)
            results.append(result)
            print(f"  {result}")
        
        if "linear" in sources:
            print(f"Syncing Linear (last {days} days)...")
            result = await run_linear_sync(days)
            results.append(result)
            print(f"  {result}")
    
    finally:
        await close_pool()
    
    return results


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run daily sync for GitHub, Slack, and Linear integrations"
    )
    parser.add_argument(
        "--source",
        choices=["github", "slack", "linear"],
        help="Sync a specific source",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync all sources",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=[],
        help="GitHub repos to sync (e.g., owner/repo)",
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        default=[],
        help="Slack channel IDs to sync",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    load_dotenv()
    args = parse_args()
    
    if not args.source and not args.all:
        print("Error: Must specify --source or --all")
        return 1
    
    sources = []
    if args.all:
        sources = ["github", "slack", "linear"]
    elif args.source:
        sources = [args.source]
    
    # Validate required config
    if "github" in sources and not args.repos:
        print("Warning: No --repos specified for GitHub sync. Use --repos owner/repo")
    
    if "slack" in sources and not args.channels:
        print("Warning: No --channels specified for Slack sync. Use --channels C12345")
    
    results = asyncio.run(run_sync(
        sources=sources,
        repos=args.repos,
        channels=args.channels,
        days=args.days,
    ))
    
    print("\n--- Sync Summary ---")
    for result in results:
        print(f"  {result}")
        if result.errors:
            for error in result.errors[:5]:
                print(f"    - {error}")
    
    # Return non-zero if any sync failed
    if any(not r.success for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

