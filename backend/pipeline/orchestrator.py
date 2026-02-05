"""
Pipeline Orchestrator - ties together the entire ingestion flow.

This is the main entry point for:
1. Code ingestion: GitHub → Chunking → Embeddings → Docs
2. Traceability extraction: PRs → Linear tickets → Code
3. Message processing: Slack/Linear → Embeddings → Links

The orchestrator ensures:
- Only changed files are re-processed (via content hashing)
- Proper error handling and logging
- Progress tracking for the UI
"""

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from enum import Enum
import asyncpg

# Add code-indexing to path for chunker import
sys.path.insert(0, str(__file__).replace("backend/pipeline/orchestrator.py", "code-indexing/src"))

from .github_fetcher import GitHubFetcher, get_fetcher_for_workspace
from .traceability import TraceabilityExtractor, ArtifactType

logger = logging.getLogger(__name__)


class PipelineStage(str, Enum):
    """Stages of the pipeline."""
    FETCH = "fetch"
    CHUNK = "chunk"
    EMBED = "embed"
    GENERATE_DOC = "generate_doc"
    LINK_DOC_CODE = "link_doc_code"
    EXTRACT_TRACEABILITY = "extract_traceability"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class PipelineProgress:
    """Progress information for a pipeline run."""
    stage: PipelineStage
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    docs_generated: int = 0
    links_created: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "total_chunks": self.total_chunks,
            "embedded_chunks": self.embedded_chunks,
            "docs_generated": self.docs_generated,
            "links_created": self.links_created,
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PipelineResult:
    """Result of a pipeline run."""
    success: bool
    progress: PipelineProgress
    repo_full_name: str
    commit_sha: str
    files_processed: List[str] = field(default_factory=list)
    docs_created: List[Dict[str, str]] = field(default_factory=list)
    traceability_links: int = 0


class PipelineOrchestrator:
    """
    Orchestrates the full ingestion pipeline.

    Usage:
        orchestrator = PipelineOrchestrator(pool)

        # Process a repository
        result = await orchestrator.process_repository(
            workspace_id="...",
            repo_full_name="owner/repo",
            on_progress=lambda p: print(f"Stage: {p.stage}"),
        )

        # Process just PRs for traceability
        await orchestrator.process_prs_for_traceability(
            workspace_id="...",
            repo_full_name="owner/repo",
        )
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._progress_callbacks: List[Callable[[PipelineProgress], None]] = []

    async def process_repository(
        self,
        workspace_id: str,
        repo_full_name: str,
        ref: Optional[str] = None,
        generate_docs: bool = True,
        extract_traceability: bool = True,
        on_progress: Optional[Callable[[PipelineProgress], None]] = None,
    ) -> PipelineResult:
        """
        Process a full repository through the pipeline.

        Args:
            workspace_id: Workspace UUID
            repo_full_name: Repository in owner/repo format
            ref: Branch/tag/commit (default: default branch)
            generate_docs: Whether to generate documentation
            extract_traceability: Whether to extract traceability links
            on_progress: Callback for progress updates

        Returns:
            PipelineResult with processing summary
        """
        progress = PipelineProgress(
            stage=PipelineStage.FETCH,
            started_at=datetime.utcnow(),
        )

        def update_progress(stage: PipelineStage = None, **kwargs):
            if stage:
                progress.stage = stage
            for key, value in kwargs.items():
                setattr(progress, key, value)
            if on_progress:
                on_progress(progress)
            logger.info(f"Pipeline progress: {progress.stage.value} - {kwargs}")

        try:
            # Get GitHub fetcher
            fetcher = await get_fetcher_for_workspace(workspace_id)
            if not fetcher:
                raise ValueError("GitHub not connected for this workspace")

            # Get latest commit
            commit = await fetcher.get_latest_commit(repo_full_name, ref)
            commit_sha = commit.sha if commit else "unknown"

            print(f"\n{'='*60}")
            print(f"PIPELINE: Processing {repo_full_name}")
            print(f"Commit: {commit_sha[:8] if commit else 'unknown'}")
            print(f"{'='*60}\n")

            # Stage 1: Fetch files
            update_progress(PipelineStage.FETCH)
            print(f"[1/6] FETCHING files from GitHub...")

            files = await fetcher.fetch_repo_files(repo_full_name, ref)
            update_progress(total_files=len(files))
            print(f"      Found {len(files)} code files")

            # Stage 2: Chunk files
            update_progress(PipelineStage.CHUNK)
            print(f"\n[2/6] CHUNKING files with AST-aware chunker...")

            all_chunks = []
            for i, file in enumerate(files):
                try:
                    chunks = await self._chunk_file(file.path, file.content)
                    for chunk in chunks:
                        all_chunks.append({
                            "file_path": file.path,
                            "content": chunk.content,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "chunk_index": chunk.chunk_index,
                            "chunk_hash": chunk.chunk_hash,
                            "language": self._detect_language(file.path),
                        })
                    update_progress(processed_files=i + 1)
                    print(f"      [{i+1}/{len(files)}] {file.path} → {len(chunks)} chunks")
                except Exception as e:
                    progress.errors.append(f"Chunk error for {file.path}: {str(e)}")
                    logger.error(f"Error chunking {file.path}: {e}")

            update_progress(total_chunks=len(all_chunks))
            print(f"      Total: {len(all_chunks)} chunks from {len(files)} files")

            # Stage 3: Generate embeddings
            update_progress(PipelineStage.EMBED)
            print(f"\n[3/6] GENERATING embeddings...")

            embedded_count = await self._embed_chunks(
                workspace_id, repo_full_name, commit_sha, all_chunks, update_progress
            )
            update_progress(embedded_chunks=embedded_count)
            print(f"      Embedded {embedded_count} chunks")

            # Stage 4: Generate documentation
            docs_created = []
            if generate_docs:
                update_progress(PipelineStage.GENERATE_DOC)
                print(f"\n[4/6] GENERATING documentation...")

                docs_created = await self._generate_docs(
                    workspace_id, repo_full_name, commit_sha, files, update_progress
                )
                update_progress(docs_generated=len(docs_created))
                print(f"      Generated {len(docs_created)} documents")
            else:
                print(f"\n[4/6] SKIPPING documentation generation")

            # Stage 5: Create doc-code links
            links_count = 0
            if generate_docs and docs_created:
                update_progress(PipelineStage.LINK_DOC_CODE)
                print(f"\n[5/6] CREATING doc ↔ code links...")

                links_count = await self._create_doc_code_links(
                    workspace_id, repo_full_name, docs_created, all_chunks
                )
                update_progress(links_created=links_count)
                print(f"      Created {links_count} links")
            else:
                print(f"\n[5/6] SKIPPING doc-code links")

            # Stage 6: Extract traceability
            traceability_count = 0
            if extract_traceability:
                update_progress(PipelineStage.EXTRACT_TRACEABILITY)
                print(f"\n[6/6] EXTRACTING traceability links...")

                traceability_count = await self.process_prs_for_traceability(
                    workspace_id, repo_full_name
                )
                print(f"      Created {traceability_count} traceability links")
            else:
                print(f"\n[6/6] SKIPPING traceability extraction")

            # Complete
            update_progress(PipelineStage.COMPLETE)
            progress.completed_at = datetime.utcnow()

            print(f"\n{'='*60}")
            print(f"PIPELINE COMPLETE")
            print(f"  Files: {len(files)}")
            print(f"  Chunks: {len(all_chunks)}")
            print(f"  Embedded: {embedded_count}")
            print(f"  Docs: {len(docs_created)}")
            print(f"  Doc-Code Links: {links_count}")
            print(f"  Traceability Links: {traceability_count}")
            print(f"  Errors: {len(progress.errors)}")
            print(f"{'='*60}\n")

            await fetcher.close()

            return PipelineResult(
                success=True,
                progress=progress,
                repo_full_name=repo_full_name,
                commit_sha=commit_sha,
                files_processed=[f.path for f in files],
                docs_created=docs_created,
                traceability_links=traceability_count,
            )

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            progress.stage = PipelineStage.FAILED
            progress.errors.append(str(e))
            progress.completed_at = datetime.utcnow()

            print(f"\n{'='*60}")
            print(f"PIPELINE FAILED: {e}")
            print(f"{'='*60}\n")

            return PipelineResult(
                success=False,
                progress=progress,
                repo_full_name=repo_full_name,
                commit_sha="unknown",
            )

    async def _chunk_file(self, file_path: str, content: str) -> List[Any]:
        """Chunk a file using the AST-aware chunker."""
        try:
            from indexing.chunker import chunk_code_file
            return chunk_code_file(content, file_path)
        except ImportError:
            # Fallback if code-indexing module not in path
            logger.warning("Using fallback chunker (code-indexing module not found)")
            return self._fallback_chunk(content, file_path)

    def _fallback_chunk(self, content: str, file_path: str) -> List[Any]:
        """Simple fallback chunker."""
        from dataclasses import dataclass
        import hashlib

        @dataclass
        class SimpleChunk:
            content: str
            start_line: int
            end_line: int
            chunk_hash: str
            chunk_index: int

        lines = content.split("\n")
        chunk_size = 50  # Lines per chunk

        chunks = []
        for i in range(0, len(lines), chunk_size):
            chunk_lines = lines[i:i + chunk_size]
            chunk_content = "\n".join(chunk_lines)
            chunks.append(SimpleChunk(
                content=chunk_content,
                start_line=i + 1,
                end_line=min(i + chunk_size, len(lines)),
                chunk_hash=hashlib.sha256(chunk_content.encode()).hexdigest(),
                chunk_index=len(chunks),
            ))

        return chunks

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".sql": "sql",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return "unknown"

    async def _embed_chunks(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        chunks: List[Dict],
        update_progress: Callable,
    ) -> int:
        """Embed chunks using the AI service."""
        try:
            from backend.ai.embeddings import EmbeddingService, CodeChunk

            service = EmbeddingService(self.pool)

            # Convert to CodeChunk objects
            code_chunks = []
            for c in chunks:
                chunk = CodeChunk(
                    file_path=c["file_path"],
                    content=c["content"],
                    start_line=c["start_line"],
                    end_line=c["end_line"],
                    chunk_index=c["chunk_index"],
                    language=c["language"],
                )
                chunk._content_hash = c["chunk_hash"]
                code_chunks.append(chunk)

            result = await service.embed_code_chunks(
                workspace_id=workspace_id,
                repo_full_name=repo_full_name,
                commit_sha=commit_sha,
                chunks=code_chunks,
            )

            return result["new_chunks"] + result["unchanged_chunks"]

        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            # Return 0 but don't fail the pipeline
            return 0

    async def _generate_docs(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        files: List[Any],
        update_progress: Callable,
    ) -> List[Dict[str, str]]:
        """Generate documentation for files."""
        try:
            from backend.ai.generation import DocGenerationService
            from backend.ai.embeddings import EmbeddingService

            gen_service = DocGenerationService(self.pool)
            embed_service = EmbeddingService(self.pool)

            docs = []
            for i, file in enumerate(files[:20]):  # Limit to first 20 files for MVP
                try:
                    # Generate doc
                    doc = await gen_service.generate_file_doc(
                        workspace_id=workspace_id,
                        repo_full_name=repo_full_name,
                        file_path=file.path,
                        code=file.content,
                        language=self._detect_language(file.path),
                        commit_sha=commit_sha,
                    )

                    # Embed the doc
                    await embed_service.embed_document(
                        workspace_id=workspace_id,
                        doc_id=doc.id,
                        content=doc.content,
                    )

                    docs.append({
                        "id": doc.id,
                        "file_path": file.path,
                        "title": doc.title,
                    })

                    print(f"        Generated doc for {file.path}")

                except Exception as e:
                    logger.error(f"Doc generation failed for {file.path}: {e}")

            return docs

        except Exception as e:
            logger.error(f"Doc generation failed: {e}")
            return []

    async def _create_doc_code_links(
        self,
        workspace_id: str,
        repo_full_name: str,
        docs: List[Dict],
        chunks: List[Dict],
    ) -> int:
        """Create links between documentation and code."""
        try:
            from backend.ai.generation import DocGenerationService

            service = DocGenerationService(self.pool)
            total_links = 0

            for doc in docs:
                # Find chunks for this file
                file_chunks = [
                    c for c in chunks
                    if c["file_path"] == doc["file_path"]
                ]

                if not file_chunks:
                    continue

                # Get the full doc content
                doc_data = await service.get_doc(
                    workspace_id=workspace_id,
                    repo_full_name=repo_full_name,
                    file_path=doc["file_path"],
                    doc_type="file",
                )

                if not doc_data:
                    continue

                # Create links
                links = await service.create_doc_code_links(
                    workspace_id=workspace_id,
                    doc_id=doc["id"],
                    doc_content=doc_data["content"],
                    repo_full_name=repo_full_name,
                    file_path=doc["file_path"],
                    code_chunks=[
                        {
                            "id": None,  # We don't have embedding IDs yet
                            "start_line": c["start_line"],
                            "end_line": c["end_line"],
                            "content": c["content"],
                        }
                        for c in file_chunks
                    ],
                )
                total_links += links

            return total_links

        except Exception as e:
            logger.error(f"Doc-code linking failed: {e}")
            return 0

    async def process_prs_for_traceability(
        self,
        workspace_id: str,
        repo_full_name: str,
        limit: int = 100,
    ) -> int:
        """
        Process PRs to extract traceability links.

        Args:
            workspace_id: Workspace UUID
            repo_full_name: Repository name
            limit: Max PRs to process

        Returns:
            Number of traceability links created
        """
        # Get Linear team keys for this workspace
        extractor = TraceabilityExtractor(self.pool)
        team_keys = await extractor.get_team_keys_from_linear(workspace_id)

        if team_keys:
            # Recreate extractor with team keys
            extractor = TraceabilityExtractor(self.pool, team_keys=team_keys)
            print(f"      Using Linear team keys: {team_keys}")

        # Get GitHub fetcher
        fetcher = await get_fetcher_for_workspace(workspace_id)
        if not fetcher:
            logger.warning("GitHub not connected, skipping PR traceability")
            return 0

        # Fetch PRs
        owner, repo = repo_full_name.split("/")
        total_links = 0

        try:
            from backend.integrations.auth import get_integration_token
            import httpx

            token = await get_integration_token("github", workspace_id)
            if not token:
                return 0

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/pulls",
                    headers={
                        "Authorization": f"Bearer {token.access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    params={"state": "all", "per_page": limit}
                )

                if response.status_code != 200:
                    logger.error(f"Failed to fetch PRs: {response.status_code}")
                    return 0

                prs = response.json()

                for pr in prs:
                    # Get files changed
                    pr_details = await fetcher.get_pull_request(repo_full_name, pr["number"])
                    if not pr_details:
                        continue

                    # Extract links
                    result = extractor.extract_from_pr(
                        pr_number=pr["number"],
                        pr_title=pr["title"],
                        pr_body=pr.get("body"),
                        files_changed=[f["filename"] for f in pr_details.get("files", [])],
                        repo_full_name=repo_full_name,
                    )

                    # Store links
                    stored = await extractor.store_links(workspace_id, result.links)
                    total_links += stored

                    if result.ticket_refs_found:
                        print(f"        PR #{pr['number']}: {result.ticket_refs_found}")

        except Exception as e:
            logger.error(f"PR traceability extraction failed: {e}")

        await fetcher.close()
        return total_links


# Convenience function
async def run_pipeline(
    workspace_id: str,
    repo_full_name: str,
    pool: asyncpg.Pool,
    **kwargs,
) -> PipelineResult:
    """
    Convenience function to run the full pipeline.

    Args:
        workspace_id: Workspace UUID
        repo_full_name: Repository in owner/repo format
        pool: Database connection pool
        **kwargs: Additional arguments for process_repository

    Returns:
        PipelineResult
    """
    orchestrator = PipelineOrchestrator(pool)
    return await orchestrator.process_repository(
        workspace_id=workspace_id,
        repo_full_name=repo_full_name,
        **kwargs,
    )
