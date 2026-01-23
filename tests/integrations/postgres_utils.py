import os
from typing import Dict

import psycopg2


def postgres_enabled() -> bool:
    return bool(os.getenv("POSTGRES_DSN"))


def fetch_table_counts() -> Dict[str, int]:
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        return {}
    counts: Dict[str, int] = {}
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cursor:
            for table in ["work_items", "pull_requests", "conversations", "relationships", "artifact_events"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
    return counts


def fetch_relationship_count() -> int:
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        return 0
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM relationships")
            return cursor.fetchone()[0]
