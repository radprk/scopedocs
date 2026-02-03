# Code Indexing ETL Pipeline

A security-first code indexing pipeline for ScopeDocs that enables semantic search over customer codebases without storing raw code.

## Overview

This pipeline indexes code repositories into Supabase (PostgreSQL + pgvector) for semantic search. Unlike traditional code search that stores raw code, this system:

- **Stores only embeddings and metadata** - Raw code is never persisted
- **Uses AST-aware chunking** - Splits code at semantic boundaries (functions, classes)
- **Detects changes efficiently** - Content hashing minimizes re-indexing

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARCHITECTURE                                    │
└─────────────────────────────────────────────────────────────────────────────┘

    INDEXING TIME                              QUERY TIME
    ─────────────                              ──────────

    ┌──────────────┐                           ┌──────────────┐
    │  Repository  │                           │    Query     │
    └──────┬───────┘                           └──────┬───────┘
           │                                          │
           ▼                                          ▼
    ┌──────────────┐                           ┌──────────────┐
    │   Chunker    │                           │ Vector Search│
    │  (AST-aware) │                           │  (pgvector)  │
    └──────┬───────┘                           └──────┬───────┘
           │                                          │
           ▼                                          ▼
    ┌──────────────┐                           ┌──────────────┐
    │  Embeddings  │                           │  Retrieval   │
    │  (mock/real) │                           │  (on-demand) │
    └──────┬───────┘                           └──────┬───────┘
           │                                          │
           ▼                                          ▼
    ┌──────────────────────────────────────────────────────────┐
    │                      Supabase                             │
    │  ┌────────────────┐        ┌────────────────┐            │
    │  │  code_chunks   │        │ file_path_lookup│            │
    │  │  - embeddings  │◄──────►│  - hash → path  │            │
    │  │  - line nums   │        │  - content hash │            │
    │  │  - chunk hash  │        └────────────────┘            │
    │  └────────────────┘                                      │
    │         ⚠️ NO RAW CODE STORED                             │
    └──────────────────────────────────────────────────────────┘
```

## Security Model

| Data | Stored? | Why |
|------|---------|-----|
| Raw code | ❌ No | Fetched on-demand from GitHub |
| Embeddings | ✅ Yes | Required for search, not reversible |
| File paths | ✅ Yes | Needed for retrieval (isolated table) |
| Path hashes | ✅ Yes | Links chunks to files |
| Line numbers | ✅ Yes | Know which lines to fetch |

**Key principle**: A database breach doesn't expose customer source code.

## Quick Start

```bash
# 1. Create and activate virtual environment
cd code-indexing
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify tree-sitter setup
python scripts/setup_tree_sitter.py

# 4. Generate test data
python scripts/gen_dummy_repo.py

# 5. Set up environment
cp .env.example .env
# Edit .env with your Supabase credentials

# 6. Run the database migration
# (Use Supabase dashboard or CLI to run supabase/migrations/001_code_chunks.sql)

# 7. Index a codebase
python scripts/sync_codebase.py \
    --repo-path ./dummy_repo \
    --repo-id 550e8400-e29b-41d4-a716-446655440000

# 8. Run tests
pytest tests/ -v
```

## Project Structure

```
code-indexing/
├── README.md                      # This file
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment template
├── .gitignore
│
├── src/
│   └── indexing/
│       ├── __init__.py
│       ├── chunker.py             # AST-aware code chunking
│       └── retrieval.py           # On-demand code fetching
│
├── scripts/
│   ├── gen_dummy_repo.py          # Generate test data
│   ├── sync_codebase.py           # Main ETL script
│   └── setup_tree_sitter.py       # Verify tree-sitter setup
│
├── tests/
│   ├── conftest.py                # Pytest fixtures
│   └── test_indexing_pipeline.py  # Test suite
│
├── supabase/
│   └── migrations/
│       └── 001_code_chunks.sql    # Database schema
│
└── dummy_repo/                    # Generated test files (gitignored)
```

## Scripts

### `gen_dummy_repo.py`

Generates realistic Python files for testing:

```bash
python scripts/gen_dummy_repo.py [--output-dir ./dummy_repo]
```

Creates 5 Python files (~500 lines total) with:
- Functions with docstrings
- Classes with methods
- Imports and realistic logic

### `sync_codebase.py`

Main ETL script for indexing:

```bash
python scripts/sync_codebase.py --repo-path <path> --repo-id <uuid>
```

Features:
- **Change detection**: Only re-indexes modified files
- **Graceful errors**: Continues on individual file failures
- **Progress reporting**: Shows files processed
- **Summary**: Reports new/modified/deleted/unchanged counts

### `setup_tree_sitter.py`

Verifies tree-sitter installation:

```bash
python scripts/setup_tree_sitter.py
```

Run this if you encounter chunking errors.

## API Reference

### Chunker

```python
from indexing.chunker import chunk_code_file, CodeChunk

chunks: list[CodeChunk] = chunk_code_file(
    file_content="def hello(): pass",
    file_path="example.py",
    max_tokens=512  # optional
)

# CodeChunk fields:
# - content: str        # The code text
# - start_line: int     # 1-indexed
# - end_line: int       # 1-indexed
# - chunk_hash: str     # SHA256
# - chunk_index: int    # Position in file
```

### Retrieval

```python
from indexing.retrieval import retrieve_chunk_content, RetrievedChunk

chunk: RetrievedChunk = await retrieve_chunk_content(
    repo_id="uuid",
    file_path_hash="sha256...",
    start_line=10,
    end_line=25,
    supabase_client=client,
    repo_base_path="./repo"  # For local retrieval
)

# RetrievedChunk fields:
# - file_path: str          # Actual path
# - content: str            # Code for lines
# - start_line: int
# - end_line: int
# - retrieval_source: str   # "local" or "github"
```

## Database Schema

### `code_chunks`

Stores embeddings and chunk metadata:

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| repo_id | UUID | Repository reference |
| file_path_hash | TEXT | SHA256 of file path |
| chunk_hash | TEXT | SHA256 of chunk content |
| chunk_index | INTEGER | Position in file (0-indexed) |
| start_line | INTEGER | Starting line (1-indexed) |
| end_line | INTEGER | Ending line (1-indexed) |
| embedding | vector(768) | Embedding vector |

### `file_path_lookup`

Maps hashes to actual paths (kept separate for security):

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| repo_id | UUID | Repository reference |
| file_path_hash | TEXT | SHA256 of file path |
| file_path | TEXT | Actual file path |
| file_content_hash | TEXT | SHA256 of file content |

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test class
pytest tests/test_indexing_pipeline.py::TestChunkerBasic -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Configuration

Environment variables (`.env`):

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-or-service-key
```

## Future Work

- [ ] Real embeddings via OpenAI/Cohere API
- [ ] GitHub API retrieval (replace local filesystem)
- [ ] Incremental embedding updates
- [ ] HNSW index for production vector search
- [ ] Multi-language support (JS, TS, Go, Rust)
- [ ] Webhook-triggered re-indexing

## Notes

- **Embeddings are mocked** (random floats) - real embedding API integration TBD
- **Local retrieval only** - GitHub API retrieval is stubbed
- **Python only** - tree-sitter supports other languages, but chunker is Python-focused for MVP
