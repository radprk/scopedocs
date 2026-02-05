"""Multi-audience documentation generation.

Generates documentation tailored to different audience perspectives:
1. Non-technical (but familiar with tech)
2. Data/AI engineer
3. Backend engineer
4. Frontend engineer/designer
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import asyncpg

from .client import TogetherClient, get_client
from .generation import DocGenerationService, GeneratedDoc


class Audience(str, Enum):
    """Target audience for documentation."""
    NON_TECHNICAL = "non_technical"
    DATA_AI_ENGINEER = "data_ai_engineer"
    BACKEND_ENGINEER = "backend_engineer"
    FRONTEND_DESIGNER = "frontend_designer"


@dataclass
class AudienceProfile:
    """Profile defining how to write for a specific audience."""
    audience: Audience
    display_name: str
    description: str
    system_prompt: str
    doc_structure: List[str]
    focus_areas: List[str]
    avoid: List[str]
    example_questions: List[str]


# =============================================================================
# Audience Profiles with Tailored Prompts
# =============================================================================

AUDIENCE_PROFILES: Dict[Audience, AudienceProfile] = {
    Audience.NON_TECHNICAL: AudienceProfile(
        audience=Audience.NON_TECHNICAL,
        display_name="Product & Business Stakeholders",
        description="Non-technical readers who are familiar with technology concepts but don't write code",
        system_prompt="""You are a technical writer creating documentation for product managers,
business stakeholders, and executives who are tech-savvy but don't write code.

Your writing style should:
- Use plain English, avoiding jargon and technical terms unless necessary
- When technical terms are needed, explain them briefly in parentheses
- Focus on WHAT the code does and WHY, not HOW it does it
- Use analogies and real-world comparisons to explain concepts
- Emphasize business value, user impact, and product implications
- Structure content with clear headings and bullet points for scannability
- Include a TL;DR or Executive Summary at the top
- Mention dependencies on other teams or systems in business terms

Avoid:
- Code snippets or implementation details
- Technical jargon without explanation
- Assuming knowledge of programming concepts
- Deep architectural discussions""",
        doc_structure=[
            "## TL;DR",
            "## What This Does (Business Perspective)",
            "## Why It Matters",
            "## Key Capabilities",
            "## Dependencies & Integrations",
            "## Impact on Users/Product",
        ],
        focus_areas=[
            "Business value and ROI",
            "User-facing features",
            "Product capabilities",
            "Integration points with other products",
            "Timeline and delivery implications",
        ],
        avoid=[
            "Code snippets",
            "Implementation details",
            "Technical architecture diagrams",
            "Performance metrics without context",
        ],
        example_questions=[
            "What problem does this solve for our users?",
            "How does this affect our product roadmap?",
            "What other teams need to be involved?",
            "What's the business impact?",
        ],
    ),

    Audience.DATA_AI_ENGINEER: AudienceProfile(
        audience=Audience.DATA_AI_ENGINEER,
        display_name="Data & AI Engineers",
        description="Engineers working with data pipelines, ML models, embeddings, and AI systems",
        system_prompt="""You are a senior AI/ML engineer writing documentation for other data and AI engineers.

Your writing style should:
- Be technically precise about data flows and model architectures
- Detail embedding dimensions, model choices, and their trade-offs
- Explain chunking strategies, tokenization approaches, and their rationale
- Discuss vector databases, similarity metrics, and search strategies
- Include performance considerations (latency, throughput, memory)
- Reference specific models, libraries, and frameworks used
- Explain the RAG pipeline architecture in detail
- Cover data validation, preprocessing, and quality considerations
- Discuss scalability and batch processing approaches

Include when relevant:
- Model specifications (dimensions, parameters, context windows)
- Embedding strategies and their trade-offs
- Vector indexing approaches (HNSW, IVF, etc.)
- Prompt engineering patterns used
- Data pipeline architecture
- Performance benchmarks and optimization notes""",
        doc_structure=[
            "## Overview",
            "## Data Flow Architecture",
            "## Models & Embeddings",
            "## Vector Storage & Search",
            "## Pipeline Processing",
            "## Performance Considerations",
            "## Configuration & Tuning",
        ],
        focus_areas=[
            "Embedding models and dimensions",
            "Vector similarity search",
            "Chunking and tokenization",
            "RAG pipeline architecture",
            "Batch vs streaming processing",
            "Model inference optimization",
        ],
        avoid=[
            "Basic explanations of ML concepts",
            "Oversimplified diagrams",
            "Ignoring edge cases in data",
        ],
        example_questions=[
            "What embedding model is used and why?",
            "How is the chunking strategy implemented?",
            "What's the vector search query pattern?",
            "How do we handle embedding updates?",
        ],
    ),

    Audience.BACKEND_ENGINEER: AudienceProfile(
        audience=Audience.BACKEND_ENGINEER,
        display_name="Backend Engineers",
        description="Engineers working on APIs, databases, infrastructure, and server-side logic",
        system_prompt="""You are a senior backend engineer writing documentation for other backend engineers.

Your writing style should:
- Be precise about API contracts, request/response formats
- Detail database schemas, indexes, and query patterns
- Explain error handling strategies and edge cases
- Cover authentication, authorization, and security considerations
- Discuss concurrency, async patterns, and performance
- Reference specific frameworks, libraries, and tools
- Include code snippets for key patterns and interfaces
- Explain the service architecture and component interactions
- Cover deployment, configuration, and environment setup

Include when relevant:
- API endpoint signatures and examples
- Database schema details and migrations
- Error codes and handling patterns
- Configuration options and environment variables
- Testing strategies and mocking approaches
- Logging, monitoring, and debugging tips""",
        doc_structure=[
            "## Overview",
            "## API Reference",
            "## Database Schema",
            "## Service Architecture",
            "## Error Handling",
            "## Configuration",
            "## Testing",
        ],
        focus_areas=[
            "API design and contracts",
            "Database queries and performance",
            "Error handling and edge cases",
            "Service communication patterns",
            "Security and authentication",
            "Configuration and deployment",
        ],
        avoid=[
            "Frontend implementation details",
            "UI/UX considerations",
            "Business requirements without technical context",
        ],
        example_questions=[
            "What's the API contract for this endpoint?",
            "How are errors handled and propagated?",
            "What database indexes exist?",
            "How do services communicate?",
        ],
    ),

    Audience.FRONTEND_DESIGNER: AudienceProfile(
        audience=Audience.FRONTEND_DESIGNER,
        display_name="Frontend Engineers & Designers",
        description="Engineers and designers working on UI, UX, and client-side applications",
        system_prompt="""You are a senior frontend engineer writing documentation for frontend developers and designers.

Your writing style should:
- Focus on what the backend provides to the frontend
- Detail API responses and data shapes clearly
- Explain loading states, error states, and edge cases
- Describe the user flows and interactions supported
- Cover real-time updates and WebSocket events if any
- Explain pagination, filtering, and sorting options
- Include example API responses with realistic data
- Discuss rate limits and performance expectations
- Cover authentication flows from the client perspective

Include when relevant:
- API response examples with TypeScript types
- User flow diagrams and state transitions
- Error message formats and how to display them
- Loading and empty states
- Real-time update patterns
- Mobile vs desktop considerations""",
        doc_structure=[
            "## Overview",
            "## User Flows Supported",
            "## API Responses & Data Shapes",
            "## States to Handle",
            "## Real-time Updates",
            "## Error Handling for UI",
            "## Integration Examples",
        ],
        focus_areas=[
            "API response formats",
            "User-facing states (loading, error, empty)",
            "Real-time updates",
            "Pagination and filtering",
            "Authentication from client perspective",
            "Performance and perceived speed",
        ],
        avoid=[
            "Backend implementation details",
            "Database internals",
            "Server infrastructure",
        ],
        example_questions=[
            "What data shape does this endpoint return?",
            "How should loading states be handled?",
            "What error messages should the UI show?",
            "Are there real-time updates?",
        ],
    ),
}


class MultiAudienceDocService:
    """Service for generating documentation for multiple audiences."""

    def __init__(self, pool: asyncpg.Pool, client: Optional[TogetherClient] = None):
        self.pool = pool
        self.client = client or get_client()
        self.base_service = DocGenerationService(pool, client)

    async def generate_for_audience(
        self,
        audience: Audience,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
        code: str,
        language: str,
        commit_sha: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GeneratedDoc:
        """
        Generate documentation for a specific audience.

        Args:
            audience: Target audience
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            file_path: Path to the file
            code: File contents
            language: Programming language
            commit_sha: Current commit SHA
            context: Optional additional context (related files, git history, etc.)

        Returns:
            GeneratedDoc tailored for the audience
        """
        profile = AUDIENCE_PROFILES[audience]

        # Build the prompt with audience-specific instructions
        structure_guide = "\n".join(profile.doc_structure)
        focus_list = "\n".join(f"- {f}" for f in profile.focus_areas)

        context_section = ""
        if context:
            if context.get("git_history"):
                context_section += f"\n\nRecent changes:\n{context['git_history']}"
            if context.get("related_files"):
                context_section += f"\n\nRelated files:\n{context['related_files']}"
            if context.get("readme"):
                context_section += f"\n\nProject README:\n{context['readme'][:1000]}"

        prompt = f"""Generate documentation for the following code, tailored for: {profile.display_name}

Audience description: {profile.description}

File: {file_path}
Language: {language}

Code:
```{language}
{code}
```
{context_section}

Generate documentation following this structure:
{structure_guide}

Focus on these areas:
{focus_list}

Remember: Write from the perspective of what {profile.display_name} need to know and care about."""

        result = await self.client.generate(
            prompt=prompt,
            system_prompt=profile.system_prompt,
            temperature=0.3,
            max_tokens=2000,
        )

        doc_content = result.text
        sections = self.base_service._parse_sections(doc_content)

        # Extract title
        title = f"{file_path.split('/')[-1]} ({profile.display_name})"
        if sections and sections[0].heading:
            title = sections[0].heading

        # Store with audience-specific doc_type
        doc_type = f"file_{audience.value}"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generated_docs (
                    workspace_id, repo_full_name, file_path, doc_type,
                    title, content, source_commit_sha, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (workspace_id, repo_full_name, file_path, doc_type)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    source_commit_sha = EXCLUDED.source_commit_sha,
                    metadata = EXCLUDED.metadata,
                    is_stale = FALSE,
                    version = generated_docs.version + 1,
                    updated_at = NOW()
                RETURNING id
                """,
                workspace_id,
                repo_full_name,
                file_path,
                doc_type,
                title,
                doc_content,
                commit_sha,
                {"audience": audience.value, "profile": profile.display_name},
            )
            doc_id = str(row["id"])

        return GeneratedDoc(
            id=doc_id,
            title=title,
            content=doc_content,
            doc_type=doc_type,
            file_path=file_path,
            sections=sections,
            source_chunks=[],
        )

    async def generate_for_all_audiences(
        self,
        workspace_id: str,
        repo_full_name: str,
        file_path: str,
        code: str,
        language: str,
        commit_sha: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[Audience, GeneratedDoc]:
        """
        Generate documentation for all four audiences.

        Args:
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            file_path: Path to the file
            code: File contents
            language: Programming language
            commit_sha: Current commit SHA
            context: Optional additional context

        Returns:
            Dict mapping Audience to GeneratedDoc
        """
        import asyncio

        results = {}
        tasks = []

        for audience in Audience:
            task = self.generate_for_audience(
                audience=audience,
                workspace_id=workspace_id,
                repo_full_name=repo_full_name,
                file_path=file_path,
                code=code,
                language=language,
                commit_sha=commit_sha,
                context=context,
            )
            tasks.append((audience, task))

        # Run all in parallel
        audience_results = await asyncio.gather(*[t[1] for t in tasks])

        for i, (audience, _) in enumerate(tasks):
            results[audience] = audience_results[i]

        return results

    async def generate_repo_overview_for_audience(
        self,
        audience: Audience,
        workspace_id: str,
        repo_full_name: str,
        readme_content: Optional[str],
        file_summaries: List[Dict[str, str]],
        commit_sha: str,
        git_history: Optional[str] = None,
    ) -> GeneratedDoc:
        """
        Generate a repository overview for a specific audience.

        Args:
            audience: Target audience
            workspace_id: Workspace UUID
            repo_full_name: e.g., "owner/repo"
            readme_content: Contents of README.md if present
            file_summaries: List of dicts with 'path' and 'summary'
            commit_sha: Current commit SHA
            git_history: Optional recent git commit history

        Returns:
            GeneratedDoc with audience-tailored overview
        """
        profile = AUDIENCE_PROFILES[audience]

        # Build file summary
        files_text = "\n".join(
            f"- **{f['path']}**: {f['summary']}"
            for f in file_summaries[:30]
        ) or "No files analyzed yet"

        history_section = ""
        if git_history:
            history_section = f"\n\nRecent development activity:\n{git_history}"

        prompt = f"""Generate a repository overview for {repo_full_name}, tailored for: {profile.display_name}

Audience description: {profile.description}

{"README content:" + chr(10) + readme_content[:2000] if readme_content else "No README found."}

Key files and modules:
{files_text}
{history_section}

Generate an overview following this structure:
# {repo_full_name.split('/')[-1]}

Then include sections relevant for {profile.display_name}, focusing on:
{chr(10).join(f'- {f}' for f in profile.focus_areas)}

Write from the perspective of what {profile.display_name} would want to understand first about this codebase."""

        result = await self.client.generate(
            prompt=prompt,
            system_prompt=profile.system_prompt,
            temperature=0.3,
            max_tokens=2500,
        )

        doc_content = result.text
        sections = self.base_service._parse_sections(doc_content)
        title = f"{repo_full_name.split('/')[-1]} - {profile.display_name} Guide"

        doc_type = f"overview_{audience.value}"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generated_docs (
                    workspace_id, repo_full_name, file_path, doc_type,
                    title, content, source_commit_sha, metadata
                ) VALUES ($1, $2, NULL, $3, $4, $5, $6, $7)
                ON CONFLICT (workspace_id, repo_full_name, file_path, doc_type)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    source_commit_sha = EXCLUDED.source_commit_sha,
                    metadata = EXCLUDED.metadata,
                    is_stale = FALSE,
                    version = generated_docs.version + 1,
                    updated_at = NOW()
                RETURNING id
                """,
                workspace_id,
                repo_full_name,
                doc_type,
                title,
                doc_content,
                commit_sha,
                {"audience": audience.value, "profile": profile.display_name},
            )
            doc_id = str(row["id"])

        return GeneratedDoc(
            id=doc_id,
            title=title,
            content=doc_content,
            doc_type=doc_type,
            file_path=None,
            sections=sections,
            source_chunks=[],
        )

    async def generate_all_repo_overviews(
        self,
        workspace_id: str,
        repo_full_name: str,
        readme_content: Optional[str],
        file_summaries: List[Dict[str, str]],
        commit_sha: str,
        git_history: Optional[str] = None,
    ) -> Dict[Audience, GeneratedDoc]:
        """Generate repo overviews for all audiences."""
        import asyncio

        results = {}
        tasks = []

        for audience in Audience:
            task = self.generate_repo_overview_for_audience(
                audience=audience,
                workspace_id=workspace_id,
                repo_full_name=repo_full_name,
                readme_content=readme_content,
                file_summaries=file_summaries,
                commit_sha=commit_sha,
                git_history=git_history,
            )
            tasks.append((audience, task))

        audience_results = await asyncio.gather(*[t[1] for t in tasks])

        for i, (audience, _) in enumerate(tasks):
            results[audience] = audience_results[i]

        return results

    async def get_docs_by_audience(
        self,
        workspace_id: str,
        audience: Audience,
        repo_full_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all docs for a specific audience."""
        async with self.pool.acquire() as conn:
            query = """
                SELECT id, repo_full_name, file_path, doc_type, title,
                       is_stale, version, created_at, updated_at, metadata
                FROM generated_docs
                WHERE workspace_id = $1
                  AND (doc_type LIKE $2 OR doc_type LIKE $3)
            """
            params = [
                workspace_id,
                f"file_{audience.value}",
                f"overview_{audience.value}",
            ]

            if repo_full_name:
                query += f" AND repo_full_name = ${len(params) + 1}"
                params.append(repo_full_name)

            query += " ORDER BY updated_at DESC"

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]


def get_audience_profile(audience: Audience) -> AudienceProfile:
    """Get the profile for an audience."""
    return AUDIENCE_PROFILES[audience]


def list_audiences() -> List[Dict[str, str]]:
    """List all available audiences with descriptions."""
    return [
        {
            "id": audience.value,
            "name": profile.display_name,
            "description": profile.description,
        }
        for audience, profile in AUDIENCE_PROFILES.items()
    ]
