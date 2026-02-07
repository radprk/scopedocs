"""
API routes for AI services (MVP version).

Simple endpoints for:
- Embedding code chunks
- Getting embedding stats
- Health check
- Audience-adaptive documentation generation
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage.postgres import get_pool
from .embeddings import EmbeddingService, CodeChunk
from .search import RAGSearchService
from .client import get_client
from .prompts import (
    AudienceType, AudienceContext, STYLE_PRESETS,
    build_generation_prompt, get_component_deep_dive_prompt
)


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


# =============================================================================
# RAG Search & Doc Generation (Testing Endpoints)
# =============================================================================

class SearchRequest(BaseModel):
    """Request for RAG search."""
    query: str
    workspace_id: str
    repo_full_name: Optional[str] = None
    top_k: int = 5


class SearchResult(BaseModel):
    """Single search result."""
    file_path: str
    repo_full_name: str
    start_line: int
    end_line: int
    similarity: float


class SearchResponse(BaseModel):
    """Response from RAG search."""
    query: str
    results: List[SearchResult]
    total_results: int


@router.post("/search", response_model=SearchResponse)
async def search_code(request: SearchRequest):
    """
    Search code using vector similarity.

    Test this to verify:
    1. Embeddings are stored correctly
    2. pgvector search is working
    3. Results are relevant to the query
    """
    print(f"\n[API] POST /api/ai/search")
    print(f"  query: {request.query[:50]}...")
    print(f"  workspace_id: {request.workspace_id}")

    pool = await get_pool()
    search_service = RAGSearchService(pool)

    context = await search_service.search(
        query=request.query,
        workspace_id=request.workspace_id,
        repo_full_name=request.repo_full_name,
        top_k=request.top_k,
    )

    results = [
        SearchResult(
            file_path=r.file_path,
            repo_full_name=r.repo_full_name,
            start_line=r.start_line,
            end_line=r.end_line,
            similarity=r.similarity,
        )
        for r in context.results
    ]

    print(f"  Found {len(results)} results")
    for r in results[:3]:
        print(f"    - {r.file_path}:{r.start_line} (sim={r.similarity:.3f})")

    return SearchResponse(
        query=request.query,
        results=results,
        total_results=len(results),
    )


class GenerateDocRequest(BaseModel):
    """Request to generate documentation."""
    workspace_id: str
    repo_full_name: str
    doc_type: str = "overview"  # overview, file, module
    file_path: Optional[str] = None  # Required for file/module docs
    query: Optional[str] = None  # What to document


class GenerateDocResponse(BaseModel):
    """Generated documentation."""
    title: str
    content: str  # Markdown
    references: Dict[str, Any]
    token_estimate: int


@router.post("/generate-doc", response_model=GenerateDocResponse)
async def generate_documentation(request: GenerateDocRequest):
    """
    Generate documentation using RAG + LLM.

    This:
    1. Searches for relevant code chunks
    2. Assembles context
    3. Calls LLM to generate documentation
    4. Returns markdown with [n] references
    """
    print(f"\n[API] POST /api/ai/generate-doc")
    print(f"  workspace_id: {request.workspace_id}")
    print(f"  repo: {request.repo_full_name}")
    print(f"  doc_type: {request.doc_type}")

    pool = await get_pool()
    client = get_client()
    search_service = RAGSearchService(pool, client)

    # Build search query based on doc_type
    if request.doc_type == "overview":
        search_query = f"Main entry point, architecture, how {request.repo_full_name} works"
    elif request.doc_type == "file" and request.file_path:
        search_query = f"Code in {request.file_path}, what it does, functions, classes"
    elif request.query:
        search_query = request.query
    else:
        search_query = f"How does {request.repo_full_name} work?"

    # Search for relevant code
    context = await search_service.search(
        query=search_query,
        workspace_id=request.workspace_id,
        repo_full_name=request.repo_full_name,
        top_k=8,
    )

    if not context.results:
        raise HTTPException(
            status_code=404,
            detail="No code chunks found. Run indexing and embeddings first."
        )

    # Format context for LLM
    context_parts = []
    references = {}
    for i, result in enumerate(context.results):
        ref = f"[{i+1}]"
        references[ref] = {
            "file_path": result.file_path,
            "start_line": result.start_line,
            "end_line": result.end_line,
        }
        context_parts.append(f"{ref} {result.file_path}:{result.start_line}-{result.end_line}")

    context_summary = "\n".join(context_parts)

    # Generate doc with LLM
    prompt = f"""You are documenting a codebase. Based on the code locations below, generate clear documentation.

Code locations found (most relevant to query "{search_query}"):
{context_summary}

Generate a markdown document that:
1. Explains what this code does
2. References specific files using [n] notation
3. Is concise but thorough

Title the document appropriately for doc_type="{request.doc_type}".
"""

    print(f"  Calling LLM with {len(context.results)} code references...")

    try:
        result = await client.generate(
            prompt=prompt,
            max_tokens=1500,
        )
        doc_content = result.text
    except Exception as e:
        error_msg = str(e)
        print(f"  LLM error: {error_msg}")
        return GenerateDocResponse(
            title="Generation Error",
            content=f"Failed to generate documentation: {error_msg}",
            references=references,
            token_estimate=0,
        )

    # Extract title from first line if it's a heading
    lines = doc_content.strip().split("\n")
    if lines[0].startswith("# "):
        title = lines[0][2:].strip()
        content = "\n".join(lines[1:]).strip()
    else:
        title = f"{request.doc_type.title()} Documentation"
        content = doc_content

    print(f"  Generated doc: {len(content)} chars")

    return GenerateDocResponse(
        title=title,
        content=content,
        references=references,
        token_estimate=len(content.split()) + len(prompt.split()),
    )


# =============================================================================
# Audience-Adaptive Documentation Generation
# =============================================================================

class AdaptiveDocRequest(BaseModel):
    """Request for audience-adaptive documentation."""
    workspace_id: str
    repo_full_name: str

    # Audience configuration
    audience_type: str = "traditional"  # traditional, new_engineer, oncall, custom
    role: Optional[str] = None  # e.g., "AI engineer", "backend developer"
    team: Optional[str] = None  # e.g., "inference team"
    purpose: Optional[str] = None  # What they're trying to understand
    custom_context: Optional[str] = None  # Free-form description of reader

    # Documentation options
    doc_type: str = "overview"  # overview, file, component
    style: str = "narrative"  # concise, narrative, reference, tutorial
    file_path: Optional[str] = None  # For file-specific docs
    component_name: Optional[str] = None  # For component-specific docs


class AdaptiveDocResponse(BaseModel):
    """Generated adaptive documentation."""
    title: str
    content: str  # Markdown
    audience_type: str
    style: str
    references: Dict[str, Any]
    suggested_next: List[str]  # Suggested topics to explore next
    token_estimate: int


@router.post("/generate-adaptive-doc", response_model=AdaptiveDocResponse)
async def generate_adaptive_documentation(request: AdaptiveDocRequest):
    """
    Generate documentation adapted to a specific audience.

    This endpoint creates documentation tailored to:
    - Traditional: Classic wiki-style reference docs
    - New Engineer: Birds-eye view for onboarding
    - On-Call: Quick reference for incident response
    - Custom: Documentation tailored to a specific user-provided context
    """
    print(f"\n[API] POST /api/ai/generate-adaptive-doc")
    print(f"  workspace_id: {request.workspace_id}")
    print(f"  repo: {request.repo_full_name}")
    print(f"  audience: {request.audience_type}")
    print(f"  style: {request.style}")

    pool = await get_pool()
    client = get_client()
    search_service = RAGSearchService(pool, client)

    # Parse audience type
    try:
        audience_type = AudienceType(request.audience_type)
    except ValueError:
        audience_type = AudienceType.TRADITIONAL

    # Build audience context
    audience = AudienceContext(
        audience_type=audience_type,
        role=request.role,
        team=request.team,
        purpose=request.purpose,
        custom_context=request.custom_context,
    )

    # Build search query based on audience and purpose
    if request.file_path:
        search_query = f"Code in {request.file_path}, functions, classes, implementation"
    elif request.component_name:
        search_query = f"{request.component_name} implementation, how it works, dependencies"
    elif request.purpose:
        search_query = f"{request.purpose} implementation, architecture, key components"
    elif audience_type == AudienceType.ONCALL:
        search_query = f"Error handling, critical paths, dependencies, failure modes in {request.repo_full_name}"
    elif audience_type == AudienceType.NEW_ENGINEER:
        search_query = f"Main entry points, architecture overview, key concepts in {request.repo_full_name}"
    else:
        search_query = f"Architecture, main components, how {request.repo_full_name} works"

    print(f"  search_query: {search_query[:80]}...")

    # Search for relevant code
    context = await search_service.search(
        query=search_query,
        workspace_id=request.workspace_id,
        repo_full_name=request.repo_full_name,
        top_k=10,  # More context for adaptive docs
    )

    if not context.results:
        raise HTTPException(
            status_code=404,
            detail="No code chunks found. Run indexing and embeddings first."
        )

    # Format context for LLM
    context_parts = []
    references = {}
    for i, result in enumerate(context.results):
        ref = f"[{i+1}]"
        references[ref] = {
            "file_path": result.file_path,
            "start_line": result.start_line,
            "end_line": result.end_line,
            "repo": result.repo_full_name,
        }
        context_parts.append(f"{ref} {result.file_path}:{result.start_line}-{result.end_line}")

    context_summary = "\n".join(context_parts)

    # Build prompts using the prompts module
    system_prompt, user_prompt = build_generation_prompt(
        audience=audience,
        context_summary=context_summary,
        repo_name=request.repo_full_name,
        doc_type=request.doc_type,
        style=request.style,
    )

    print(f"  Calling LLM with {len(context.results)} code references...")

    try:
        result = await client.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=3000,  # More tokens for comprehensive docs
            temperature=0.2,
        )
        doc_content = result.text
    except Exception as e:
        error_msg = str(e)
        print(f"  LLM error: {error_msg}")
        return AdaptiveDocResponse(
            title="Generation Error",
            content=f"Failed to generate documentation: {error_msg}",
            audience_type=request.audience_type,
            style=request.style,
            references=references,
            suggested_next=[],
            token_estimate=0,
        )

    # Extract title from first line if it's a heading
    lines = doc_content.strip().split("\n")
    if lines[0].startswith("# "):
        title = lines[0][2:].strip()
        content = "\n".join(lines[1:]).strip()
    else:
        title = f"{request.repo_full_name} - {request.doc_type.title()}"
        content = doc_content

    # Generate suggested next topics based on references
    suggested_next = []
    unique_files = set()
    for ref_data in references.values():
        file_path = ref_data["file_path"]
        if file_path not in unique_files:
            unique_files.add(file_path)
            # Extract component name from path
            parts = file_path.replace("\\", "/").split("/")
            if len(parts) > 1:
                suggested_next.append(f"Deep dive: {parts[-1]}")
    suggested_next = suggested_next[:5]  # Limit to 5 suggestions

    print(f"  Generated doc: {len(content)} chars, {len(suggested_next)} suggestions")

    return AdaptiveDocResponse(
        title=title,
        content=content,
        audience_type=request.audience_type,
        style=request.style,
        references=references,
        suggested_next=suggested_next,
        token_estimate=len(content.split()) + len(user_prompt.split()),
    )


@router.get("/doc-styles")
async def get_documentation_styles():
    """
    Get available documentation styles.

    Returns the style presets that can be used with generate-adaptive-doc.
    """
    return {
        "styles": [
            {
                "id": style_id,
                "name": style_data["name"],
                "description": style_data["description"],
            }
            for style_id, style_data in STYLE_PRESETS.items()
        ],
        "audience_types": [
            {"id": "traditional", "name": "Traditional Wiki", "description": "Classic reference documentation"},
            {"id": "new_engineer", "name": "New Team Member", "description": "Top-down onboarding view"},
            {"id": "oncall", "name": "On-Call Guide", "description": "Quick incident response docs"},
            {"id": "custom", "name": "Custom Purpose", "description": "Tell us what you need"},
        ]
    }
