# Storage Architecture

How ScopeDocs stores data in PostgreSQL with pgvector.

## Location

- Schema: `db/schema.sql`
- Access layer: `backend/storage/postgres.py`

## Design Principles

1. **No code storage**: Only embeddings and pointers (SOC 2 compliant)
2. **Multi-tenant**: All tables have `workspace_id` for isolation
3. **Change detection**: Content hashes prevent duplicate work
4. **Vector search**: pgvector enables similarity queries

---

## Schema Overview

```sql
┌─────────────────────────────────────────────────────────────────┐
│                         DATABASE SCHEMA                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │ workspaces  │────▶│oauth_tokens │     │code_chunks  │       │
│  │             │     │             │     │             │       │
│  │ id          │     │ workspace_id│     │ workspace_id│       │
│  │ name        │     │ provider    │     │ file_path   │       │
│  │ created_at  │     │ access_token│     │ start_line  │       │
│  └─────────────┘     └─────────────┘     │ chunk_hash  │       │
│         │                                 └──────┬──────┘       │
│         │                                        │              │
│         │            ┌─────────────┐     ┌──────▼──────┐       │
│         └───────────▶│generated_docs│     │code_embeddings│    │
│                      │             │     │             │       │
│                      │ workspace_id│     │ chunk_id    │       │
│                      │ content     │     │ embedding   │       │
│                      │ doc_type    │     │ (vector)    │       │
│                      └─────────────┘     └─────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Tables

### workspaces

Multi-tenant isolation. Every customer gets their own workspace.

```sql
CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,           -- 'ws_abc123'
    name TEXT NOT NULL,            -- 'Acme Corp'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### oauth_tokens

Store OAuth tokens per provider per workspace.

```sql
CREATE TABLE oauth_tokens (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id),
    provider TEXT NOT NULL,        -- 'github', 'slack', 'linear'
    access_token TEXT NOT NULL,    -- Encrypted in production
    refresh_token TEXT,
    expires_at TIMESTAMPTZ,
    UNIQUE(workspace_id, provider)
);
```

### code_chunks

**Pointers** to code, not the code itself.

```sql
CREATE TABLE code_chunks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id),
    repo_full_name TEXT NOT NULL,  -- 'owner/repo'
    commit_sha TEXT NOT NULL,      -- For version tracking
    file_path TEXT NOT NULL,       -- 'backend/server.py'
    start_line INTEGER NOT NULL,   -- 1
    end_line INTEGER NOT NULL,     -- 25
    chunk_hash TEXT NOT NULL,      -- SHA256 of content
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups
CREATE INDEX idx_chunks_workspace ON code_chunks(workspace_id);
CREATE INDEX idx_chunks_hash ON code_chunks(chunk_hash);
```

### code_embeddings

Vector embeddings for similarity search.

```sql
CREATE TABLE code_embeddings (
    id TEXT PRIMARY KEY,
    chunk_id TEXT REFERENCES code_chunks(id),
    embedding vector(1024),        -- Together.ai BGE: 1024 dimensions
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for vector similarity search
CREATE INDEX idx_embeddings_vector ON code_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

### generated_docs

AI-generated documentation output.

```sql
CREATE TABLE generated_docs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id),
    doc_type TEXT NOT NULL,        -- 'overview', 'api', 'tutorial'
    title TEXT NOT NULL,
    content TEXT NOT NULL,         -- Markdown with [n] references
    references JSONB,              -- {"[1]": {file_path, start_line, ...}}
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## pgvector Operations

### Store Embedding

```python
# In backend/storage/postgres.py
async def store_embedding(chunk_id: str, embedding: List[float]):
    await pool.execute("""
        INSERT INTO code_embeddings (id, chunk_id, embedding)
        VALUES ($1, $2, $3::vector(1024))
    """, generate_id(), chunk_id, embedding)
```

### Similarity Search

```python
async def find_similar(query_embedding: List[float], limit: int = 10):
    return await pool.fetch("""
        SELECT
            c.file_path,
            c.start_line,
            c.end_line,
            1 - (e.embedding <=> $1::vector(1024)) AS similarity
        FROM code_embeddings e
        JOIN code_chunks c ON e.chunk_id = c.id
        ORDER BY e.embedding <=> $1::vector(1024)
        LIMIT $2
    """, query_embedding, limit)
```

The `<=>` operator is cosine distance. `1 - distance = similarity`.

---

## Access Layer

### backend/storage/postgres.py

```python
# Connection pool
async def get_pool():
    return await asyncpg.create_pool(DATABASE_URL)

# Workspace operations
async def create_workspace(name: str) -> str
async def get_workspace(workspace_id: str) -> dict
async def list_workspaces() -> List[dict]

# Chunk operations
async def store_chunk(chunk: CodeChunk) -> str
async def get_chunk_by_hash(chunk_hash: str) -> Optional[dict]
async def list_chunks(workspace_id: str) -> List[dict]

# Embedding operations
async def store_embedding(chunk_id: str, embedding: List[float])
async def find_similar(embedding: List[float], limit: int) -> List[dict]
```

---

## Multi-Tenancy

Every query filters by `workspace_id`:

```python
# Good: Always filter by workspace
await pool.fetch("""
    SELECT * FROM code_chunks
    WHERE workspace_id = $1
""", workspace_id)

# Bad: Data leak risk!
await pool.fetch("SELECT * FROM code_chunks")
```

---

## Debug Tips

Add prints to trace database operations:

```python
async def store_chunk(chunk: CodeChunk) -> str:
    print(f"[DB] Storing chunk: {chunk.file_path}:{chunk.start_line}-{chunk.end_line}")
    chunk_id = generate_id()
    await pool.execute(...)
    print(f"[DB] Stored as: {chunk_id}")
    return chunk_id
```

Query to inspect stored data:

```sql
-- See all chunks for a workspace
SELECT file_path, start_line, end_line, chunk_hash
FROM code_chunks
WHERE workspace_id = 'your-workspace-id'
ORDER BY file_path, start_line;

-- Check embedding count
SELECT COUNT(*) FROM code_embeddings;
```

---

## Related Files

- `db/schema.sql` - Full schema definition
- `backend/ai/embeddings.py` - Stores embeddings after generation
- `backend/server.py` - API endpoints that trigger storage
