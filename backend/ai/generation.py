"""Documentation generation service."""

import json
import re
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import asyncpg

from .client import TogetherClient, get_client


@dataclass
class DocSection:
    """A section within generated documentation."""
    heading: str
    content: str
    start_line: int
    end_line: int


@dataclass
class GeneratedDoc:
    """A generated documentation document."""
    id: str
    title: str
    content: str
    doc_type: str
    file_path: Optional[str]
    sections: List[DocSection]
    source_chunks: List[str]


class DocGenerationService:
    """Service for generating documentation from code."""

    def __init__(self, pool: asyncpg.Pool, client: Optional[TogetherClient] = None):
        self.pool = pool
        self.client = client or get_client()

    async def generate_file_doc(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
        code: str,
        language: str,
        commit_sha: str,
        source_chunk_ids: Optional[List[str]] = None,
    ) -> GeneratedDoc:
        """
        Generate documentation for a single file.

        Args:
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            file_path: Path to the file
            code: File contents
            language: Programming language
            commit_sha: Current commit SHA
            source_chunk_ids: Optional list of code_embedding IDs

        Returns:
            GeneratedDoc with the documentation
        """
        # Generate documentation using LLM
        doc_content = await self.client.generate_code_doc(
            code=code,
            file_path=file_path,
            language=language,
            doc_type="file",
        )

        # Parse sections from the markdown
        sections = self._parse_sections(doc_content)

        # Extract title from first heading or file name
        title = file_path.split("/")[-1]
        if sections and sections[0].heading:
            title = sections[0].heading

        # Store in database
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generated_docs (
                    workspace_id, repo_full_name, file_path, doc_type,
                    title, content, source_chunks, source_commit_sha
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (workspace_id, repo_full_name, file_path, doc_type)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    source_chunks = EXCLUDED.source_chunks,
                    source_commit_sha = EXCLUDED.source_commit_sha,
                    is_stale = FALSE,
                    version = generated_docs.version + 1,
                    updated_at = NOW()
                RETURNING id
                """,
                workspace_id,
                repo_full_name,
                file_path,
                "file",
                title,
                doc_content,
                source_chunk_ids or [],
                commit_sha,
            )
            doc_id = str(row["id"])

        return GeneratedDoc(
            id=doc_id,
            title=title,
            content=doc_content,
            doc_type="file",
            file_path=file_path,
            sections=sections,
            source_chunks=source_chunk_ids or [],
        )

    async def generate_module_overview(
        self,
        workspace_id: str,
        repo_full_name: str,
        module_path: str,
        file_docs: List[Dict[str, str]],
        commit_sha: str,
    ) -> GeneratedDoc:
        """
        Generate an overview document for a module/directory.

        Args:
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            module_path: Path to the module/directory
            file_docs: List of dicts with 'file_path' and 'summary'
            commit_sha: Current commit SHA

        Returns:
            GeneratedDoc with the module overview
        """
        # Build context from file summaries
        file_summaries = "\n".join(
            f"- **{d['file_path']}**: {d['summary']}"
            for d in file_docs
        )

        prompt = f"""Generate a module overview for: {module_path}

This module contains the following files:
{file_summaries}

Generate a markdown document with:
1. A one-line summary of this module's purpose
2. ## Overview - what this module does
3. ## Components - key files and their roles
4. ## Architecture - how the components work together
5. ## Entry Points - where to start reading the code"""

        system_prompt = """You are a technical documentation expert. Generate clear,
scannable documentation that helps developers understand modules quickly."""

        result = await self.client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
        )

        doc_content = result.text
        sections = self._parse_sections(doc_content)
        title = module_path.split("/")[-1] or "Root"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generated_docs (
                    workspace_id, repo_full_name, file_path, doc_type,
                    title, content, source_commit_sha
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (workspace_id, repo_full_name, file_path, doc_type)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    source_commit_sha = EXCLUDED.source_commit_sha,
                    is_stale = FALSE,
                    version = generated_docs.version + 1,
                    updated_at = NOW()
                RETURNING id
                """,
                workspace_id,
                repo_full_name,
                module_path,
                "module",
                title,
                doc_content,
                commit_sha,
            )
            doc_id = str(row["id"])

        return GeneratedDoc(
            id=doc_id,
            title=title,
            content=doc_content,
            doc_type="module",
            file_path=module_path,
            sections=sections,
            source_chunks=[],
        )

    async def generate_repo_overview(
        self,
        workspace_id: str,
        repo_full_name: str,
        readme_content: Optional[str],
        top_level_files: List[str],
        module_summaries: List[Dict[str, str]],
        commit_sha: str,
    ) -> GeneratedDoc:
        """
        Generate a repository-level overview.

        Args:
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            readme_content: Contents of README.md if present
            top_level_files: List of top-level file names
            module_summaries: List of dicts with 'path' and 'summary'
            commit_sha: Current commit SHA

        Returns:
            GeneratedDoc with the repo overview
        """
        modules_text = "\n".join(
            f"- **{m['path']}**: {m['summary']}"
            for m in module_summaries
        ) or "No modules detected"

        prompt = f"""Generate a repository overview for: {repo_full_name}

{"README content:" + chr(10) + readme_content[:2000] if readme_content else "No README found."}

Top-level files: {', '.join(top_level_files[:20])}

Modules/directories:
{modules_text}

Generate a markdown document with:
1. # {repo_full_name.split('/')[-1]} - one-line description
2. ## What is this? - brief explanation
3. ## Architecture - high-level structure
4. ## Key Modules - main components and their purposes
5. ## Getting Started - where to begin (based on file structure)"""

        system_prompt = """You are a technical documentation expert creating
onboarding documentation. Make it welcoming and easy to navigate."""

        result = await self.client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
        )

        doc_content = result.text
        sections = self._parse_sections(doc_content)
        title = repo_full_name.split("/")[-1]

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generated_docs (
                    workspace_id, repo_full_name, file_path, doc_type,
                    title, content, source_commit_sha
                ) VALUES ($1, $2, NULL, $3, $4, $5, $6)
                ON CONFLICT (workspace_id, repo_full_name, file_path, doc_type)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    source_commit_sha = EXCLUDED.source_commit_sha,
                    is_stale = FALSE,
                    version = generated_docs.version + 1,
                    updated_at = NOW()
                RETURNING id
                """,
                workspace_id,
                repo_full_name,
                "overview",
                title,
                doc_content,
                commit_sha,
            )
            doc_id = str(row["id"])

        return GeneratedDoc(
            id=doc_id,
            title=title,
            content=doc_content,
            doc_type="overview",
            file_path=None,
            sections=sections,
            source_chunks=[],
        )

    async def create_doc_code_links(
        self,
        workspace_id: str,
        doc_id: str,
        doc_content: str,
        repo_full_name: str,
        file_path: str,
        code_chunks: List[Dict[str, Any]],
    ) -> int:
        """
        Create links between documentation sections and code.

        This enables the "click on doc → jump to code" feature.

        Args:
            workspace_id: Workspace UUID
            doc_id: Generated doc ID
            doc_content: The documentation content
            repo_full_name: Repository name
            file_path: File path being documented
            code_chunks: List of chunks with id, start_line, end_line, content

        Returns:
            Number of links created
        """
        # Parse doc into sections
        sections = self._parse_sections(doc_content)
        links_created = 0

        # Use LLM to match sections to code
        for section in sections:
            if not section.content.strip():
                continue

            # Find which code chunks this section refers to
            prompt = f"""Given this documentation section and code chunks, identify which chunks are being described.

Documentation section:
## {section.heading}
{section.content}

Code chunks:
{chr(10).join(f'[Chunk {i}] Lines {c["start_line"]}-{c["end_line"]}:{chr(10)}{c["content"][:500]}' for i, c in enumerate(code_chunks))}

Return only the chunk numbers (0-indexed) that this documentation describes, comma-separated.
If none match, return "none".
Example: 0, 2, 3"""

            result = await self.client.generate(
                prompt=prompt,
                max_tokens=50,
                temperature=0.0,
            )

            response = result.text.strip().lower()
            if response == "none":
                continue

            # Parse chunk indices
            try:
                indices = [int(x.strip()) for x in response.split(",") if x.strip().isdigit()]
            except ValueError:
                continue

            # Create links for matched chunks
            async with self.pool.acquire() as conn:
                for idx in indices:
                    if idx >= len(code_chunks):
                        continue
                    chunk = code_chunks[idx]

                    await conn.execute(
                        """
                        INSERT INTO doc_code_links (
                            workspace_id, doc_id, doc_section,
                            doc_line_start, doc_line_end,
                            code_embedding_id, repo_full_name, file_path,
                            code_line_start, code_line_end, link_type, confidence
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        ON CONFLICT DO NOTHING
                        """,
                        workspace_id,
                        doc_id,
                        section.heading,
                        section.start_line,
                        section.end_line,
                        chunk.get("id"),
                        repo_full_name,
                        file_path,
                        chunk["start_line"],
                        chunk["end_line"],
                        "explains",
                        0.8,
                    )
                    links_created += 1

        return links_created

    async def mark_docs_stale(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_paths: List[str],
    ):
        """Mark documentation as stale when code changes."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generated_docs
                SET is_stale = TRUE, updated_at = NOW()
                WHERE workspace_id = $1
                  AND repo_full_name = $2
                  AND file_path = ANY($3)
                """,
                workspace_id,
                repo_full_name,
                file_paths,
            )

    async def get_doc(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: Optional[str],
        doc_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Get a generated document."""
        async with self.pool.acquire() as conn:
            if file_path:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM generated_docs
                    WHERE workspace_id = $1
                      AND repo_full_name = $2
                      AND file_path = $3
                      AND doc_type = $4
                    """,
                    workspace_id,
                    repo_full_name,
                    file_path,
                    doc_type,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM generated_docs
                    WHERE workspace_id = $1
                      AND repo_full_name = $2
                      AND file_path IS NULL
                      AND doc_type = $3
                    """,
                    workspace_id,
                    repo_full_name,
                    doc_type,
                )
            return dict(row) if row else None

    async def get_doc_code_links(
        self,
        workspace_id: str,
        doc_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all code links for a document."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM doc_code_links
                WHERE workspace_id = $1 AND doc_id = $2
                ORDER BY doc_line_start
                """,
                workspace_id,
                doc_id,
            )
            return [dict(row) for row in rows]

    async def list_docs(
        self,
        workspace_id: str,
        repo_full_name: Optional[str] = None,
        doc_type: Optional[str] = None,
        include_stale: bool = True,
    ) -> List[Dict[str, Any]]:
        """List generated documents."""
        async with self.pool.acquire() as conn:
            query = """
                SELECT id, repo_full_name, file_path, doc_type, title,
                       is_stale, version, created_at, updated_at
                FROM generated_docs
                WHERE workspace_id = $1
            """
            params = [workspace_id]

            if repo_full_name:
                query += f" AND repo_full_name = ${len(params) + 1}"
                params.append(repo_full_name)

            if doc_type:
                query += f" AND doc_type = ${len(params) + 1}"
                params.append(doc_type)

            if not include_stale:
                query += " AND is_stale = FALSE"

            query += " ORDER BY updated_at DESC"

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    def _parse_sections(self, markdown: str) -> List[DocSection]:
        """Parse markdown into sections based on headings."""
        sections = []
        lines = markdown.split("\n")
        current_section = None
        current_content = []
        current_start = 0

        for i, line in enumerate(lines):
            # Check for heading
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                # Save previous section
                if current_section is not None:
                    sections.append(DocSection(
                        heading=current_section,
                        content="\n".join(current_content).strip(),
                        start_line=current_start,
                        end_line=i - 1,
                    ))
                current_section = heading_match.group(2)
                current_content = []
                current_start = i
            else:
                current_content.append(line)

        # Save last section
        if current_section is not None:
            sections.append(DocSection(
                heading=current_section,
                content="\n".join(current_content).strip(),
                start_line=current_start,
                end_line=len(lines) - 1,
            ))

        return sections
