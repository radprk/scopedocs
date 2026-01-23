import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import asyncpg

_POOL: Optional[asyncpg.Pool] = None


def _get_dsn() -> str:
    dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN or DATABASE_URL environment variable is required")
    return dsn


async def get_pool() -> asyncpg.Pool:
    global _POOL
    if _POOL is None:
        _POOL = await asyncpg.create_pool(dsn=_get_dsn())
    return _POOL


async def close_pool() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def init_pg() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_items (
                id text PRIMARY KEY,
                external_id text UNIQUE NOT NULL,
                project_id text,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS pull_requests (
                id text PRIMARY KEY,
                external_id text UNIQUE NOT NULL,
                repo text,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id text PRIMARY KEY,
                external_id text UNIQUE NOT NULL,
                channel text,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS scopedocs (
                id text PRIMARY KEY,
                project_id text UNIQUE,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS components (
                id text PRIMARY KEY,
                name text UNIQUE,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS people (
                id text PRIMARY KEY,
                external_id text UNIQUE,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS relationships (
                id text PRIMARY KEY,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS artifact_events (
                id text PRIMARY KEY,
                artifact_id text,
                artifact_type text,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS embeddings (
                id text PRIMARY KEY,
                artifact_id text,
                artifact_type text,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS drift_alerts (
                id text PRIMARY KEY,
                doc_id text,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS integration_state (
                source text NOT NULL,
                state_key text NOT NULL,
                state_value jsonb,
                updated_at timestamptz NOT NULL DEFAULT NOW(),
                PRIMARY KEY (source, state_key)
            );
            """
        )


async def get_integration_state(source: str, state_key: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT state_value, updated_at
            FROM integration_state
            WHERE source = $1 AND state_key = $2
            """,
            source,
            state_key,
        )
        if not row:
            return None
        return {
            "state_value": row["state_value"],
            "updated_at": row["updated_at"],
        }


async def set_integration_state(source: str, state_key: str, state_value: Any) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO integration_state (source, state_key, state_value, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (source, state_key)
            DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = EXCLUDED.updated_at
            """,
            source,
            state_key,
            state_value,
            datetime.utcnow(),
        )


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    return dict(payload)


def _ensure_id(data: Dict[str, Any]) -> str:
    item_id = data.get("id")
    if not item_id:
        item_id = str(uuid.uuid4())
        data["id"] = item_id
    return item_id


async def upsert_work_item(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO work_items (id, external_id, project_id, data, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (external_id)
            DO UPDATE SET
                id = EXCLUDED.id,
                project_id = EXCLUDED.project_id,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            external_id,
            data.get("project_id"),
            data,
            datetime.utcnow(),
        )


async def upsert_pull_request(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pull_requests (id, external_id, repo, data, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (external_id)
            DO UPDATE SET
                id = EXCLUDED.id,
                repo = EXCLUDED.repo,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            external_id,
            data.get("repo"),
            data,
            datetime.utcnow(),
        )


async def upsert_conversation(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations (id, external_id, channel, data, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (external_id)
            DO UPDATE SET
                id = EXCLUDED.id,
                channel = EXCLUDED.channel,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            external_id,
            data.get("channel"),
            data,
            datetime.utcnow(),
        )


async def upsert_scopedoc(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    project_id = data.get("project_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO scopedocs (id, project_id, data, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (project_id)
            DO UPDATE SET
                id = EXCLUDED.id,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            project_id,
            data,
            datetime.utcnow(),
        )


async def upsert_component(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    name = data.get("name")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO components (id, name, data, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (name)
            DO UPDATE SET
                id = EXCLUDED.id,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            name,
            data,
            datetime.utcnow(),
        )


async def upsert_person(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO people (id, external_id, data, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (external_id)
            DO UPDATE SET
                id = EXCLUDED.id,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            external_id,
            data,
            datetime.utcnow(),
        )


async def upsert_relationship(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO relationships (id, data, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (id)
            DO UPDATE SET
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            data,
            datetime.utcnow(),
        )


async def upsert_artifact_event(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO artifact_events (id, artifact_id, artifact_type, data, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id)
            DO UPDATE SET
                artifact_id = EXCLUDED.artifact_id,
                artifact_type = EXCLUDED.artifact_type,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            data.get("artifact_id"),
            data.get("artifact_type"),
            data,
            datetime.utcnow(),
        )


async def upsert_embedding(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO embeddings (id, artifact_id, artifact_type, data, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id)
            DO UPDATE SET
                artifact_id = EXCLUDED.artifact_id,
                artifact_type = EXCLUDED.artifact_type,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            data.get("artifact_id"),
            data.get("artifact_type"),
            data,
            datetime.utcnow(),
        )


async def upsert_drift_alert(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO drift_alerts (id, doc_id, data, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id)
            DO UPDATE SET
                doc_id = EXCLUDED.doc_id,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            data.get("doc_id"),
            data,
            datetime.utcnow(),
        )
