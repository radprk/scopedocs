"""API routes for AI services."""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import asyncpg

from ..storage.postgres import get_pool
from .client import get_client, TogetherClient
from .embeddings import EmbeddingService, CodeChunk
from .generation import DocGenerationService
from .search import SearchService


router = APIRouter(prefix="/api/ai", tags=["AI"])


# =============================================================================
# Request/Response Models
# =============================================================================

class EmbedCodeRequest(BaseModel):
    workspace_id: str
    repo_full_name: str
    commit_sha: str
    chunks: List[Dict[str, Any]]  # List of {file_path, content, start_line, end_line, chunk_index, language}


class EmbedCodeResponse(BaseModel):
    total_chunks: int
    new_chunks: int
    unchanged_chunks: int
    errors: List[str]


class GenerateDocRequest(BaseModel):
    workspace_id: str
    repo_full_name: str
    file_path: str
    code: str
    language: str
    commit_sha: str


class GenerateDocResponse(BaseModel):
    id: str
    title: str
    content: str
    doc_type: str


class SearchRequest(BaseModel):
    workspace_id: str
    query: str
    repo_full_name: Optional[str] = None
    search_type: Optional[str] = None  # 'code', 'docs', 'messages', 'all'
    limit: int = 10


class SearchResultItem(BaseModel):
    id: str
    source_type: str
    content: str
    file_path: Optional[str]
    repo_full_name: str
    start_line: Optional[int]
    end_line: Optional[int]
    score: float
    metadata: Dict[str, Any]


class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    query: str
    total_found: int


class ChatRequest(BaseModel):
    workspace_id: str
    question: str
    session_id: Optional[str] = None
    repo_full_name: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    session_id: str


class DocCodeLinkResponse(BaseModel):
    doc_id: str
    doc_section: Optional[str]
    file_path: str
    code_line_start: int
    code_line_end: int
    link_type: str
    confidence: float


# =============================================================================
# Routes
# =============================================================================

@router.post("/embed/code", response_model=EmbedCodeResponse)
async def embed_code_chunks(request: EmbedCodeRequest):
    """
    Embed code chunks and store in pgvector.

    This is the main endpoint for indexing code with embeddings.
    Only re-embeds chunks that have changed.
    """
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
            symbol_names=c.get("symbol_names"),
        ))

    result = await service.embed_code_chunks(
        workspace_id=request.workspace_id,
        repo_full_name=request.repo_full_name,
        commit_sha=request.commit_sha,
        chunks=chunks,
    )

    return EmbedCodeResponse(**result)


@router.post("/generate/doc", response_model=GenerateDocResponse)
async def generate_file_doc(request: GenerateDocRequest):
    """
    Generate documentation for a file.

    Uses the LLM to generate markdown documentation,
    then stores it with embeddings for search.
    """
    pool = await get_pool()
    gen_service = DocGenerationService(pool)
    embed_service = EmbeddingService(pool)

    # Generate the doc
    doc = await gen_service.generate_file_doc(
        workspace_id=request.workspace_id,
        repo_full_name=request.repo_full_name,
        file_path=request.file_path,
        code=request.code,
        language=request.language,
        commit_sha=request.commit_sha,
    )

    # Embed the generated doc for search
    await embed_service.embed_document(
        workspace_id=request.workspace_id,
        doc_id=doc.id,
        content=doc.content,
    )

    return GenerateDocResponse(
        id=doc.id,
        title=doc.title,
        content=doc.content,
        doc_type=doc.doc_type,
    )


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    Semantic search across code, docs, and messages.

    Set search_type to filter results:
    - 'code': Search code chunks only
    - 'docs': Search generated docs only
    - 'messages': Search Slack/Linear messages only
    - 'all' or None: Search everything
    """
    pool = await get_pool()
    service = SearchService(pool)

    if request.search_type == "code":
        response = await service.search_code(
            workspace_id=request.workspace_id,
            query=request.query,
            repo_full_name=request.repo_full_name,
            limit=request.limit,
        )
    elif request.search_type == "docs":
        response = await service.search_docs(
            workspace_id=request.workspace_id,
            query=request.query,
            repo_full_name=request.repo_full_name,
            limit=request.limit,
        )
    elif request.search_type == "messages":
        response = await service.search_messages(
            workspace_id=request.workspace_id,
            query=request.query,
            limit=request.limit,
        )
    else:
        # Search all - combine results
        all_results = await service.search_all(
            workspace_id=request.workspace_id,
            query=request.query,
            repo_full_name=request.repo_full_name,
            limit=request.limit,
        )

        # Combine and sort by score
        combined = []
        for key in ["code", "docs", "messages"]:
            combined.extend(all_results[key].results)

        combined.sort(key=lambda x: x.score, reverse=True)
        combined = combined[: request.limit]

        response = type("SearchResponse", (), {
            "results": combined,
            "query": request.query,
            "total_found": len(combined),
        })()

    return SearchResponse(
        results=[
            SearchResultItem(
                id=r.id,
                source_type=r.source_type,
                content=r.content,
                file_path=r.file_path,
                repo_full_name=r.repo_full_name,
                start_line=r.start_line,
                end_line=r.end_line,
                score=r.score,
                metadata=r.metadata,
            )
            for r in response.results
        ],
        query=response.query,
        total_found=response.total_found,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat with the codebase using RAG.

    Retrieves relevant context and generates an answer.
    Maintains chat history per session.
    """
    pool = await get_pool()
    service = SearchService(pool)

    # Create or get session
    session_id = request.session_id
    if not session_id:
        session_id = await service.create_chat_session(
            workspace_id=request.workspace_id,
            repo_full_name=request.repo_full_name,
        )

    # Get chat history if continuing a session
    chat_history = None
    if request.session_id:
        history = await service.get_chat_history(session_id)
        chat_history = [
            {"role": m["role"], "content": m["content"]}
            for m in history
        ]

    # Generate answer
    result = await service.answer_question(
        workspace_id=request.workspace_id,
        question=request.question,
        repo_full_name=request.repo_full_name,
        chat_history=chat_history,
    )

    # Save messages to history
    await service.save_chat_message(
        workspace_id=request.workspace_id,
        session_id=session_id,
        role="user",
        content=request.question,
    )
    await service.save_chat_message(
        workspace_id=request.workspace_id,
        session_id=session_id,
        role="assistant",
        content=result["answer"],
        sources=result["sources"],
    )

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        session_id=session_id,
    )


@router.get("/docs/{workspace_id}")
async def list_docs(
    workspace_id: str,
    repo_full_name: Optional[str] = None,
    doc_type: Optional[str] = None,
):
    """List generated documentation."""
    pool = await get_pool()
    service = DocGenerationService(pool)

    docs = await service.list_docs(
        workspace_id=workspace_id,
        repo_full_name=repo_full_name,
        doc_type=doc_type,
    )

    return {"docs": docs}


@router.get("/docs/{workspace_id}/links/{doc_id}")
async def get_doc_code_links(workspace_id: str, doc_id: str):
    """Get code links for a document (doc ↔ code mapping)."""
    pool = await get_pool()
    service = DocGenerationService(pool)

    links = await service.get_doc_code_links(
        workspace_id=workspace_id,
        doc_id=doc_id,
    )

    return {"links": links}


@router.get("/stats/{workspace_id}")
async def get_ai_stats(
    workspace_id: str,
    repo_full_name: Optional[str] = None,
):
    """Get embedding and indexing statistics."""
    pool = await get_pool()
    service = EmbeddingService(pool)

    stats = await service.get_embedding_stats(
        workspace_id=workspace_id,
        repo_full_name=repo_full_name,
    )

    return {"stats": stats}


@router.get("/chat/sessions/{workspace_id}")
async def list_chat_sessions(workspace_id: str):
    """List chat sessions for a workspace."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, repo_full_name, title, created_at, updated_at
            FROM chat_sessions
            WHERE workspace_id = $1
            ORDER BY updated_at DESC
            LIMIT 50
            """,
            workspace_id,
        )

    return {"sessions": [dict(row) for row in rows]}


@router.get("/chat/history/{session_id}")
async def get_chat_session_history(session_id: str):
    """Get chat history for a session."""
    pool = await get_pool()
    service = SearchService(pool)

    history = await service.get_chat_history(session_id)

    return {"messages": history}


# =============================================================================
# Health check for AI services
# =============================================================================

@router.get("/health")
async def ai_health():
    """Check if AI services are configured and working."""
    import os

    together_key = os.environ.get("TOGETHER_API_KEY")

    return {
        "together_api_configured": bool(together_key),
        "embedding_model": "BAAI/bge-large-en-v1.5",
        "generation_model": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "embedding_dimensions": 1024,
    }
