"""
API routes for AI services (MVP version).

Simple endpoints for:
- Embedding code chunks
- Getting embedding stats
- Health check
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel

from ..storage.postgres import get_pool
from .embeddings import EmbeddingService, CodeChunk


router = APIRouter(prefix="/api/ai", tags=["AI"])


# =============================================================================
# Request/Response Models
# =============================================================================

class EmbedCodeRequest(BaseModel):
    """Request to embed code chunks."""
    workspace_id: str
    repo_full_name: str
    commit_sha: str
    chunks: List[Dict[str, Any]]  # [{file_path, content, start_line, end_line, chunk_index, language}]


class EmbedCodeResponse(BaseModel):
    """Response from embedding code chunks."""
    total_chunks: int
    new_chunks: int
    unchanged_chunks: int
    errors: List[str]


# =============================================================================
# Routes
# =============================================================================

@router.post("/embed/code", response_model=EmbedCodeResponse)
async def embed_code_chunks(request: EmbedCodeRequest):
    """
    Embed code chunks and store in pgvector.

    This is the main endpoint for indexing code with embeddings.
    Only re-embeds chunks that have changed (based on content hash).

    Example request:
    {
        "workspace_id": "uuid-here",
        "repo_full_name": "owner/repo",
        "commit_sha": "abc123",
        "chunks": [
            {
                "file_path": "backend/models.py",
                "content": "class User:\\n    ...",
                "start_line": 1,
                "end_line": 25,
                "chunk_index": 0,
                "language": "python"
            }
        ]
    }
    """
    print(f"\n[API] POST /api/ai/embed/code")
    print(f"  workspace_id: {request.workspace_id}")
    print(f"  repo: {request.repo_full_name}")
    print(f"  chunks to process: {len(request.chunks)}")

    pool = await get_pool()
    service = EmbeddingService(pool)

    # Convert request chunks to CodeChunk objects
    chunks = []
    for c in request.chunks:
        chunks.append(CodeChunk(
            file_path=c["file_path"],
            content=c["content"],
            start_line=c["start_line"],
            end_line=c["end_line"],
            chunk_index=c["chunk_index"],
            language=c.get("language", "unknown"),
        ))

    result = await service.embed_code_chunks(
        workspace_id=request.workspace_id,
        repo_full_name=request.repo_full_name,
        commit_sha=request.commit_sha,
        chunks=chunks,
    )

    print(f"  Result: {result['new_chunks']} new, {result['unchanged_chunks']} unchanged")

    return EmbedCodeResponse(**result)


@router.get("/stats/{workspace_id}")
async def get_ai_stats(
    workspace_id: str,
    repo_full_name: Optional[str] = None,
):
    """
    Get embedding and indexing statistics.

    Returns counts of:
    - Total embeddings
    - Embeddings per repo
    - Files indexed
    """
    print(f"\n[API] GET /api/ai/stats/{workspace_id}")

    pool = await get_pool()
    service = EmbeddingService(pool)

    stats = await service.get_embedding_stats(
        workspace_id=workspace_id,
        repo_full_name=repo_full_name,
    )

    print(f"  Stats: {stats}")

    return {"stats": stats}


@router.get("/health")
async def ai_health():
    """
    Check if AI services are configured.

    Returns status of:
    - Together.ai API key configured
    - Model names being used
    """
    import os

    together_key = os.environ.get("TOGETHER_API_KEY")

    status = {
        "together_api_configured": bool(together_key),
        "embedding_model": "BAAI/bge-large-en-v1.5",
        "embedding_dimensions": 1024,
    }

    print(f"\n[API] GET /api/ai/health")
    print(f"  Status: {status}")

    return status
