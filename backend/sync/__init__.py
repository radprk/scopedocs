"""
Sync module for pulling data from GitHub into the database.
Slack and Linear sync will be added in phase 2.
"""

from backend.sync.sync_github import sync_github

__all__ = ["sync_github"]

