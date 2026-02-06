"""
RAG Search Layer for ScopeDocs.

This module provides vector similarity search over code embeddings
to retrieve relevant context for LLM generation.

Flow:
1. User asks a question about the codebase
2. Question is embedded using Together.ai
3. Vector search finds similar code chunks
4. Code is fetched from GitHub (on-demand)
5. Context is assembled and sent to LLM
6. LLM generates answer with code references
"""

import json
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
import asyncpg

from .client import TogetherClient, get_client, EMBEDDING_DIMS


@dataclass
class SearchResult:
    """A single search result with code context."""
    file_path: str
    repo_full_name: str
    start_line: int
    end_line: int
    chunk_index: int
    similarity: float
    language: Optional[str] = None
    symbol_names: List[str] = field(default_factory=list)
    # Fetched on demand:
    code_content: Optional[str] = None

    def to_context(self) -> Dict[str, str]:
        """Convert to context format for LLM."""
        return {
            "source": f"{self.file_path}:{self.start_line}-{self.end_line}",
            "content": self.code_content or f"[Code from {self.file_path}]",
        }


@dataclass
class RAGContext:
    """
    Complete context for RAG generation.

    This is what gets sent to the LLM.
    """
    query: str
    query_embedding: List[float]
    results: List[SearchResult]
    total_tokens_estimate: int = 0

    def format_for_llm(self) -> str:
        """Format context as a string for LLM prompt."""
        parts = []
        for i, result in enumerate(self.results):
            ref = f"[{i+1}]"
            parts.append(f"### {ref} {result.file_path}:{result.start_line}-{result.end_line}")
            if result.code_content:
                lang = result.language or "python"
                parts.append(f"```{lang}\n{result.code_content}\n```")
            parts.append("")
        return "\n".join(parts)

    def get_references(self) -> Dict[str, Dict[str, Any]]:
        """Get reference mappings for the UI."""
        refs = {}
        for i, result in enumerate(self.results):
            refs[f"[{i+1}]"] = {
                "file_path": result.file_path,
                "repo_full_name": result.repo_full_name,
                "start_line": result.start_line,
                "end_line": result.end_line,
            }
        return refs


class RAGSearchService:
    """
    Service for RAG-based code search.

    Input: User question (string)
    Output: Relevant code chunks with context

    What happens:
    1. Embed the question
    2. Search code_embeddings table using pgvector
    3. Return top-k similar chunks
    4. (Optional) Fetch actual code from GitHub
    """

    def __init__(self, pool: asyncpg.Pool, client: Optional[TogetherClient] = None):
        self.pool = pool
        self.client = client or get_client()

    async def search(
        self,
        query: str,
        workspace_id: str,
        repo_full_name: Optional[str] = None,
        top_k: int = 10,
        similarity_threshold: float = 0.3,
    ) -> RAGContext:
        """
        Search for relevant code chunks.

        Args:
            query: The search query or question
            workspace_id: Workspace UUID
            repo_full_name: Optional filter to specific repo
            top_k: Number of results to return
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            RAGContext with search results

        Debug: Check these to verify search is working:
            - query_embedding length should be 1024
            - results should have similarity > threshold
            - Check code_embeddings table has data
        """
        print(f"[RAG] Searching for: {query[:50]}...")

        # Step 1: Embed the query
        query_embedding = await self.client.embed_single(query)
        print(f"[RAG] Query embedded, dim={len(query_embedding)}")

        # Step 2: Vector search
        results = await self._vector_search(
            workspace_id=workspace_id,
            query_embedding=query_embedding,
            repo_full_name=repo_full_name,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        print(f"[RAG] Found {len(results)} results")

        return RAGContext(
            query=query,
            query_embedding=query_embedding,
            results=results,
            total_tokens_estimate=sum(
                (r.end_line - r.start_line) * 20  # ~20 tokens per line estimate
                for r in results
            ),
        )

    async def _vector_search(
        self,
        workspace_id: str,
        query_embedding: List[float],
        repo_full_name: Optional[str],
        top_k: int,
        similarity_threshold: float,
    ) -> List[SearchResult]:
        """
        Perform vector similarity search using pgvector.

        SQL uses cosine distance: 1 - (embedding <=> query) = similarity
        """
        async with self.pool.acquire() as conn:
            # Build query based on filters
            if repo_full_name:
                query = """
                    SELECT
                        file_path,
                        repo_full_name,
                        start_line,
                        end_line,
                        chunk_index,
                        language,
                        symbol_names,
                        1 - (embedding <=> $1::vector) as similarity
                    FROM code_embeddings
                    WHERE workspace_id = $2
                      AND repo_full_name = $3
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT $4
                """
                rows = await conn.fetch(
                    query,
                    json.dumps(query_embedding),
                    workspace_id,
                    repo_full_name,
                    top_k,
                )
            else:
                query = """
                    SELECT
                        file_path,
                        repo_full_name,
                        start_line,
                        end_line,
                        chunk_index,
                        language,
                        symbol_names,
                        1 - (embedding <=> $1::vector) as similarity
                    FROM code_embeddings
                    WHERE workspace_id = $2
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT $3
                """
                rows = await conn.fetch(
                    query,
                    json.dumps(query_embedding),
                    workspace_id,
                    top_k,
                )

        results = []
        for row in rows:
            similarity = float(row["similarity"])
            if similarity >= similarity_threshold:
                results.append(SearchResult(
                    file_path=row["file_path"],
                    repo_full_name=row["repo_full_name"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    chunk_index=row["chunk_index"],
                    similarity=similarity,
                    language=row["language"],
                    symbol_names=row["symbol_names"] or [],
                ))

        return results

    async def search_with_code(
        self,
        query: str,
        workspace_id: str,
        github_token: str,
        repo_full_name: Optional[str] = None,
        top_k: int = 5,
    ) -> RAGContext:
        """
        Search and fetch actual code content from GitHub.

        This is the full RAG flow:
        1. Search for relevant chunks
        2. Fetch code from GitHub using pointers
        3. Return complete context ready for LLM
        """
        import httpx

        # Step 1: Search
        context = await self.search(
            query=query,
            workspace_id=workspace_id,
            repo_full_name=repo_full_name,
            top_k=top_k,
        )

        # Step 2: Fetch code for each result
        async with httpx.AsyncClient() as http:
            for result in context.results:
                try:
                    code = await self._fetch_code_from_github(
                        http=http,
                        token=github_token,
                        repo_full_name=result.repo_full_name,
                        file_path=result.file_path,
                        start_line=result.start_line,
                        end_line=result.end_line,
                    )
                    result.code_content = code
                    print(f"[RAG] Fetched {result.file_path}:{result.start_line}-{result.end_line}")
                except Exception as e:
                    print(f"[RAG] Failed to fetch {result.file_path}: {e}")
                    result.code_content = f"# Failed to fetch: {e}"

        return context

    async def _fetch_code_from_github(
        self,
        http,
        token: str,
        repo_full_name: str,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        """
        Fetch specific lines from a file in GitHub.

        Uses GitHub's raw content API.
        """
        url = f"https://raw.githubusercontent.com/{repo_full_name}/main/{file_path}"
        response = await http.get(
            url,
            headers={"Authorization": f"token {token}"},
        )
        response.raise_for_status()

        lines = response.text.split("\n")
        # Lines are 1-indexed in our storage
        selected = lines[start_line - 1 : end_line]
        return "\n".join(selected)


async def ask_codebase(
    pool: asyncpg.Pool,
    question: str,
    workspace_id: str,
    github_token: str,
    repo_full_name: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    High-level function: Ask a question about the codebase.

    Returns:
        Tuple of (answer, references)

    Example:
        answer, refs = await ask_codebase(
            pool=pool,
            question="How does authentication work?",
            workspace_id="...",
            github_token="ghp_...",
        )
        print(answer)
        # refs = {"[1]": {"file_path": "auth.py", "start_line": 10, ...}}
    """
    client = get_client()
    search_service = RAGSearchService(pool, client)

    # Get relevant context
    context = await search_service.search_with_code(
        query=question,
        workspace_id=workspace_id,
        github_token=github_token,
        repo_full_name=repo_full_name,
        top_k=5,
    )

    if not context.results:
        return "No relevant code found for this question.", {}

    # Format context for LLM
    formatted_context = context.format_for_llm()

    # Generate answer
    answer = await client.answer_question(
        question=question,
        context=[r.to_context() for r in context.results],
    )

    return answer, context.get_references()
