import json
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
            CREATE TABLE IF NOT EXISTS external_id_mappings (
                id text PRIMARY KEY,
                integration text NOT NULL,
                external_id text NOT NULL,
                internal_id text NOT NULL,
                artifact_type text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT NOW(),
                UNIQUE (integration, external_id, artifact_type)
            );
            CREATE TABLE IF NOT EXISTS integration_tokens (
                id text PRIMARY KEY,
                integration text NOT NULL,
                workspace_id text NOT NULL,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW(),
                UNIQUE (integration, workspace_id)
            );
            CREATE TABLE IF NOT EXISTS ingestion_jobs (
                id text PRIMARY KEY,
                job_key text UNIQUE NOT NULL,
                job_type text NOT NULL,
                data jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                github_org_id TEXT,
                slack_team_id TEXT,
                linear_org_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            
            -- Code indexing tables
            CREATE TABLE IF NOT EXISTS file_path_lookup (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                repo_id UUID NOT NULL,
                file_path_hash TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_content_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (repo_id, file_path_hash)
            );
            
            CREATE TABLE IF NOT EXISTS code_chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                repo_id UUID NOT NULL,
                file_path_hash TEXT NOT NULL,
                chunk_hash TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (repo_id, file_path_hash, chunk_index)
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


async def upsert_work_item(payload: Any, workspace_id: str = None) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    if workspace_id:
        data["workspace_id"] = workspace_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO work_items (id, external_id, project_id, data, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5)
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
            json.dumps(data),
            datetime.utcnow(),
        )


async def upsert_pull_request(payload: Any, workspace_id: str = None) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    if workspace_id:
        data["workspace_id"] = workspace_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pull_requests (id, external_id, repo, data, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5)
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
            json.dumps(data),
            datetime.utcnow(),
        )


async def upsert_conversation(payload: Any, workspace_id: str = None) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    external_id = data.get("external_id")
    if workspace_id:
        data["workspace_id"] = workspace_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations (id, external_id, channel, data, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5)
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
            json.dumps(data),
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


async def upsert_external_id_mapping(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO external_id_mappings (id, integration, external_id, internal_id, artifact_type, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (integration, external_id, artifact_type)
            DO UPDATE SET
                internal_id = EXCLUDED.internal_id
            """,
            item_id,
            data.get("integration"),
            data.get("external_id"),
            data.get("internal_id"),
            data.get("artifact_type"),
            data.get("created_at", datetime.utcnow()),
        )


async def get_external_id_mapping(integration: str, external_id: str, artifact_type: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, integration, external_id, internal_id, artifact_type, created_at
            FROM external_id_mappings
            WHERE integration = $1 AND external_id = $2 AND artifact_type = $3
            """,
            integration,
            external_id,
            artifact_type,
        )
        if not row:
            return None
        return dict(row)


async def upsert_integration_token(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO integration_tokens (id, integration, workspace_id, data, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            ON CONFLICT (integration, workspace_id)
            DO UPDATE SET
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            data.get("integration"),
            data.get("workspace_id"),
            json.dumps(data),  # Convert dict to JSON string for JSONB column
            datetime.utcnow(),
        )


async def get_integration_token(integration: str, workspace_id: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data FROM integration_tokens
            WHERE integration = $1 AND workspace_id = $2
            """,
            integration,
            workspace_id,
        )
        if not row:
            return None
        data = row["data"]
        # Handle both JSON string and dict
        if isinstance(data, str):
            import json
            data = json.loads(data)
        return data


async def upsert_ingestion_job(payload: Any) -> None:
    data = _normalize_payload(payload)
    item_id = _ensure_id(data)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ingestion_jobs (id, job_key, job_type, data, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (job_key)
            DO UPDATE SET
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            item_id,
            data.get("job_key"),
            data.get("job_type"),
            data,
            datetime.utcnow(),
        )


async def get_ingestion_job(job_key: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data FROM ingestion_jobs WHERE job_key = $1
            """,
            job_key,
        )
        if not row:
            return None
        return row["data"]


async def update_ingestion_job(job_key: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data FROM ingestion_jobs WHERE job_key = $1
            """,
            job_key,
        )
        if not row:
            return None
        current_data = row["data"]
        current_data.update(updates)
        current_data["updated_at"] = datetime.utcnow().isoformat()
        await conn.execute(
            """
            UPDATE ingestion_jobs SET data = $1, updated_at = $2 WHERE job_key = $3
            """,
            current_data,
            datetime.utcnow(),
            job_key,
        )
        return current_data


async def find_latest_ingestion_checkpoint(job_type: str, source: str, project_id: Optional[str] = None) -> Optional[datetime]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if project_id:
            row = await conn.fetchrow(
                """
                SELECT data->>'checkpoint' as checkpoint
                FROM ingestion_jobs
                WHERE job_type = $1
                  AND data->>'payload'->>'source' = $2
                  AND data->>'payload'->>'project_id' = $3
                  AND data->>'checkpoint' IS NOT NULL
                ORDER BY data->>'checkpoint' DESC
                LIMIT 1
                """,
                job_type,
                source,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT data->>'checkpoint' as checkpoint
                FROM ingestion_jobs
                WHERE job_type = $1
                  AND data->'payload'->>'source' = $2
                  AND data->>'checkpoint' IS NOT NULL
                ORDER BY data->>'checkpoint' DESC
                LIMIT 1
                """,
                job_type,
                source,
            )
        if not row or not row["checkpoint"]:
            return None
        try:
            return datetime.fromisoformat(row["checkpoint"].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None


# =============================================================================
# Workspace functions
# =============================================================================

async def list_workspaces() -> list:
    """List all workspaces."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, slug, github_org_id, slack_team_id, linear_org_id, created_at
            FROM workspaces
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in rows]


async def get_workspace(workspace_id: str) -> Optional[dict]:
    """Get a workspace by ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, slug, github_org_id, slack_team_id, linear_org_id, created_at
            FROM workspaces
            WHERE id = $1::uuid
            """,
            workspace_id,
        )
        return dict(row) if row else None


async def create_workspace(name: str, slug: str) -> dict:
    """Create a new workspace."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO workspaces (name, slug)
            VALUES ($1, $2)
            RETURNING id, name, slug, github_org_id, slack_team_id, linear_org_id, created_at
            """,
            name,
            slug,
        )
        return dict(row)
