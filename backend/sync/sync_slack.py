"""
Slack sync module - fetches conversation history from Slack API.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.ingest.normalize import normalize_slack_event
from backend.storage.postgres import upsert_conversation, upsert_relationship
from backend.sync.base import (
    SyncResult,
    get_env_token,
    get_last_sync_time,
    set_last_sync_time,
)

SLACK_API_BASE = "https://slack.com/api"


async def fetch_channel_history(
    channel: str,
    token: str,
    oldest: float,
    cursor: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Fetch conversation history from a Slack channel.
    
    Returns:
        Tuple of (messages, next_cursor)
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    params: Dict[str, Any] = {
        "channel": channel,
        "oldest": str(oldest),
        "limit": 200,
        "inclusive": True,
    }
    
    if cursor:
        params["cursor"] = cursor
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{SLACK_API_BASE}/conversations.history",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        
        data = response.json()
        if not data.get("ok"):
            raise ValueError(f"Slack API error: {data.get('error', 'unknown')}")
        
        messages = data.get("messages", [])
        next_cursor = data.get("response_metadata", {}).get("next_cursor")
        
        return messages, next_cursor if next_cursor else None


async def fetch_thread_replies(
    channel: str,
    thread_ts: str,
    token: str,
) -> List[Dict[str, Any]]:
    """Fetch all replies in a thread."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    params = {
        "channel": channel,
        "ts": thread_ts,
        "limit": 200,
    }
    
    all_replies: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            if cursor:
                params["cursor"] = cursor
            
            response = await client.get(
                f"{SLACK_API_BASE}/conversations.replies",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get("ok"):
                break
            
            messages = data.get("messages", [])
            # First message is the parent, skip it
            if messages and not cursor:
                messages = messages[1:]
            
            all_replies.extend(messages)
            
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    
    return all_replies


def group_messages_by_thread(messages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group messages by thread_ts or ts for standalone messages."""
    threads: Dict[str, List[Dict[str, Any]]] = {}
    
    for msg in messages:
        thread_ts = msg.get("thread_ts") or msg.get("ts")
        if thread_ts not in threads:
            threads[thread_ts] = []
        threads[thread_ts].append(msg)
    
    return threads


async def sync_slack(
    channels: Optional[List[str]] = None,
    lookback_days: int = 7,
) -> SyncResult:
    """
    Sync conversations from Slack channels.
    
    Args:
        channels: List of channel IDs. If None, uses SLACK_CHANNELS env var.
        lookback_days: Number of days to look back for initial sync.
    
    Returns:
        SyncResult with sync statistics.
    """
    result = SyncResult("slack")
    
    token = get_env_token("slack")
    if not token:
        result.add_error("SLACK_ACCESS_TOKEN not set")
        result.finish()
        return result
    
    # Get channels from args or env
    if not channels:
        channels_env = os.environ.get("SLACK_CHANNELS", "")
        channels = [c.strip() for c in channels_env.split(",") if c.strip()]
    
    if not channels:
        result.add_error("No channels specified. Set SLACK_CHANNELS or pass --channels")
        result.finish()
        return result
    
    # Get last sync time
    since = await get_last_sync_time("slack", default_days=lookback_days)
    oldest_ts = since.timestamp()
    
    for channel in channels:
        try:
            # Fetch all messages since last sync
            all_messages: List[Dict[str, Any]] = []
            cursor: Optional[str] = None
            
            while True:
                messages, cursor = await fetch_channel_history(
                    channel, token, oldest_ts, cursor
                )
                all_messages.extend(messages)
                
                if not cursor:
                    break
            
            # Group by thread
            threads = group_messages_by_thread(all_messages)
            
            for thread_ts, thread_messages in threads.items():
                # Check if this is a threaded conversation
                parent_msg = thread_messages[0] if thread_messages else {}
                has_replies = parent_msg.get("reply_count", 0) > 0
                
                # Fetch thread replies if it's a thread
                if has_replies:
                    try:
                        replies = await fetch_thread_replies(channel, thread_ts, token)
                        thread_messages.extend(replies)
                    except Exception:
                        pass  # Thread replies are optional
                
                # Process each message in the thread
                for msg in thread_messages:
                    # Add channel to message for normalize function
                    msg["channel"] = channel
                    
                    # Normalize and store
                    conversation, relationships = await normalize_slack_event(msg)
                    
                    # Build full messages list for the conversation
                    conversation.messages = [
                        {
                            "ts": m.get("ts"),
                            "user": m.get("user"),
                            "text": m.get("text", ""),
                            "thread_ts": m.get("thread_ts"),
                        }
                        for m in thread_messages
                    ]
                    
                    # Collect all participants
                    participants = list(set(
                        m.get("user") for m in thread_messages if m.get("user")
                    ))
                    conversation.participants = participants
                    
                    # Upsert conversation
                    await upsert_conversation(conversation.model_dump())
                    
                    # Upsert relationships
                    for rel in relationships:
                        await upsert_relationship(rel.model_dump())
                    
                    result.items_synced += 1
                    break  # Only create one conversation per thread
        
        except httpx.HTTPStatusError as e:
            result.add_error(f"Slack API error for {channel}: {e.response.status_code}")
        except ValueError as e:
            result.add_error(f"Slack error for {channel}: {str(e)}")
        except Exception as e:
            result.add_error(f"Error syncing {channel}: {str(e)}")
    
    # Update last sync time
    await set_last_sync_time("slack")
    
    result.finish()
    return result

