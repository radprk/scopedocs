#!/usr/bin/env python3
"""
Pull messages from Slack and store in Supabase.
Run: python scripts/pull_slack.py --channel general

Requires: SLACK_BOT_TOKEN in your .env file
Get it from: api.slack.com/apps → Your App → OAuth & Permissions → Bot User OAuth Token
"""
import asyncio
import os
import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

import httpx
import asyncpg

SLACK_API_URL = "https://slack.com/api"


def extract_issue_refs(text: str) -> List[str]:
    """Extract Linear issue references like ENG-123 from text."""
    if not text:
        return []
    pattern = r'\b[A-Z]{2,10}-\d+\b'
    return list(set(re.findall(pattern, text)))


def extract_pr_refs(text: str) -> List[str]:
    """Extract GitHub PR references from text."""
    if not text:
        return []
    # Match #123 or repo#123 or full GitHub PR URLs
    patterns = [
        r'github\.com/[\w-]+/[\w-]+/pull/(\d+)',  # Full URL
        r'(?:[\w-]+/[\w-]+)?#(\d+)',  # #123 or org/repo#123
    ]
    refs = []
    for pattern in patterns:
        refs.extend(re.findall(pattern, text))
    return list(set(refs))


async def slack_api(client: httpx.AsyncClient, token: str, method: str, **params) -> Dict[str, Any]:
    """Make a Slack API call."""
    response = await client.post(
        f"{SLACK_API_URL}/{method}",
        headers={"Authorization": f"Bearer {token}"},
        data=params,
    )
    data = response.json()
    if not data.get("ok"):
        error = data.get("error", "Unknown error")
        print(f"   ⚠️  Slack API error ({method}): {error}")
    return data


async def get_channel_id(client: httpx.AsyncClient, token: str, channel_name: str) -> Optional[str]:
    """Get channel ID from name."""
    # Remove # if present
    channel_name = channel_name.lstrip("#")

    # Try to find in public channels
    data = await slack_api(client, token, "conversations.list", types="public_channel,private_channel", limit=1000)

    if data.get("ok"):
        for channel in data.get("channels", []):
            if channel["name"] == channel_name:
                return channel["id"]

    print(f"   Channel '{channel_name}' not found. Make sure the bot is invited to the channel.")
    return None


async def fetch_channel_messages(client: httpx.AsyncClient, token: str, channel_id: str, channel_name: str, days: int = 30) -> List[Dict[str, Any]]:
    """Fetch messages from a channel."""
    messages = []
    oldest = (datetime.now() - timedelta(days=days)).timestamp()
    cursor = None

    while True:
        params = {
            "channel": channel_id,
            "oldest": oldest,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        data = await slack_api(client, token, "conversations.history", **params)

        if not data.get("ok"):
            break

        for msg in data.get("messages", []):
            # Only include messages with text (not system messages)
            if msg.get("type") == "message" and msg.get("text"):
                msg["_channel_id"] = channel_id
                msg["_channel_name"] = channel_name
                messages.append(msg)

        print(f"   Fetched {len(messages)} messages...")

        if not data.get("has_more"):
            break

        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return messages


async def fetch_thread_replies(client: httpx.AsyncClient, token: str, channel_id: str, thread_ts: str) -> List[Dict[str, Any]]:
    """Fetch all replies in a thread."""
    data = await slack_api(client, token, "conversations.replies", channel=channel_id, ts=thread_ts, limit=200)
    if data.get("ok"):
        return data.get("messages", [])
    return []


async def get_user_name(client: httpx.AsyncClient, token: str, user_id: str, user_cache: Dict[str, str]) -> str:
    """Get user display name from ID."""
    if user_id in user_cache:
        return user_cache[user_id]

    data = await slack_api(client, token, "users.info", user=user_id)
    if data.get("ok"):
        user = data.get("user", {})
        name = user.get("real_name") or user.get("name") or user_id
        user_cache[user_id] = name
        return name

    user_cache[user_id] = user_id
    return user_id


async def store_messages(conn: asyncpg.Connection, messages: List[Dict[str, Any]], client: httpx.AsyncClient, token: str) -> int:
    """Store messages in Supabase."""
    stored = 0
    user_cache = {}

    # Group messages by thread
    threads = {}
    for msg in messages:
        thread_ts = msg.get("thread_ts") or msg.get("ts")
        if thread_ts not in threads:
            threads[thread_ts] = {
                "channel_id": msg["_channel_id"],
                "channel_name": msg["_channel_name"],
                "thread_ts": thread_ts,
                "messages": [],
                "participants": set(),
                "first_msg": msg,
            }
        threads[thread_ts]["messages"].append(msg)
        if msg.get("user"):
            threads[thread_ts]["participants"].add(msg["user"])

    for thread_ts, thread in threads.items():
        try:
            # Get user names
            user_name = await get_user_name(client, token, thread["first_msg"].get("user", ""), user_cache)
            participants = [await get_user_name(client, token, u, user_cache) for u in thread["participants"]]

            # If it's a thread with replies, fetch full thread
            if thread["first_msg"].get("reply_count", 0) > 0:
                full_thread = await fetch_thread_replies(client, token, thread["channel_id"], thread_ts)
                if full_thread:
                    thread["messages"] = full_thread
                    thread["participants"] = set(m.get("user") for m in full_thread if m.get("user"))
                    participants = [await get_user_name(client, token, u, user_cache) for u in thread["participants"]]

            await conn.execute("""
                INSERT INTO slack_messages (
                    id, channel_id, channel_name, thread_ts, message_text,
                    user_id, user_name, reply_count, participants,
                    thread_messages, created_at, raw_data
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (channel_id, thread_ts) DO UPDATE SET
                    message_text = EXCLUDED.message_text,
                    reply_count = EXCLUDED.reply_count,
                    participants = EXCLUDED.participants,
                    thread_messages = EXCLUDED.thread_messages,
                    raw_data = EXCLUDED.raw_data,
                    synced_at = NOW()
            """,
                f"{thread['channel_id']}_{thread_ts}",
                thread["channel_id"],
                thread["channel_name"],
                thread_ts,
                thread["first_msg"].get("text"),
                thread["first_msg"].get("user"),
                user_name,
                thread["first_msg"].get("reply_count", 0),
                participants,
                json.dumps(thread["messages"]),
                datetime.fromtimestamp(float(thread_ts)),
                json.dumps(thread["first_msg"]),
            )
            stored += 1

        except Exception as e:
            print(f"   ⚠️  Error storing thread {thread_ts}: {e}")

    return stored


async def create_links_from_messages(conn: asyncpg.Connection, messages: List[Dict[str, Any]]) -> int:
    """Create links between Slack messages and Linear issues/PRs."""
    links_created = 0

    # Group by thread
    threads = {}
    for msg in messages:
        thread_ts = msg.get("thread_ts") or msg.get("ts")
        if thread_ts not in threads:
            threads[thread_ts] = {"channel_id": msg["_channel_id"], "texts": []}
        threads[thread_ts]["texts"].append(msg.get("text", ""))

    for thread_ts, thread in threads.items():
        combined_text = " ".join(thread["texts"])
        msg_id = f"{thread['channel_id']}_{thread_ts}"

        # Find Linear issue references
        for issue_ref in extract_issue_refs(combined_text):
            try:
                await conn.execute("""
                    INSERT INTO links (source_type, source_id, target_type, target_id, link_type, context)
                    VALUES ('slack_message', $1, 'linear_issue', $2, 'discusses', $3)
                    ON CONFLICT DO NOTHING
                """, msg_id, issue_ref, combined_text[:200])
                links_created += 1
            except:
                pass

        # Find PR references
        for pr_ref in extract_pr_refs(combined_text):
            try:
                await conn.execute("""
                    INSERT INTO links (source_type, source_id, target_type, target_id, link_type, context)
                    VALUES ('slack_message', $1, 'github_pr', $2, 'discusses', $3)
                    ON CONFLICT DO NOTHING
                """, msg_id, pr_ref, combined_text[:200])
                links_created += 1
            except:
                pass

    return links_created


async def main():
    parser = argparse.ArgumentParser(description="Pull messages from Slack")
    parser.add_argument("--channel", "-c", required=True, help="Channel name (e.g., general)")
    parser.add_argument("--days", "-d", type=int, default=30, help="Days of history to fetch")
    args = parser.parse_args()

    token = os.environ.get('SLACK_BOT_TOKEN')
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')

    if not token:
        print("❌ ERROR: SLACK_BOT_TOKEN not set!")
        print("")
        print("To get your Slack Bot Token:")
        print("   1. Go to api.slack.com/apps")
        print("   2. Create a new app (or select existing)")
        print("   3. Go to 'OAuth & Permissions'")
        print("   4. Under 'Bot Token Scopes', add:")
        print("      - channels:history")
        print("      - channels:read")
        print("      - groups:history (for private channels)")
        print("      - groups:read")
        print("      - users:read")
        print("   5. Install the app to your workspace")
        print("   6. Copy 'Bot User OAuth Token' (starts with xoxb-)")
        print("   7. Add to backend/.env:")
        print("")
        print('   SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxxx')
        print("")
        print("   8. Invite the bot to channels: /invite @YourBotName")
        return False

    if not dsn:
        print("❌ ERROR: POSTGRES_DSN not set!")
        return False

    print(f"🔄 Pulling messages from Slack: #{args.channel}")
    print(f"   Last {args.days} days")
    print("")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Get channel ID
            channel_id = await get_channel_id(client, token, args.channel)
            if not channel_id:
                return False

            print(f"   Found channel: {channel_id}")

            # Fetch messages
            messages = await fetch_channel_messages(client, token, channel_id, args.channel, args.days)
            print(f"✅ Fetched {len(messages)} messages from Slack")

            if not messages:
                print("   No messages found in the specified time range.")
                return True

            # Store in Supabase
            print("")
            print("💾 Storing in Supabase...")
            conn = await asyncpg.connect(dsn)

            stored = await store_messages(conn, messages, client, token)
            print(f"✅ Stored {stored} message threads")

            # Create links
            print("")
            print("🔗 Creating links to Linear issues and PRs...")
            links = await create_links_from_messages(conn, messages)
            print(f"✅ Created {links} links")

            await conn.close()

        print("")
        print("=" * 50)
        print("✅ Slack sync complete!")
        print(f"   Message threads: {stored}")
        print(f"   Links: {links}")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
