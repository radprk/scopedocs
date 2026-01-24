"""
Database module - PostgreSQL (Supabase) implementation
Replaces MongoDB with PostgreSQL for all database operations
"""
import os
import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

from backend.storage.postgres import (
    get_pool,
    close_pool,
    init_pg,
    upsert_work_item,
    upsert_pull_request,
    upsert_conversation,
    upsert_scopedoc,
    upsert_component,
    upsert_person,
    upsert_relationship,
    upsert_artifact_event,
    upsert_embedding,
    upsert_drift_alert,
    upsert_external_id_mapping,
    upsert_integration_token,
    upsert_ingestion_job,
    get_external_id_mapping,
    get_integration_token as pg_get_integration_token,
    get_ingestion_job,
    update_ingestion_job,
    find_latest_ingestion_checkpoint,
    get_integration_state,
    set_integration_state,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Collection names (for compatibility with existing code)
COLLECTIONS = {
    'artifact_events': 'artifact_events',
    'work_items': 'work_items',
    'pull_requests': 'pull_requests',
    'conversations': 'conversations',
    'scopedocs': 'scopedocs',
    'components': 'components',
    'people': 'people',
    'relationships': 'relationships',
    'embeddings': 'embeddings',
    'drift_alerts': 'drift_alerts',
    'integration_tokens': 'integration_tokens',
    'external_id_mappings': 'external_id_mappings',
    'ingestion_jobs': 'ingestion_jobs',
}

# Table name mapping
TABLE_NAMES = COLLECTIONS


class PostgresDB:
    """PostgreSQL database wrapper that provides MongoDB-like interface"""

    def __init__(self):
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            self._pool = await get_pool()
        return self._pool

    def __getitem__(self, collection: str) -> 'PostgresCollection':
        """Allow db['collection_name'] syntax like MongoDB"""
        return PostgresCollection(collection, self)


class PostgresCollection:
    """Wrapper for a PostgreSQL table that mimics MongoDB collection interface"""

    def __init__(self, table_name: str, db: PostgresDB):
        self.table_name = table_name
        self.db = db

    async def _get_pool(self):
        return await self.db._get_pool()

    def _serialize_value(self, value: Any) -> Any:
        """Serialize Python objects to JSON-compatible values"""
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, 'value'):  # Enum
            return value.value
        return value

    def _deserialize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert database row to dict, extracting data from JSONB if present"""
        if row is None:
            return None
        result = dict(row)
        # If there's a 'data' column with JSONB, expand it
        if 'data' in result and isinstance(result['data'], dict):
            data = result.pop('data')
            result.update(data)
        return result

    async def find_one(self, query: Dict[str, Any], projection: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Find a single document matching the query"""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Build WHERE clause
            conditions = []
            values = []
            idx = 1

            for key, value in query.items():
                if isinstance(value, dict):
                    # Handle MongoDB-style operators
                    for op, op_value in value.items():
                        if op == '$in':
                            placeholders = ', '.join([f'${idx + i}' for i in range(len(op_value))])
                            # Check if it's a JSONB field or regular column
                            if self._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' IN ({placeholders})")
                            else:
                                conditions.append(f"{key} IN ({placeholders})")
                            values.extend([self._serialize_value(v) for v in op_value])
                            idx += len(op_value)
                        elif op == '$gte':
                            if self._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' >= ${idx}")
                            else:
                                conditions.append(f"{key} >= ${idx}")
                            values.append(self._serialize_value(op_value))
                            idx += 1
                        elif op == '$ne':
                            if self._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' != ${idx}")
                            else:
                                conditions.append(f"{key} != ${idx}")
                            values.append(self._serialize_value(op_value))
                            idx += 1
                        elif op == '$regex':
                            if self._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' ~ ${idx}")
                            else:
                                conditions.append(f"{key} ~ ${idx}")
                            values.append(op_value)
                            idx += 1
                else:
                    # Simple equality
                    serialized = self._serialize_value(value)
                    if self._is_jsonb_field(key):
                        conditions.append(f"data->>'{key}' = ${idx}")
                    else:
                        conditions.append(f"{key} = ${idx}")
                    values.append(serialized)
                    idx += 1

            where_clause = ' AND '.join(conditions) if conditions else '1=1'
            query_sql = f"SELECT * FROM {self.table_name} WHERE {where_clause} LIMIT 1"

            row = await conn.fetchrow(query_sql, *values)
            return self._deserialize_row(row)

    def _is_jsonb_field(self, key: str) -> bool:
        """Check if a field should be queried from JSONB data column"""
        # These are the indexed columns that exist directly on tables
        direct_columns = {
            'work_items': ['id', 'external_id', 'project_id', 'updated_at'],
            'pull_requests': ['id', 'external_id', 'repo', 'updated_at'],
            'conversations': ['id', 'external_id', 'channel', 'updated_at'],
            'scopedocs': ['id', 'project_id', 'updated_at'],
            'components': ['id', 'name', 'updated_at'],
            'people': ['id', 'external_id', 'updated_at'],
            'relationships': ['id', 'updated_at'],
            'artifact_events': ['id', 'artifact_id', 'artifact_type', 'updated_at'],
            'embeddings': ['id', 'artifact_id', 'artifact_type', 'updated_at'],
            'drift_alerts': ['id', 'doc_id', 'updated_at'],
            'external_id_mappings': ['id', 'integration', 'external_id', 'internal_id', 'artifact_type', 'created_at'],
            'integration_tokens': ['id', 'integration', 'workspace_id', 'updated_at'],
            'ingestion_jobs': ['id', 'job_key', 'job_type', 'updated_at'],
            'integration_state': ['source', 'state_key', 'state_value', 'updated_at'],
        }
        table_columns = direct_columns.get(self.table_name, ['id'])
        return key not in table_columns

    async def find(self, query: Dict[str, Any] = None, projection: Dict[str, Any] = None) -> 'PostgresCursor':
        """Find documents matching the query, returns a cursor-like object"""
        return PostgresCursor(self, query or {}, projection)

    async def insert_one(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a single document"""
        await self._upsert(document)
        return {'inserted_id': document.get('id')}

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False) -> Dict[str, Any]:
        """Update a single document"""
        pool = await self._get_pool()

        # Handle $set operator
        if '$set' in update:
            update_data = update['$set']
        elif '$setOnInsert' in update and '$set' in update:
            # For upsert operations
            update_data = {**update.get('$setOnInsert', {}), **update.get('$set', {})}
        else:
            update_data = update

        # Handle $inc operator
        if '$inc' in update:
            # Need to fetch current values first
            existing = await self.find_one(query)
            if existing:
                for key, increment in update['$inc'].items():
                    current = existing.get(key, 0)
                    update_data[key] = current + increment

        if upsert:
            # Try to find existing document
            existing = await self.find_one(query)
            if existing:
                # Merge with existing data
                merged = {**existing, **update_data}
                await self._upsert(merged)
            else:
                # Insert new document with query fields + update data
                new_doc = {**query, **update_data}
                if '$setOnInsert' in update:
                    new_doc.update(update['$setOnInsert'])
                await self._upsert(new_doc)
        else:
            # Just update
            existing = await self.find_one(query)
            if existing:
                merged = {**existing, **update_data}
                await self._upsert(merged)

        return {'modified_count': 1}

    async def _upsert(self, document: Dict[str, Any]) -> None:
        """Upsert a document using the appropriate function"""
        # Serialize datetime and enum values
        serialized = {}
        for key, value in document.items():
            serialized[key] = self._serialize_value(value)

        # Use the appropriate upsert function
        upsert_functions = {
            'work_items': upsert_work_item,
            'pull_requests': upsert_pull_request,
            'conversations': upsert_conversation,
            'scopedocs': upsert_scopedoc,
            'components': upsert_component,
            'people': upsert_person,
            'relationships': upsert_relationship,
            'artifact_events': upsert_artifact_event,
            'embeddings': upsert_embedding,
            'drift_alerts': upsert_drift_alert,
            'external_id_mappings': upsert_external_id_mapping,
            'integration_tokens': upsert_integration_token,
            'ingestion_jobs': upsert_ingestion_job,
        }

        upsert_func = upsert_functions.get(self.table_name)
        if upsert_func:
            await upsert_func(serialized)
        else:
            raise ValueError(f"No upsert function for table: {self.table_name}")

    async def delete_many(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """Delete documents matching the query"""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if not query:
                # Delete all
                result = await conn.execute(f"DELETE FROM {self.table_name}")
            else:
                # Build WHERE clause
                conditions = []
                values = []
                idx = 1

                for key, value in query.items():
                    serialized = self._serialize_value(value)
                    if self._is_jsonb_field(key):
                        conditions.append(f"data->>'{key}' = ${idx}")
                    else:
                        conditions.append(f"{key} = ${idx}")
                    values.append(serialized)
                    idx += 1

                where_clause = ' AND '.join(conditions)
                result = await conn.execute(f"DELETE FROM {self.table_name} WHERE {where_clause}", *values)

            # Parse deleted count from result string
            deleted_count = int(result.split()[-1]) if result else 0
            return {'deleted_count': deleted_count}

    async def count_documents(self, query: Dict[str, Any] = None) -> int:
        """Count documents matching the query"""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if not query:
                row = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {self.table_name}")
            else:
                # Build WHERE clause
                conditions = []
                values = []
                idx = 1

                for key, value in query.items():
                    serialized = self._serialize_value(value)
                    if self._is_jsonb_field(key):
                        conditions.append(f"data->>'{key}' = ${idx}")
                    else:
                        conditions.append(f"{key} = ${idx}")
                    values.append(serialized)
                    idx += 1

                where_clause = ' AND '.join(conditions)
                row = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {self.table_name} WHERE {where_clause}", *values)

            return row['count'] if row else 0


class PostgresCursor:
    """Cursor-like object for iterating over query results"""

    def __init__(self, collection: PostgresCollection, query: Dict[str, Any], projection: Dict[str, Any] = None):
        self.collection = collection
        self.query = query
        self.projection = projection
        self._sort = None
        self._limit = None

    def sort(self, key_or_list, direction=None):
        """Set sort order"""
        if isinstance(key_or_list, list):
            self._sort = key_or_list
        else:
            self._sort = [(key_or_list, direction or 1)]
        return self

    async def to_list(self, length: int = None) -> List[Dict[str, Any]]:
        """Execute query and return results as list"""
        pool = await self.collection._get_pool()
        async with pool.acquire() as conn:
            # Build WHERE clause
            conditions = []
            values = []
            idx = 1

            for key, value in self.query.items():
                if isinstance(value, dict):
                    # Handle MongoDB-style operators
                    for op, op_value in value.items():
                        if op == '$in':
                            placeholders = ', '.join([f'${idx + i}' for i in range(len(op_value))])
                            if self.collection._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' IN ({placeholders})")
                            else:
                                conditions.append(f"{key} IN ({placeholders})")
                            values.extend([self.collection._serialize_value(v) for v in op_value])
                            idx += len(op_value)
                        elif op == '$gte':
                            if self.collection._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' >= ${idx}")
                            else:
                                conditions.append(f"{key} >= ${idx}")
                            values.append(self.collection._serialize_value(op_value))
                            idx += 1
                        elif op == '$ne':
                            if self.collection._is_jsonb_field(key):
                                conditions.append(f"data->>'{key}' IS NOT NULL")
                            else:
                                conditions.append(f"{key} IS NOT NULL")
                else:
                    serialized = self.collection._serialize_value(value)
                    if self.collection._is_jsonb_field(key):
                        conditions.append(f"data->>'{key}' = ${idx}")
                    else:
                        conditions.append(f"{key} = ${idx}")
                    values.append(serialized)
                    idx += 1

            where_clause = ' AND '.join(conditions) if conditions else '1=1'

            # Build ORDER BY clause
            order_clause = ''
            if self._sort:
                order_parts = []
                for sort_key, sort_dir in self._sort:
                    direction = 'DESC' if sort_dir == -1 else 'ASC'
                    if self.collection._is_jsonb_field(sort_key):
                        order_parts.append(f"data->>'{sort_key}' {direction}")
                    else:
                        order_parts.append(f"{sort_key} {direction}")
                order_clause = ' ORDER BY ' + ', '.join(order_parts)

            # Build LIMIT clause
            limit_clause = ''
            if length or self._limit:
                limit_clause = f' LIMIT {length or self._limit}'

            query_sql = f"SELECT * FROM {self.collection.table_name} WHERE {where_clause}{order_clause}{limit_clause}"

            rows = await conn.fetch(query_sql, *values)
            return [self.collection._deserialize_row(dict(row)) for row in rows]


# Global database instance
db = PostgresDB()


async def init_db():
    """Initialize database with tables and indexes"""
    await init_pg()


async def close_db():
    """Close database connection"""
    await close_pool()
