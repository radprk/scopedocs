"""
Mock data generator for testing the ScopeDocs pipeline.

Generates realistic mock data for:
- GitHub files and PRs
- Slack messages
- Linear issues

This allows testing the full pipeline without real API connections.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid


@dataclass
class MockFile:
    """Mock GitHub file."""
    path: str
    content: str
    sha: str = ""

    def __post_init__(self):
        if not self.sha:
            self.sha = hashlib.sha1(self.content.encode()).hexdigest()


@dataclass
class MockPR:
    """Mock GitHub pull request."""
    number: int
    title: str
    body: str
    files_changed: List[str]
    author: str = "developer"
    state: str = "merged"
    created_at: str = ""


@dataclass
class MockSlackMessage:
    """Mock Slack message."""
    id: str
    channel: str
    text: str
    user: str
    timestamp: str


@dataclass
class MockLinearIssue:
    """Mock Linear issue."""
    id: str
    identifier: str  # e.g., "SD-123"
    title: str
    description: str
    state: str
    assignee: Optional[str] = None


@dataclass
class MockDataSet:
    """Complete set of mock data for testing."""
    files: List[MockFile] = field(default_factory=list)
    prs: List[MockPR] = field(default_factory=list)
    slack_messages: List[MockSlackMessage] = field(default_factory=list)
    linear_issues: List[MockLinearIssue] = field(default_factory=list)
    team_key: str = "SD"  # Linear team key


class MockDataGenerator:
    """
    Generates realistic mock data for ScopeDocs.

    The generated data includes:
    - A realistic codebase with multiple files
    - PRs that reference Linear tickets
    - Slack discussions about features
    - Linear issues with feature requests

    Usage:
        generator = MockDataGenerator()
        data = generator.generate_scopedocs_data()

        # Access mock data
        for file in data.files:
            print(f"{file.path}: {len(file.content)} bytes")

        for pr in data.prs:
            print(f"PR #{pr.number}: {pr.title}")
    """

    def __init__(self, team_key: str = "SD"):
        self.team_key = team_key

    def generate_scopedocs_data(self) -> MockDataSet:
        """
        Generate mock data that represents the ScopeDocs project itself.

        This creates a realistic dataset that demonstrates all features:
        - Code files with documentation
        - PRs that implement features from tickets
        - Slack discussions about architecture
        - Linear issues for feature tracking
        """
        data = MockDataSet(team_key=self.team_key)

        # Generate Linear issues first (features we're "building")
        issues = self._generate_linear_issues()
        data.linear_issues = issues

        # Generate code files
        data.files = self._generate_code_files()

        # Generate PRs that reference the issues
        data.prs = self._generate_prs(issues, data.files)

        # Generate Slack messages discussing the work
        data.slack_messages = self._generate_slack_messages(issues, data.files)

        return data

    def _generate_linear_issues(self) -> List[MockLinearIssue]:
        """Generate realistic Linear issues for ScopeDocs."""
        issues = [
            MockLinearIssue(
                id=str(uuid.uuid4()),
                identifier=f"{self.team_key}-101",
                title="Set up OAuth integration for GitHub, Slack, Linear",
                description="""
## Objective
Implement OAuth2 flows for all three integrations.

## Requirements
- GitHub OAuth with repo access
- Slack OAuth with channels:read and chat:write
- Linear OAuth with read access

## Acceptance Criteria
- [ ] Users can connect GitHub from the UI
- [ ] Users can connect Slack from the UI
- [ ] Users can connect Linear from the UI
- [ ] Tokens are stored securely
                """,
                state="completed",
                assignee="alice",
            ),
            MockLinearIssue(
                id=str(uuid.uuid4()),
                identifier=f"{self.team_key}-102",
                title="Build code indexing pipeline with AST-aware chunking",
                description="""
## Objective
Index code repositories using semantic chunking.

## Requirements
- Use tree-sitter for AST parsing
- Chunk by function/class boundaries
- Store embeddings in pgvector

## Technical Notes
- Consider using Chonkie library for chunking
- Start with Python, expand to other languages later
                """,
                state="completed",
                assignee="bob",
            ),
            MockLinearIssue(
                id=str(uuid.uuid4()),
                identifier=f"{self.team_key}-103",
                title="Implement AI documentation generation",
                description="""
## Objective
Auto-generate documentation from code using LLMs.

## Requirements
- Generate file-level documentation
- Generate module overviews
- Create doc ↔ code links

## Open Questions
- Which LLM provider? Together.ai vs OpenAI?
- How to handle rate limits?
                """,
                state="in_progress",
                assignee="alice",
            ),
            MockLinearIssue(
                id=str(uuid.uuid4()),
                identifier=f"{self.team_key}-104",
                title="Add traceability between Linear tickets and code",
                description="""
## Objective
Track which code changes came from which tickets.

## Requirements
- Parse ticket IDs from PR titles/bodies
- Link PRs to Linear issues
- Show traceability in UI

## Dependencies
- Depends on {self.team_key}-102 (code indexing)
                """,
                state="backlog",
                assignee=None,
            ),
            MockLinearIssue(
                id=str(uuid.uuid4()),
                identifier=f"{self.team_key}-105",
                title="Create admin UI for testing integrations",
                description="""
## Objective
Simple UI to test OAuth and data sync.

## Requirements
- Connect/disconnect integrations
- Trigger data sync
- View sync results

## Notes
- Keep it simple, focus on functionality
- Can use vanilla JS for MVP
                """,
                state="completed",
                assignee="charlie",
            ),
        ]
        return issues

    def _generate_code_files(self) -> List[MockFile]:
        """Generate mock code files."""
        files = [
            MockFile(
                path="backend/server.py",
                content='''"""
ScopeDocs API Server
Main FastAPI application with OAuth and sync endpoints.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ScopeDocs API", version="1.0.0")

# Include routers
app.include_router(oauth_router)
app.include_router(sync_router)

@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {"name": "ScopeDocs", "version": "1.0.0"}

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
''',
            ),
            MockFile(
                path="backend/integrations/oauth/routes.py",
                content='''"""
OAuth routes for GitHub, Slack, and Linear.
Handles OAuth2 authorization code flow.
"""
from fastapi import APIRouter, HTTPException
from urllib.parse import urlencode

router = APIRouter(prefix="/api/oauth")

@router.get("/{provider}/connect")
async def connect(provider: str, workspace_id: str):
    """Start OAuth flow for a provider."""
    config = get_provider_config(provider)
    state = generate_state(workspace_id, provider)

    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return RedirectResponse(f"{config.authorize_url}?{urlencode(params)}")

@router.get("/{provider}/callback")
async def callback(provider: str, code: str, state: str):
    """Handle OAuth callback and exchange code for token."""
    state_data = validate_state(state)
    if not state_data:
        raise HTTPException(400, "Invalid state")

    token = await exchange_code_for_token(provider, code)
    await store_token(provider, state_data["workspace_id"], token)

    return RedirectResponse("/ui")
''',
            ),
            MockFile(
                path="backend/ai/client.py",
                content='''"""
Together.ai client for embeddings and generation.
Uses BAAI/bge-large-en-v1.5 for embeddings.
Uses Qwen/Qwen2.5-Coder-32B-Instruct for code tasks.
"""
import httpx
from typing import List

EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
CODE_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

class TogetherClient:
    """Async client for Together.ai API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.together.xyz/v1"

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": EMBEDDING_MODEL, "input": texts},
            )
            data = response.json()
            return [item["embedding"] for item in data["data"]]

    async def generate(self, prompt: str, system: str = None) -> str:
        """Generate text completion."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": CODE_MODEL, "messages": messages},
            )
            data = response.json()
            return data["choices"][0]["message"]["content"]
''',
            ),
            MockFile(
                path="backend/pipeline/orchestrator.py",
                content='''"""
Pipeline orchestrator for code ingestion.
Coordinates: Fetch → Chunk → Embed → Generate Docs → Link
"""
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class PipelineResult:
    """Result of a pipeline run."""
    success: bool
    files_processed: int
    chunks_created: int
    docs_generated: int
    errors: List[str]

class PipelineOrchestrator:
    """Orchestrates the full ingestion pipeline."""

    async def process_repository(
        self,
        workspace_id: str,
        repo_full_name: str,
    ) -> PipelineResult:
        """Process a repository through the full pipeline."""
        # 1. Fetch files from GitHub
        files = await self.fetch_files(repo_full_name)

        # 2. Chunk with AST-aware chunker
        chunks = []
        for file in files:
            file_chunks = await self.chunk_file(file)
            chunks.extend(file_chunks)

        # 3. Generate embeddings
        await self.embed_chunks(chunks)

        # 4. Generate documentation
        docs = await self.generate_docs(files)

        # 5. Create doc-code links
        await self.create_links(docs, chunks)

        return PipelineResult(
            success=True,
            files_processed=len(files),
            chunks_created=len(chunks),
            docs_generated=len(docs),
            errors=[],
        )
''',
            ),
            MockFile(
                path="code-indexing/src/indexing/chunker.py",
                content='''"""
AST-aware code chunking using tree-sitter.
Chunks code by semantic boundaries (functions, classes).
"""
from dataclasses import dataclass
import hashlib

@dataclass
class CodeChunk:
    """A semantic chunk of code."""
    content: str
    start_line: int
    end_line: int
    chunk_hash: str
    chunk_index: int

def chunk_code_file(content: str, file_path: str) -> List[CodeChunk]:
    """Chunk a file using AST-aware chunking."""
    from chonkie import CodeChunker

    chunker = CodeChunker(language="python", chunk_size=512)
    chonkie_chunks = chunker.chunk(content)

    result = []
    for idx, chunk in enumerate(chonkie_chunks):
        result.append(CodeChunk(
            content=chunk.text,
            start_line=get_start_line(content, chunk.text),
            end_line=get_end_line(content, chunk.text),
            chunk_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
            chunk_index=idx,
        ))

    return result
''',
            ),
        ]
        return files

    def _generate_prs(
        self,
        issues: List[MockLinearIssue],
        files: List[MockFile],
    ) -> List[MockPR]:
        """Generate PRs that reference the Linear issues."""
        prs = [
            MockPR(
                number=1,
                title=f"feat: Add OAuth integration ({self.team_key}-101)",
                body=f"""
## Summary
Implements OAuth2 flows for GitHub, Slack, and Linear.

## Changes
- Added OAuth routes in `backend/integrations/oauth/routes.py`
- Token storage in PostgreSQL
- Connect/disconnect functionality

## Ticket
Closes {self.team_key}-101

## Testing
- [x] GitHub OAuth flow
- [x] Slack OAuth flow
- [x] Linear OAuth flow
                """,
                files_changed=[
                    "backend/integrations/oauth/routes.py",
                    "backend/storage/postgres.py",
                    "backend/server.py",
                ],
                author="alice",
            ),
            MockPR(
                number=2,
                title=f"feat: Implement AST-aware code chunking ({self.team_key}-102)",
                body=f"""
## Summary
Add code indexing with tree-sitter based chunking.

## Changes
- New chunker using Chonkie library
- PostgreSQL storage for chunks
- Support for Python files (more languages coming)

## Related
Implements {self.team_key}-102

## Notes
Using Chonkie for tree-sitter integration as discussed in Slack.
                """,
                files_changed=[
                    "code-indexing/src/indexing/chunker.py",
                    "code-indexing/src/indexing/retrieval.py",
                ],
                author="bob",
            ),
            MockPR(
                number=3,
                title=f"feat: Add AI layer with Together.ai ({self.team_key}-103)",
                body=f"""
## Summary
Integrates Together.ai for embeddings and doc generation.

## Changes
- Together.ai client wrapper
- Embedding service with change detection
- Documentation generation using Qwen

## Ticket
Addresses {self.team_key}-103

## Decisions
- Using BGE-large for embeddings (1024 dims)
- Using Qwen 32B for code understanding
- Storing embeddings only, not raw code (SOC 2)
                """,
                files_changed=[
                    "backend/ai/client.py",
                    "backend/ai/embeddings.py",
                    "backend/ai/generation.py",
                    "backend/ai/routes.py",
                ],
                author="alice",
            ),
            MockPR(
                number=4,
                title=f"feat: Create admin testing UI ({self.team_key}-105)",
                body=f"""
## Summary
Simple admin UI for testing integrations.

## Changes
- Single HTML file with vanilla JS
- OAuth connect/disconnect buttons
- Data sync testing

## Ticket
Fixes {self.team_key}-105
                """,
                files_changed=[
                    "frontend/index.html",
                ],
                author="charlie",
            ),
        ]
        return prs

    def _generate_slack_messages(
        self,
        issues: List[MockLinearIssue],
        files: List[MockFile],
    ) -> List[MockSlackMessage]:
        """Generate realistic Slack messages."""
        base_time = datetime.utcnow() - timedelta(days=7)

        messages = [
            MockSlackMessage(
                id="1234567890.000001",
                channel="engineering",
                text=f"Hey team, starting work on {self.team_key}-101 (OAuth integration). "
                     f"Going to use the standard OAuth2 authorization code flow for all three providers.",
                user="alice",
                timestamp=(base_time + timedelta(hours=1)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000002",
                channel="engineering",
                text=f"Question about {self.team_key}-102: Should we use tree-sitter directly or "
                     f"go through a library like Chonkie? I found that Chonkie handles a lot of the "
                     f"tree-sitter setup for us.",
                user="bob",
                timestamp=(base_time + timedelta(hours=5)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000003",
                channel="engineering",
                text="@bob I'd go with Chonkie. Less setup and it has good defaults for code chunking. "
                     "We can always swap it out later if needed.",
                user="alice",
                timestamp=(base_time + timedelta(hours=6)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000004",
                channel="architecture",
                text=f"RFC for {self.team_key}-103: I'm proposing we use Together.ai for the AI layer. "
                     f"Reasons:\n"
                     f"1. Open source models (BGE, Qwen)\n"
                     f"2. Good pricing\n"
                     f"3. No vendor lock-in\n\n"
                     f"The main alternative is OpenAI but I want to stay open source.",
                user="alice",
                timestamp=(base_time + timedelta(days=1)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000005",
                channel="architecture",
                text="@alice +1 on Together.ai. Quick question - for SOC 2 compliance, are we storing "
                     "the actual code or just embeddings? I think embeddings-only is safer.",
                user="bob",
                timestamp=(base_time + timedelta(days=1, hours=2)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000006",
                channel="architecture",
                text="@bob Great point. Let's go with embeddings + pointers. We'll fetch code on-demand "
                     "from GitHub when users need to see it. This keeps us SOC 2 compliant and reduces "
                     "data liability. I'll update the design doc.",
                user="alice",
                timestamp=(base_time + timedelta(days=1, hours=3)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000007",
                channel="engineering",
                text=f"Just merged PR #1 for {self.team_key}-101. OAuth is working! "
                     f"Check out `backend/integrations/oauth/routes.py` for the implementation.",
                user="alice",
                timestamp=(base_time + timedelta(days=2)).isoformat(),
            ),
            MockSlackMessage(
                id="1234567890.000008",
                channel="engineering",
                text=f"The chunker is ready! PR #2 implements {self.team_key}-102. "
                     f"Using Chonkie as discussed. The code is in `code-indexing/src/indexing/chunker.py`.",
                user="bob",
                timestamp=(base_time + timedelta(days=3)).isoformat(),
            ),
        ]
        return messages

    def generate_simple_test_data(self) -> MockDataSet:
        """Generate minimal test data for quick testing."""
        data = MockDataSet(team_key=self.team_key)

        data.linear_issues = [
            MockLinearIssue(
                id=str(uuid.uuid4()),
                identifier=f"{self.team_key}-1",
                title="Test issue",
                description="A test issue for validation.",
                state="done",
            ),
        ]

        data.files = [
            MockFile(
                path="test.py",
                content='def hello():\n    """Say hello."""\n    print("Hello, world!")\n',
            ),
        ]

        data.prs = [
            MockPR(
                number=1,
                title=f"test: Add hello function ({self.team_key}-1)",
                body=f"Implements {self.team_key}-1",
                files_changed=["test.py"],
            ),
        ]

        data.slack_messages = [
            MockSlackMessage(
                id="test.1",
                channel="test",
                text=f"Working on {self.team_key}-1, updating test.py",
                user="tester",
                timestamp=datetime.utcnow().isoformat(),
            ),
        ]

        return data


def print_mock_data_summary(data: MockDataSet):
    """Print a summary of generated mock data."""
    print(f"\n{'='*60}")
    print("MOCK DATA SUMMARY")
    print(f"{'='*60}")
    print(f"\nLinear Team Key: {data.team_key}")
    print(f"\nLinear Issues ({len(data.linear_issues)}):")
    for issue in data.linear_issues:
        print(f"  - {issue.identifier}: {issue.title[:50]}...")

    print(f"\nCode Files ({len(data.files)}):")
    for file in data.files:
        print(f"  - {file.path} ({len(file.content)} bytes)")

    print(f"\nPull Requests ({len(data.prs)}):")
    for pr in data.prs:
        print(f"  - PR #{pr.number}: {pr.title[:50]}...")

    print(f"\nSlack Messages ({len(data.slack_messages)}):")
    for msg in data.slack_messages:
        print(f"  - #{msg.channel}: {msg.text[:50]}...")

    print(f"\n{'='*60}\n")
