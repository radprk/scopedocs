"""Initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Core tables
    op.execute("""
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
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS ingestion_jobs;
        DROP TABLE IF EXISTS integration_tokens;
        DROP TABLE IF EXISTS external_id_mappings;
        DROP TABLE IF EXISTS integration_state;
        DROP TABLE IF EXISTS drift_alerts;
        DROP TABLE IF EXISTS embeddings;
        DROP TABLE IF EXISTS artifact_events;
        DROP TABLE IF EXISTS relationships;
        DROP TABLE IF EXISTS people;
        DROP TABLE IF EXISTS components;
        DROP TABLE IF EXISTS scopedocs;
        DROP TABLE IF EXISTS conversations;
        DROP TABLE IF EXISTS pull_requests;
        DROP TABLE IF EXISTS work_items;
    """)
