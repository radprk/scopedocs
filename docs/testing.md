# Testing Guide

How to test ScopeDocs and verify each component works.

## Quick Verification

### 1. Database Connection

```bash
# Check PostgreSQL is running
psql -d scopedocs -c "SELECT 1"

# Verify pgvector
psql -d scopedocs -c "SELECT * FROM pg_extension WHERE extname = 'vector'"

# Check tables exist
psql -d scopedocs -c "\dt"
```

Expected: All tables from `db/schema.sql` should appear.

---

### 2. Server Health

```bash
# Start server
python -m uvicorn backend.server:app --reload

# Test health endpoint
curl http://localhost:8000/health
```

Expected: `{"status": "healthy"}`

---

### 3. OAuth Flow

1. Open http://localhost:8000/ui
2. Click "Connect GitHub"
3. Authorize the OAuth app
4. You should be redirected back with "Connected!"

Verify token stored:

```sql
SELECT provider, created_at FROM oauth_tokens;
```

---

### 4. Code Indexing

```bash
# Index a repository (replace with your workspace/repo)
curl -X POST http://localhost:8000/api/index/repo \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "test-workspace",
    "repo_full_name": "your-username/your-repo"
  }'
```

Expected response:
```json
{
  "files_processed": 15,
  "chunks_created": 47,
  "skipped_unchanged": 0
}
```

Verify chunks stored:

```sql
SELECT file_path, start_line, end_line
FROM code_chunks
WHERE workspace_id = 'test-workspace'
LIMIT 10;
```

---

### 5. Embedding Generation

```bash
# Generate embeddings for indexed chunks
curl -X POST http://localhost:8000/api/ai/embed/code \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "test-workspace",
    "repo_full_name": "your-username/your-repo"
  }'
```

Expected response:
```json
{
  "total": 47,
  "new_chunks": 47,
  "skipped": 0
}
```

Verify embeddings stored:

```sql
SELECT COUNT(*) FROM code_embeddings;
```

---

## Pipeline UI Testing

1. Open http://localhost:8000/pipeline.html
2. Enter workspace ID and repository name
3. Click "Run Indexing" → Watch log output
4. Click "Generate Embeddings" → Watch log output
5. Click "Load Sample Doc" → View generated documentation
6. Click a `[n]` reference → View source code

---

## Component Tests

### Test Chunker

```python
# test_chunker.py
from code_indexing.src.indexing.chunker import chunk_code_file

def test_chunker_basic():
    code = """
def hello():
    print("Hello")

def goodbye():
    print("Goodbye")
"""

    chunks = chunk_code_file(code, "test.py")

    assert len(chunks) >= 2
    assert all(c.start_line > 0 for c in chunks)
    assert all(c.chunk_hash for c in chunks)
    print(f"✓ Created {len(chunks)} chunks")

if __name__ == "__main__":
    test_chunker_basic()
```

Run:
```bash
python test_chunker.py
```

---

### Test Embeddings

```python
# test_embeddings.py
import asyncio
from backend.ai.client import TogetherClient

async def test_embeddings():
    client = TogetherClient()

    texts = ["def hello(): print('hi')", "class User: pass"]
    embeddings = await client.embed(texts)

    assert len(embeddings) == 2
    assert len(embeddings[0]) == 1024  # BGE-large dimensions
    print(f"✓ Generated {len(embeddings)} embeddings of dim {len(embeddings[0])}")

if __name__ == "__main__":
    asyncio.run(test_embeddings())
```

Run:
```bash
TOGETHER_API_KEY=your-key python test_embeddings.py
```

---

### Test Database Storage

```python
# test_storage.py
import asyncio
from backend.storage.postgres import get_pool, create_workspace, list_workspaces

async def test_storage():
    pool = await get_pool()

    # Create workspace
    ws_id = await create_workspace("Test Workspace")
    print(f"✓ Created workspace: {ws_id}")

    # List workspaces
    workspaces = await list_workspaces()
    assert any(w["id"] == ws_id for w in workspaces)
    print(f"✓ Listed {len(workspaces)} workspaces")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(test_storage())
```

---

## Debug Checklist

When something doesn't work:

### 1. Check Environment Variables

```bash
echo $DATABASE_URL
echo $TOGETHER_API_KEY
echo $GITHUB_CLIENT_ID
```

### 2. Check Server Logs

Look for `[FETCH]`, `[CHUNK]`, `[EMBED]` prefixes:

```
[FETCH] Starting: owner/repo
[FETCH] Got 25 files
[CHUNK] Processing: backend/server.py
[CHUNK] Created 8 chunks
[EMBED] Processing 8 chunks
[EMBED] New: 8, Skipped: 0
```

### 3. Check Database State

```sql
-- How many workspaces?
SELECT COUNT(*) FROM workspaces;

-- How many chunks per repo?
SELECT repo_full_name, COUNT(*)
FROM code_chunks
GROUP BY repo_full_name;

-- How many embeddings?
SELECT COUNT(*) FROM code_embeddings;

-- Any chunks without embeddings?
SELECT c.id, c.file_path
FROM code_chunks c
LEFT JOIN code_embeddings e ON c.id = e.chunk_id
WHERE e.id IS NULL;
```

### 4. Check API Responses

```bash
# Test with verbose output
curl -v http://localhost:8000/api/index/repo ...
```

---

## Running All Tests

```bash
# Run with pytest (if configured)
pytest tests/

# Or run individual test files
python test_chunker.py
python test_embeddings.py
python test_storage.py
```

---

## Dogfooding: Test with ScopeDocs Itself

The best test: index the ScopeDocs codebase!

```bash
# 1. Create a workspace
curl -X POST http://localhost:8000/api/workspaces \
  -H "Content-Type: application/json" \
  -d '{"name": "ScopeDocs Dogfood"}'

# 2. Index the repo (after connecting GitHub)
curl -X POST http://localhost:8000/api/index/repo \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "your-workspace-id",
    "repo_full_name": "your-username/scopedocs"
  }'

# 3. Generate embeddings
curl -X POST http://localhost:8000/api/ai/embed/code \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "your-workspace-id",
    "repo_full_name": "your-username/scopedocs"
  }'

# 4. Check stats
curl http://localhost:8000/api/ai/stats/your-workspace-id
```

This tests the entire pipeline end-to-end with real code!
