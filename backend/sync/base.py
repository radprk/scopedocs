"""
Shared utilities for daily sync operations.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.storage.postgres import get_integration_state, set_integration_state


def get_env_token(integration: str) -> Optional[str]:
    """Get access token from environment variable."""
    env_key = f"{integration.upper()}_ACCESS_TOKEN"
    return os.environ.get(env_key)


async def get_last_sync_time(source: str, default_days: int = 7) -> datetime:
    """Get the last sync timestamp for a source, or default to N days ago."""
    state = await get_integration_state(source, "last_sync_time")
    if state and state.get("state_value"):
        try:
            ts = state["state_value"]
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return ts
        except (ValueError, TypeError):
            pass
    return datetime.now(tz=timezone.utc) - timedelta(days=default_days)


async def set_last_sync_time(source: str, sync_time: Optional[datetime] = None) -> None:
    """Set the last sync timestamp for a source."""
    if sync_time is None:
        sync_time = datetime.now(tz=timezone.utc)
    await set_integration_state(source, "last_sync_time", sync_time.isoformat())


async def get_sync_cursor(source: str, cursor_key: str = "cursor") -> Optional[str]:
    """Get a pagination cursor for a source."""
    state = await get_integration_state(source, cursor_key)
    if state:
        return state.get("state_value")
    return None


async def set_sync_cursor(source: str, cursor: Optional[str], cursor_key: str = "cursor") -> None:
    """Set a pagination cursor for a source."""
    await set_integration_state(source, cursor_key, cursor)


class SyncResult:
    """Result of a sync operation."""
    
    def __init__(self, source: str):
        self.source = source
        self.items_synced = 0
        self.errors: list[str] = []
        self.started_at = datetime.now(tz=timezone.utc)
        self.finished_at: Optional[datetime] = None
    
    def add_error(self, error: str) -> None:
        self.errors.append(error)
    
    def finish(self) -> None:
        self.finished_at = datetime.now(tz=timezone.utc)
    
    @property
    def success(self) -> bool:
        return len(self.errors) == 0
    
    @property
    def duration_seconds(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
    
    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"[{self.source}] {status}: "
            f"{self.items_synced} items synced in {self.duration_seconds:.1f}s"
            + (f" ({len(self.errors)} errors)" if self.errors else "")
        )

