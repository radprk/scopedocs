# ScopeDocs

**Living Documentation for Engineering Teams**

ScopeDocs automatically generates and maintains documentation from your codebase, keeping it always up-to-date with your actual code.

## What This System Does

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   GitHub    │ → │   Chunker   │ → │  Embeddings │ → │    Docs     │
│    Repo     │    │  (AST-aware)│    │ (Together.ai)│   │  (Markdown) │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **Fetch**: Pull code files from GitHub repositories
2. **Chunk**: Split code into semantic units (functions, classes) using AST
3. **Embed**: Generate vector embeddings for semantic search
4. **Link**: Connect documentation to source code with clickable references

## Key Features (MVP)

- **GitHub OAuth**: Connect repositories securely
- **AST-Aware Chunking**: Smart code splitting that preserves meaning
- **Vector Embeddings**: Using Together.ai's BGE model (1024 dimensions)
- **Code References**: Documentation links directly to source lines
- **No Code Storage**: Only embeddings and metadata stored (SOC 2 friendly)

## Quick Start

```bash
# 1. Set up the database
psql -d scopedocs -f db/schema.sql

# 2. Set environment variables
export DATABASE_URL="postgresql://localhost:5432/scopedocs"
export TOGETHER_API_KEY="your-key-here"
export GITHUB_CLIENT_ID="your-github-app-id"
export GITHUB_CLIENT_SECRET="your-github-secret"

# 3. Start the server
python -m uvicorn backend.server:app --reload

# 4. Open the UI
# http://localhost:8000/ui - Connect GitHub
# http://localhost:8000/pipeline.html - Test pipeline
```

## Project Structure

```
scopedocs/
├── backend/
│   ├── server.py          # FastAPI application
│   ├── models.py          # Pydantic data models
│   ├── storage/           # Database operations
│   ├── ai/                # Embeddings (Together.ai)
│   └── integrations/      # OAuth (GitHub, Slack, Linear)
├── code-indexing/
│   └── src/indexing/
│       └── chunker.py     # AST-aware code chunking
├── db/
│   └── schema.sql         # PostgreSQL schema
├── frontend/
│   ├── index.html         # Integration tester UI
│   └── pipeline.html      # Pipeline viewer UI
└── output/
    ├── sample_doc.md      # Example generated docs
    └── references.json    # Code reference mappings
```

## Next Steps

1. Read the [Learning Path](learning-path.md) to understand the codebase
2. Follow the [Setup Guide](setup.md) to run locally
3. Understand the [Data Flow](data-flow.md) through the system
4. Dive into [Architecture](architecture/chunker.md) for component details
