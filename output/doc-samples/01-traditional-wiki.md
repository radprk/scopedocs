# ScopeDocs - Traditional Wiki Documentation

> **Style:** Traditional Reference Wiki
> **Best for:** Complete reference, looking things up

---

## Overview

ScopeDocs is a multi-tenant, AI-powered documentation generation platform that transforms codebases into adaptive, audience-specific documentation. It integrates with GitHub, Slack, and Linear to provide comprehensive context for documentation generation.

## Architecture

### Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python 3.11+) |
| Database | PostgreSQL + pgvector (Supabase) |
| AI/ML | Together.ai (BGE-large embeddings, Llama 3.3) |
| Code Analysis | tree-sitter, Chonkie |
| Frontend | Vanilla HTML/CSS/JS |

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      ScopeDocs Platform                      │
├─────────────────────────────────────────────────────────────┤
│  Frontend (index.html, docs.html, pipeline.html)            │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Backend                                            │
│  ├── OAuth Routes (/api/oauth/*)                            │
│  ├── Sync Routes (/api/sync/*)                              │
│  ├── AI Routes (/api/ai/*)                                  │
│  └── Indexing Routes (/api/index/*)                         │
├─────────────────────────────────────────────────────────────┤
│  Services Layer                                             │
│  ├── EmbeddingService (ai/embeddings.py)                    │
│  ├── RAGSearchService (ai/search.py)                        │
│  └── TogetherClient (ai/client.py)                          │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL + pgvector                                      │
│  (workspaces, oauth_tokens, code_embeddings, generated_docs)│
└─────────────────────────────────────────────────────────────┘
```

## API Reference

### Authentication

All API endpoints require workspace context. OAuth tokens are stored per-workspace.

#### OAuth Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/oauth/{provider}/connect` | GET | Initiate OAuth flow |
| `/api/oauth/{provider}/callback` | GET | OAuth callback handler |
| `/api/oauth/status/{workspace_id}` | GET | Check connection status |
| `/api/oauth/{provider}/disconnect` | DELETE | Remove integration |

**Providers:** `github`, `slack`, `linear`

### AI Endpoints

#### Generate Adaptive Documentation

```http
POST /api/ai/generate-adaptive-doc
Content-Type: application/json

{
  "workspace_id": "uuid",
  "repo_full_name": "owner/repo",
  "audience_type": "new_engineer",
  "style": "narrative",
  "purpose": "understand the whole system"
}
```

**Response:**
```json
{
  "title": "Welcome to owner/repo",
  "content": "# Welcome...",
  "audience_type": "new_engineer",
  "style": "narrative",
  "references": {"[1]": {"file_path": "...", "start_line": 1}},
  "suggested_next": ["Deep dive: server.py"],
  "token_estimate": 1500
}
```

#### Audience Types

| Type | Description |
|------|-------------|
| `traditional` | Classic wiki-style reference documentation |
| `new_engineer` | Top-down onboarding view with conceptual explanations |
| `oncall` | Quick, actionable incident response documentation |
| `custom` | Documentation tailored to user-provided context |

#### Documentation Styles

| Style | Description |
|-------|-------------|
| `concise` | Bullet points, scannable, minimal prose |
| `narrative` | Story-like flow, explains the "why" |
| `reference` | Exhaustive API documentation |
| `tutorial` | Step-by-step with examples |

### Indexing Endpoints

#### Index Repository

```http
POST /api/index/repo
Content-Type: application/json

{
  "workspace_id": "uuid",
  "repo_full_name": "owner/repo",
  "branch": "main"
}
```

#### Generate Embeddings

```http
POST /api/index/embed
Content-Type: application/json

{
  "workspace_id": "uuid",
  "repo_full_name": "owner/repo"
}
```

## Database Schema

### Core Tables

#### workspaces
```sql
CREATE TABLE workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

#### code_embeddings
```sql
CREATE TABLE code_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id),
  repo_full_name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  content_hash TEXT,
  embedding vector(1024),
  language TEXT,
  UNIQUE(workspace_id, repo_full_name, file_path, chunk_index)
);
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `TOGETHER_API_KEY` | For AI | Together.ai API key |
| `GITHUB_CLIENT_ID` | For GitHub | GitHub OAuth app client ID |
| `GITHUB_CLIENT_SECRET` | For GitHub | GitHub OAuth app secret |
| `SLACK_CLIENT_ID` | For Slack | Slack app client ID |
| `SLACK_CLIENT_SECRET` | For Slack | Slack app secret |
| `LINEAR_CLIENT_ID` | For Linear | Linear OAuth client ID |
| `LINEAR_CLIENT_SECRET` | For Linear | Linear OAuth secret |

### Running the Server

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

## File Structure

```
scopedocs/
├── backend/
│   ├── server.py              # Main FastAPI app
│   ├── models.py              # Pydantic models
│   ├── ai/
│   │   ├── client.py          # Together.ai client
│   │   ├── embeddings.py      # Embedding service
│   │   ├── search.py          # RAG search
│   │   ├── routes.py          # AI endpoints
│   │   └── prompts.py         # Audience-adaptive prompts
│   ├── integrations/
│   │   └── oauth/             # OAuth handlers
│   └── storage/
│       └── postgres.py        # Database layer
├── frontend/
│   ├── index.html             # Integration dashboard
│   ├── docs.html              # Documentation generator
│   └── pipeline.html          # Pipeline visualization
└── db/
    └── schema.sql             # Database schema
```

---
*Generated with Traditional Wiki style*
