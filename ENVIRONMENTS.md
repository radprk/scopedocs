# ScopeDocs Environments & Testing Guide

## 🗂️ Codebase Structure

```
scopedocs/
├── backend/                    # INTEGRATIONS (Slack, GitHub, Linear)
│   ├── venv/                   # ❌ Don't use this one
│   └── ...
├── code-indexing/              # CODE INDEXING (AST, chunking, embeddings)
│   └── venv/                   # ✅ Use for indexing tests
├── venv/                       # ✅ Use for main app (OAuth, API)
└── .env files                  # See below
```

## 🔑 Environment Files

| File | Purpose |
|------|---------|
| `backend/.env` | OAuth secrets, DB connection, API tokens |
| `code-indexing/.env` | (Create if needed) Embedding API keys |

## 🧪 Testing Each Component

### 1. Backend Integrations (OAuth, Sync)

```bash
# Activate main venv
cd /Users/radprk/scopedocs
source venv/bin/activate

# Start server
uvicorn app.main:app --reload --port 8000

# Test endpoints:
# - http://localhost:8000/docs (Swagger UI)
# - http://localhost:8000/oauth/github/authorize
# - http://localhost:8000/oauth/slack/authorize
# - http://localhost:8000/oauth/linear/authorize
```

### 2. Code Indexing (AST, Chunking, Embeddings)

```bash
# Activate code-indexing venv
cd /Users/radprk/scopedocs/code-indexing
source venv/bin/activate

# Run the test script (see below)
python scripts/verify_pipeline.py
```

## 📋 What Each Part Does

### Backend Flow
```
User → OAuth → Access Token → Sync API → 
Fetch from Slack/GitHub/Linear → Store in Supabase
```

### Code Indexing Flow
```
Python File → tree-sitter AST → Chunker → 
Embedding Model → pgvector (code_chunks table)
```

## 🔍 Key Tables in Supabase

| Table | Purpose |
|-------|---------|
| `user_integrations` | OAuth tokens per user |
| `conversations` | Slack messages |
| `pull_requests` | GitHub PRs |
| `work_items` | Linear issues |
| `code_chunks` | Embeddings + metadata (pgvector) |
| `file_path_lookup` | Hash → real file path mapping |
