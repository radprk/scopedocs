# ScopeDocs Architecture

ScopeDocs is a FastAPI-based backend for generating living documentation from code.[1]

## Overview

The system ingests code from GitHub repositories, chunks it into semantic units,
generates embeddings using Together.ai, and produces documentation that stays
linked to the source code.

## Data Flow

```
GitHub Repo → Fetch Files → Chunk Code → Generate Embeddings → Store in DB → Generate Docs
```

## Data Models

The system uses Pydantic models defined in `backend/models.py`.[2]

Key models include:
- **WorkItem**: Represents Linear issues with title, description, status, assignee
- **PullRequest**: Represents GitHub PRs with author, files changed, reviewers
- **Conversation**: Represents Slack threads with messages and participants

## Code Chunking

Code is chunked using AST-aware parsing in `code-indexing/src/indexing/chunker.py`.[3]

The chunker uses Chonkie with tree-sitter to:
1. Parse the code into an Abstract Syntax Tree (AST)
2. Split at function and class boundaries
3. Preserve semantic meaning (no mid-function splits)
4. Generate content hashes for change detection

Example chunk structure:[4]
- `content`: The actual code text
- `start_line`: 1-indexed starting line
- `end_line`: 1-indexed ending line
- `chunk_hash`: SHA256 of content
- `chunk_index`: Position in file

## Storage Layer

Data is stored in PostgreSQL with pgvector extension for embeddings.[5]

Key tables:
- `workspaces`: Multi-tenant isolation
- `oauth_tokens`: Integration credentials
- `code_chunks`: Chunk metadata and embeddings
- `generated_docs`: AI-generated documentation

## API Endpoints

Main endpoints are defined in `backend/server.py`:[6]

### Workspace Management
- `GET /api/workspaces` - List all workspaces
- `POST /api/workspaces` - Create new workspace

### OAuth Integration
- `GET /api/oauth/{provider}/connect` - Start OAuth flow
- `GET /api/oauth/{provider}/callback` - OAuth callback

### Code Indexing
- `POST /api/index/repo` - Index a GitHub repository
- `GET /api/index/chunks/{workspace_id}` - List indexed chunks
- `GET /api/index/chunk-content/{workspace_id}` - Fetch chunk content from GitHub

### AI Services
- `POST /api/ai/embed/code` - Generate embeddings for chunks
- `GET /api/ai/stats/{workspace_id}` - Embedding statistics
- `GET /api/ai/health` - Check AI service status

## Security

The system follows SOC 2 principles:[7]
- **No code stored**: Only embeddings and metadata are persisted
- **On-demand fetch**: Actual code is fetched from GitHub when needed
- **Workspace isolation**: Each workspace has separate data
- **OAuth tokens encrypted**: Credentials stored securely

## Configuration

Required environment variables:
- `DATABASE_URL`: PostgreSQL connection string
- `TOGETHER_API_KEY`: Together.ai API key for embeddings
- `GITHUB_CLIENT_ID`: GitHub OAuth app client ID
- `GITHUB_CLIENT_SECRET`: GitHub OAuth app client secret

## Getting Started

1. Set up PostgreSQL with pgvector extension
2. Run schema: `psql -d scopedocs -f db/schema.sql`
3. Set environment variables
4. Start server: `python -m uvicorn backend.server:app --reload`
5. Open http://localhost:8000/ui to connect GitHub
6. Open http://localhost:8000/pipeline.html to test the pipeline
