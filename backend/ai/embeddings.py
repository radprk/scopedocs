"""Embedding service for code chunks and documents."""

import hashlib
import json
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import asyncpg

from .client import TogetherClient, get_client, EMBEDDING_DIMS


@dataclass
class CodeChunk:
    """A chunk of code to be embedded."""
    file_path: str
    content: str
    start_line: int
    end_line: int
    chunk_index: int
    language: str
    symbol_names: List[str] = None

    def content_hash(self) -> str:
        """Generate SHA256 hash of content for change detection."""
        return hashlib.sha256(self.content.encode()).hexdigest()


@dataclass
class EmbeddedChunk:
    """A code chunk with its embedding."""
    chunk: CodeChunk
    embedding: List[float]
    commit_sha: str


class EmbeddingService:
    """Service for generating and storing code embeddings."""

    def __init__(self, pool: asyncpg.Pool, client: Optional[TogetherClient] = None):
        self.pool = pool
        self.client = client or get_client()

    async def embed_code_chunks(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        chunks: List[CodeChunk],
        batch_size: int = 20,
    ) -> Dict[str, Any]:
        """
        Embed code chunks and store in database.

        Only embeds chunks that have changed (based on content hash).

        Args:
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            commit_sha: Git commit SHA
            chunks: List of code chunks
            batch_size: Chunks to embed in one API call

        Returns:
            Stats about the embedding operation
        """
        stats = {
            "total_chunks": len(chunks),
            "new_chunks": 0,
            "unchanged_chunks": 0,
            "errors": [],
        }

        # Check which chunks have changed
        chunks_to_embed = []
        for chunk in chunks:
            content_hash = chunk.content_hash()

            # Check if we already have this exact content
            existing = await self._get_existing_chunk(
                workspace_id, repo_full_name, chunk.file_path, chunk.chunk_index
            )

            if existing and existing["content_hash"] == content_hash:
                stats["unchanged_chunks"] += 1
                # Update commit SHA if needed
                if existing["commit_sha"] != commit_sha:
                    await self._update_commit_sha(existing["id"], commit_sha)
            else:
                chunk._content_hash = content_hash
                chunks_to_embed.append(chunk)

        if not chunks_to_embed:
            return stats

        # Embed in batches
        for i in range(0, len(chunks_to_embed), batch_size):
            batch = chunks_to_embed[i : i + batch_size]

            try:
                # Prepare text for embedding
                # Include file context for better semantic understanding
                texts = [
                    f"File: {c.file_path}\nLanguage: {c.language}\n\n{c.content}"
                    for c in batch
                ]

                # Get embeddings
                result = await self.client.embed(texts)

                # Store each chunk
                for chunk, embedding in zip(batch, result.embeddings):
                    await self._upsert_code_embedding(
                        workspace_id=workspace_id,
                        repo_full_name=repo_full_name,
                        commit_sha=commit_sha,
                        chunk=chunk,
                        embedding=embedding,
                    )
                    stats["new_chunks"] += 1

            except Exception as e:
                stats["errors"].append(f"Batch {i}: {str(e)}")

        return stats

    async def _get_existing_chunk(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
        chunk_index: int,
    ) -> Optional[Dict[str, Any]]:
        """Check if a chunk already exists."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, content_hash, commit_sha
                FROM code_embeddings
                WHERE workspace_id = $1
                  AND repo_full_name = $2
                  AND file_path = $3
                  AND chunk_index = $4
                """,
                workspace_id,
                repo_full_name,
                file_path,
                chunk_index,
            )
            return dict(row) if row else None

    async def _update_commit_sha(self, embedding_id: str, commit_sha: str):
        """Update the commit SHA for an existing embedding."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE code_embeddings
                SET commit_sha = $1, updated_at = NOW()
                WHERE id = $2
                """,
                commit_sha,
                embedding_id,
            )

    async def _upsert_code_embedding(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        chunk: CodeChunk,
        embedding: List[float],
    ):
        """Insert or update a code embedding."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO code_embeddings (
                    workspace_id, repo_full_name, file_path, commit_sha,
                    chunk_index, start_line, end_line, content_hash,
                    embedding, symbol_names, language, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (workspace_id, repo_full_name, file_path, chunk_index)
                DO UPDATE SET
                    commit_sha = EXCLUDED.commit_sha,
                    content_hash = EXCLUDED.content_hash,
                    embedding = EXCLUDED.embedding,
                    symbol_names = EXCLUDED.symbol_names,
                    language = EXCLUDED.language,
                    updated_at = NOW()
                """,
                workspace_id,
                repo_full_name,
                chunk.file_path,
                commit_sha,
                chunk.chunk_index,
                chunk.start_line,
                chunk.end_line,
                chunk._content_hash,
                json.dumps(embedding),  # pgvector accepts JSON array
                chunk.symbol_names or [],
                chunk.language,
                json.dumps({}),
            )

    async def delete_file_embeddings(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
    ):
        """Delete all embeddings for a file (when file is deleted)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM code_embeddings
                WHERE workspace_id = $1
                  AND repo_full_name = $2
                  AND file_path = $3
                """,
                workspace_id,
                repo_full_name,
                file_path,
            )

    async def embed_document(
        self,
        workspace_id: str,
        doc_id: str,
        content: str,
    ) -> List[float]:
        """
        Embed a generated document.

        Args:
            workspace_id: Workspace UUID
            doc_id: Document UUID
            content: Document content

        Returns:
            Embedding vector
        """
        embedding = await self.client.embed_single(content)

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generated_docs
                SET embedding = $1, updated_at = NOW()
                WHERE id = $2
                """,
                json.dumps(embedding),
                doc_id,
            )

        return embedding

    async def embed_message(
        self,
        workspace_id: str,
        source: str,
        external_id: str,
        content: str,
        channel_or_project: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> str:
        """
        Embed a Slack/Linear message.

        If summary is not provided, generates one using the LLM.

        Args:
            workspace_id: Workspace UUID
            source: 'slack' or 'linear'
            external_id: External message ID
            content: Message content (NOT stored, only used for embedding)
            channel_or_project: Channel or project name
            summary: Optional pre-generated summary

        Returns:
            Message embedding ID
        """
        # Generate summary if not provided
        if not summary:
            summary = await self.client.summarize_for_embedding(
                content, content_type="message"
            )

        # Embed the summary (not the full content for privacy)
        embedding = await self.client.embed_single(summary)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO message_embeddings (
                    workspace_id, source, external_id, channel_or_project,
                    summary, embedding
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (workspace_id, source, external_id)
                DO UPDATE SET
                    summary = EXCLUDED.summary,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
                RETURNING id
                """,
                workspace_id,
                source,
                external_id,
                channel_or_project,
                summary,
                json.dumps(embedding),
            )
            return str(row["id"])

    async def get_embedding_stats(
        self,
        workspace_id: str,
        repo_full_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get statistics about embeddings for a workspace."""
        async with self.pool.acquire() as conn:
            if repo_full_name:
                code_stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_chunks,
                        COUNT(DISTINCT file_path) as total_files,
                        MAX(updated_at) as last_updated
                    FROM code_embeddings
                    WHERE workspace_id = $1 AND repo_full_name = $2
                    """,
                    workspace_id,
                    repo_full_name,
                )
            else:
                code_stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_chunks,
                        COUNT(DISTINCT file_path) as total_files,
                        COUNT(DISTINCT repo_full_name) as total_repos,
                        MAX(updated_at) as last_updated
                    FROM code_embeddings
                    WHERE workspace_id = $1
                    """,
                    workspace_id,
                )

            doc_stats = await conn.fetchrow(
                """
                SELECT COUNT(*) as total_docs
                FROM generated_docs
                WHERE workspace_id = $1
                """,
                workspace_id,
            )

            message_stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_messages,
                    COUNT(*) FILTER (WHERE source = 'slack') as slack_messages,
                    COUNT(*) FILTER (WHERE source = 'linear') as linear_messages
                FROM message_embeddings
                WHERE workspace_id = $1
                """,
                workspace_id,
            )

            return {
                "code": dict(code_stats) if code_stats else {},
                "docs": dict(doc_stats) if doc_stats else {},
                "messages": dict(message_stats) if message_stats else {},
            }
