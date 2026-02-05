"""Search service for semantic search and RAG."""

import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import asyncpg

from .client import TogetherClient, get_client


@dataclass
class SearchResult:
    """A single search result."""
    id: str
    source_type: str  # 'code', 'doc', 'message'
    content: str
    file_path: Optional[str]
    repo_full_name: str
    start_line: Optional[int]
    end_line: Optional[int]
    score: float
    metadata: Dict[str, Any]


@dataclass
class SearchResponse:
    """Response from a search query."""
    results: List[SearchResult]
    query: str
    total_found: int


class SearchService:
    """Service for semantic search across code, docs, and messages."""

    def __init__(self, pool: asyncpg.Pool, client: Optional[TogetherClient] = None):
        self.pool = pool
        self.client = client or get_client()

    async def search_code(
        self,
        workspace_id: str,
        query: str,
        repo_full_name: Optional[str] = None,
        file_path_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        limit: int = 10,
    ) -> SearchResponse:
        """
        Search code chunks semantically.

        Args:
            workspace_id: Workspace UUID
            query: Search query
            repo_full_name: Optional filter by repo
            file_path_filter: Optional filter by file path prefix
            language_filter: Optional filter by language
            limit: Max results to return

        Returns:
            SearchResponse with matching code chunks
        """
        # Embed the query
        query_embedding = await self.client.embed_single(query)

        async with self.pool.acquire() as conn:
            # Build query with filters
            filters = ["workspace_id = $1"]
            params = [workspace_id]

            if repo_full_name:
                params.append(repo_full_name)
                filters.append(f"repo_full_name = ${len(params)}")

            if file_path_filter:
                params.append(f"{file_path_filter}%")
                filters.append(f"file_path LIKE ${len(params)}")

            if language_filter:
                params.append(language_filter)
                filters.append(f"language = ${len(params)}")

            params.append(json.dumps(query_embedding))
            params.append(limit)

            query_sql = f"""
                SELECT
                    id, repo_full_name, file_path, commit_sha,
                    chunk_index, start_line, end_line, language,
                    symbol_names, metadata,
                    1 - (embedding <=> ${len(params) - 1}::vector) as score
                FROM code_embeddings
                WHERE {' AND '.join(filters)}
                ORDER BY embedding <=> ${len(params) - 1}::vector
                LIMIT ${len(params)}
            """

            rows = await conn.fetch(query_sql, *params)

            results = []
            for row in rows:
                results.append(SearchResult(
                    id=str(row["id"]),
                    source_type="code",
                    content=f"File: {row['file_path']}, Lines {row['start_line']}-{row['end_line']}",
                    file_path=row["file_path"],
                    repo_full_name=row["repo_full_name"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    score=float(row["score"]),
                    metadata={
                        "language": row["language"],
                        "symbols": row["symbol_names"],
                        "commit_sha": row["commit_sha"],
                        "chunk_index": row["chunk_index"],
                    },
                ))

            return SearchResponse(
                results=results,
                query=query,
                total_found=len(results),
            )

    async def search_docs(
        self,
        workspace_id: str,
        query: str,
        repo_full_name: Optional[str] = None,
        doc_type: Optional[str] = None,
        include_stale: bool = False,
        limit: int = 10,
    ) -> SearchResponse:
        """
        Search generated documentation semantically.

        Args:
            workspace_id: Workspace UUID
            query: Search query
            repo_full_name: Optional filter by repo
            doc_type: Optional filter by doc type
            include_stale: Include stale docs
            limit: Max results

        Returns:
            SearchResponse with matching docs
        """
        query_embedding = await self.client.embed_single(query)

        async with self.pool.acquire() as conn:
            filters = ["workspace_id = $1", "embedding IS NOT NULL"]
            params = [workspace_id]

            if repo_full_name:
                params.append(repo_full_name)
                filters.append(f"repo_full_name = ${len(params)}")

            if doc_type:
                params.append(doc_type)
                filters.append(f"doc_type = ${len(params)}")

            if not include_stale:
                filters.append("is_stale = FALSE")

            params.append(json.dumps(query_embedding))
            params.append(limit)

            query_sql = f"""
                SELECT
                    id, repo_full_name, file_path, doc_type, title, content,
                    is_stale, version,
                    1 - (embedding <=> ${len(params) - 1}::vector) as score
                FROM generated_docs
                WHERE {' AND '.join(filters)}
                ORDER BY embedding <=> ${len(params) - 1}::vector
                LIMIT ${len(params)}
            """

            rows = await conn.fetch(query_sql, *params)

            results = []
            for row in rows:
                results.append(SearchResult(
                    id=str(row["id"]),
                    source_type="doc",
                    content=row["content"][:500],  # Truncate for response
                    file_path=row["file_path"],
                    repo_full_name=row["repo_full_name"],
                    start_line=None,
                    end_line=None,
                    score=float(row["score"]),
                    metadata={
                        "doc_type": row["doc_type"],
                        "title": row["title"],
                        "is_stale": row["is_stale"],
                        "version": row["version"],
                    },
                ))

            return SearchResponse(
                results=results,
                query=query,
                total_found=len(results),
            )

    async def search_messages(
        self,
        workspace_id: str,
        query: str,
        source: Optional[str] = None,
        limit: int = 10,
    ) -> SearchResponse:
        """
        Search Slack/Linear messages semantically.

        Args:
            workspace_id: Workspace UUID
            query: Search query
            source: Optional filter by 'slack' or 'linear'
            limit: Max results

        Returns:
            SearchResponse with matching messages
        """
        query_embedding = await self.client.embed_single(query)

        async with self.pool.acquire() as conn:
            filters = ["workspace_id = $1", "embedding IS NOT NULL"]
            params = [workspace_id]

            if source:
                params.append(source)
                filters.append(f"source = ${len(params)}")

            params.append(json.dumps(query_embedding))
            params.append(limit)

            query_sql = f"""
                SELECT
                    id, source, external_id, channel_or_project, summary,
                    message_type, linked_code_chunks, linked_prs, linked_issues,
                    1 - (embedding <=> ${len(params) - 1}::vector) as score
                FROM message_embeddings
                WHERE {' AND '.join(filters)}
                ORDER BY embedding <=> ${len(params) - 1}::vector
                LIMIT ${len(params)}
            """

            rows = await conn.fetch(query_sql, *params)

            results = []
            for row in rows:
                results.append(SearchResult(
                    id=str(row["id"]),
                    source_type="message",
                    content=row["summary"] or "",
                    file_path=None,
                    repo_full_name="",
                    start_line=None,
                    end_line=None,
                    score=float(row["score"]),
                    metadata={
                        "source": row["source"],
                        "external_id": row["external_id"],
                        "channel_or_project": row["channel_or_project"],
                        "message_type": row["message_type"],
                        "linked_code_chunks": row["linked_code_chunks"],
                        "linked_prs": row["linked_prs"],
                        "linked_issues": row["linked_issues"],
                    },
                ))

            return SearchResponse(
                results=results,
                query=query,
                total_found=len(results),
            )

    async def search_all(
        self,
        workspace_id: str,
        query: str,
        repo_full_name: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, SearchResponse]:
        """
        Search across all content types.

        Args:
            workspace_id: Workspace UUID
            query: Search query
            repo_full_name: Optional filter by repo
            limit: Max results per type

        Returns:
            Dict with 'code', 'docs', 'messages' SearchResponses
        """
        # Run searches in parallel
        import asyncio
        code_task = self.search_code(
            workspace_id, query, repo_full_name, limit=limit
        )
        docs_task = self.search_docs(
            workspace_id, query, repo_full_name, limit=limit
        )
        messages_task = self.search_messages(
            workspace_id, query, limit=limit
        )

        code_results, doc_results, message_results = await asyncio.gather(
            code_task, docs_task, messages_task
        )

        return {
            "code": code_results,
            "docs": doc_results,
            "messages": message_results,
        }

    async def answer_question(
        self,
        workspace_id: str,
        question: str,
        repo_full_name: Optional[str] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Answer a question using RAG (retrieve + generate).

        Args:
            workspace_id: Workspace UUID
            question: The user's question
            repo_full_name: Optional scope to a repo
            chat_history: Previous messages for context

        Returns:
            Dict with 'answer', 'sources', and 'search_results'
        """
        # Search for relevant context
        search_results = await self.search_all(
            workspace_id=workspace_id,
            query=question,
            repo_full_name=repo_full_name,
            limit=5,
        )

        # Combine results from all sources
        context = []

        # Add doc results first (most comprehensive)
        for result in search_results["docs"].results[:3]:
            context.append({
                "content": result.content,
                "source": f"{result.metadata['title']} ({result.file_path or 'overview'})",
                "type": "documentation",
            })

        # Add code results
        for result in search_results["code"].results[:3]:
            context.append({
                "content": f"Code from {result.file_path}, lines {result.start_line}-{result.end_line}",
                "source": result.file_path,
                "type": "code",
            })

        # Add message results
        for result in search_results["messages"].results[:2]:
            context.append({
                "content": result.content,
                "source": f"{result.metadata['source']}: {result.metadata['channel_or_project']}",
                "type": "message",
            })

        if not context:
            return {
                "answer": "I couldn't find relevant information to answer your question. Try rephrasing or asking about something else.",
                "sources": [],
                "search_results": search_results,
            }

        # Generate answer
        answer = await self.client.answer_question(
            question=question,
            context=context,
            chat_history=chat_history,
        )

        # Format sources
        sources = [
            {
                "source": c["source"],
                "type": c["type"],
            }
            for c in context
        ]

        return {
            "answer": answer,
            "sources": sources,
            "search_results": search_results,
        }

    async def save_chat_message(
        self,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict]] = None,
    ) -> str:
        """Save a chat message to history."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chat_messages (session_id, role, content, sources)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                session_id,
                role,
                content,
                json.dumps(sources or []),
            )
            return str(row["id"])

    async def create_chat_session(
        self,
        workspace_id: str,
        repo_full_name: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        """Create a new chat session."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chat_sessions (workspace_id, repo_full_name, title)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                workspace_id,
                repo_full_name,
                title or "New Chat",
            )
            return str(row["id"])

    async def get_chat_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get chat history for a session."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, role, content, sources, created_at
                FROM chat_messages
                WHERE session_id = $1
                ORDER BY created_at ASC
                LIMIT $2
                """,
                session_id,
                limit,
            )
            return [dict(row) for row in rows]
