import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.extras import Json

POSTGRES_DSN = os.getenv("POSTGRES_DSN")


def postgres_enabled() -> bool:
    return bool(POSTGRES_DSN)


@contextmanager
def postgres_connection():
    if not POSTGRES_DSN:
        raise RuntimeError("POSTGRES_DSN is not set")
    conn = psycopg2.connect(POSTGRES_DSN)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_postgres_schema() -> None:
    if not POSTGRES_DSN:
        return
    with postgres_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS work_items (
                id UUID PRIMARY KEY,
                external_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pull_requests (
                id UUID PRIMARY KEY,
                external_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                repo TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                merged_at TIMESTAMPTZ NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY,
                external_id TEXT UNIQUE NOT NULL,
                channel TEXT NOT NULL,
                thread_ts TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relationships (
                id UUID PRIMARY KEY,
                source_id UUID NOT NULL,
                target_id UUID NOT NULL,
                relationship_type TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                UNIQUE (source_id, target_id, relationship_type),
                FOREIGN KEY (source_id) REFERENCES work_items(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES pull_requests(id) ON DELETE CASCADE
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS artifact_events (
                id UUID PRIMARY KEY,
                artifact_type TEXT NOT NULL,
                artifact_id UUID NOT NULL,
                source TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            );
            """
        )
        cursor.close()


def upsert_work_item(conn, work_item: Dict[str, Any]) -> str:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO work_items (id, external_id, title, status, created_at, updated_at)
        VALUES (%(id)s, %(external_id)s, %(title)s, %(status)s, %(created_at)s, %(updated_at)s)
        ON CONFLICT (external_id)
        DO UPDATE SET title = EXCLUDED.title, status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
        RETURNING id;
        """,
        work_item,
    )
    row = cursor.fetchone()
    cursor.close()
    return str(row[0])


def upsert_pull_request(conn, pull_request: Dict[str, Any]) -> str:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO pull_requests (id, external_id, title, status, repo, created_at, merged_at)
        VALUES (%(id)s, %(external_id)s, %(title)s, %(status)s, %(repo)s, %(created_at)s, %(merged_at)s)
        ON CONFLICT (external_id)
        DO UPDATE SET title = EXCLUDED.title, status = EXCLUDED.status, repo = EXCLUDED.repo, merged_at = EXCLUDED.merged_at
        RETURNING id;
        """,
        pull_request,
    )
    row = cursor.fetchone()
    cursor.close()
    return str(row[0])


def upsert_conversation(conn, conversation: Dict[str, Any]) -> str:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO conversations (id, external_id, channel, thread_ts, created_at)
        VALUES (%(id)s, %(external_id)s, %(channel)s, %(thread_ts)s, %(created_at)s)
        ON CONFLICT (external_id)
        DO UPDATE SET channel = EXCLUDED.channel, thread_ts = EXCLUDED.thread_ts
        RETURNING id;
        """,
        conversation,
    )
    row = cursor.fetchone()
    cursor.close()
    return str(row[0])


def insert_relationship(
    conn,
    relationship: Dict[str, Any],
) -> Optional[str]:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO relationships (id, source_id, target_id, relationship_type, created_at)
        VALUES (%(id)s, %(source_id)s, %(target_id)s, %(relationship_type)s, %(created_at)s)
        ON CONFLICT (source_id, target_id, relationship_type) DO NOTHING
        RETURNING id;
        """,
        relationship,
    )
    row = cursor.fetchone()
    cursor.close()
    return str(row[0]) if row else None


def insert_artifact_event(conn, artifact_event: Dict[str, Any]) -> None:
    cursor = conn.cursor()
    payload = artifact_event.copy()
    payload_json = Json(payload.pop("data"))
    cursor.execute(
        """
        INSERT INTO artifact_events (id, artifact_type, artifact_id, source, payload, created_at)
        VALUES (%(id)s, %(artifact_type)s, %(artifact_id)s, %(source)s, %(payload)s, %(created_at)s)
        ON CONFLICT (id) DO NOTHING;
        """,
        {
            "id": payload["id"],
            "artifact_type": payload["artifact_type"],
            "artifact_id": payload["artifact_id"],
            "source": payload["source"],
            "payload": payload_json,
            "created_at": payload["event_time"],
        },
    )
    cursor.close()
