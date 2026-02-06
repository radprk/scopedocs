# Learning Path

Read files in this order to understand ScopeDocs from the ground up.

## Level 1: Core Concepts (30 min)

### 1. Database Schema
**File**: `db/schema.sql`

Start here to understand what data we store. Key tables:

- `workspaces` - Multi-tenant isolation
- `code_chunks` - Indexed code with embeddings
- `generated_docs` - AI-generated documentation

```sql
-- Look for these key patterns:
CREATE TABLE code_chunks (
    embedding vector(1024),  -- Together.ai embeddings
    chunk_hash TEXT,         -- For change detection
    start_line INTEGER,      -- Code location (not content)
);
```

**Key insight**: We store *pointers* to code, not the code itself.

---

### 2. Data Models
**File**: `backend/models.py`

Understand the Pydantic models that define our data shapes:

```python
# Find these classes:
class WorkItem     # Linear issues
class PullRequest  # GitHub PRs
class Conversation # Slack threads
```

**Key insight**: These models mirror our database tables.

---

### 3. Code Chunker
**File**: `code-indexing/src/indexing/chunker.py`

The heart of the system. Understand:

```python
# Find the CodeChunk dataclass (lines 19-46):
@dataclass
class CodeChunk:
    content: str      # The actual code text
    start_line: int   # Where it starts
    end_line: int     # Where it ends
    chunk_hash: str   # SHA256 for change detection

# Find chunk_code_file function (lines 104-186):
def chunk_code_file(file_content, file_path, max_tokens=512):
    # Uses Chonkie + tree-sitter for AST-aware chunking
```

**Key insight**: Chunks split at function/class boundaries, not arbitrary lines.

---

## Level 2: Data Flow (45 min)

### 4. Server Entry Point
**File**: `backend/server.py`

The FastAPI application. Find these endpoints:

```python
# OAuth flow:
/api/oauth/{provider}/connect  # Start OAuth
/api/oauth/{provider}/callback # OAuth callback

# Indexing:
/api/index/repo                # Index a repository
/api/index/chunks/{workspace}  # View indexed chunks

# AI:
/api/ai/embed/code            # Generate embeddings
/api/ai/stats/{workspace}     # View stats
```

**Debug tip**: Add `print()` statements here to see requests flow.

---

### 5. Storage Layer
**File**: `backend/storage/postgres.py`

How we talk to PostgreSQL:

```python
# Find these functions:
async def get_pool()          # Connection pool
async def create_workspace()  # Create new workspace
async def list_workspaces()   # List all workspaces
```

**Debug tip**: Add prints before/after SQL queries.

---

### 6. OAuth Integration
**File**: `backend/integrations/oauth/routes.py`

How GitHub/Slack/Linear OAuth works:

```python
# Find the connect and callback routes:
@router.get("/{provider}/connect")
@router.get("/{provider}/callback")
```

**Key insight**: Tokens stored per-workspace in `oauth_tokens` table.

---

## Level 3: AI Layer (30 min)

### 7. Together.ai Client
**File**: `backend/ai/client.py`

How we call the embedding API:

```python
# Find these constants:
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"  # 1024 dimensions
EMBEDDING_DIMS = 1024

# Find the embed method:
async def embed(self, texts: List[str]) -> EmbeddingResult
```

**Debug tip**: Print the first 10 dimensions of embeddings.

---

### 8. Embedding Service
**File**: `backend/ai/embeddings.py`

How embeddings are generated and stored:

```python
# Find embed_code_chunks method:
async def embed_code_chunks(
    workspace_id, repo_full_name, commit_sha, chunks
) -> Dict
```

**Key insight**: Uses content hashing to skip unchanged chunks.

---

## Level 4: Frontend (15 min)

### 9. Pipeline Viewer
**File**: `frontend/pipeline.html`

Simple UI to test the pipeline:

```javascript
// Find these functions:
runIndexing()        // Step 1: Index repo
generateEmbeddings() // Step 2: Create embeddings
loadSampleDoc()      // Step 3: View docs
loadReference()      // Click [n] to view code
```

**Try it**: Open http://localhost:8000/pipeline.html

---

## Reading Order Summary

```
1. db/schema.sql           ← Data structure
2. backend/models.py       ← Type definitions
3. chunker.py              ← Core algorithm
4. backend/server.py       ← API endpoints
5. storage/postgres.py     ← Database access
6. oauth/routes.py         ← Authentication
7. ai/client.py            ← External API
8. ai/embeddings.py        ← Embedding logic
9. frontend/pipeline.html  ← Test UI
```

## Adding Debug Prints

Best places to add `print()` for learning:

```python
# In server.py endpoints:
@app.post("/api/index/repo")
async def api_index_repo(data: dict):
    print(f"[INDEX] Request: {data}")
    # ... rest of function
    print(f"[INDEX] Result: {stats}")

# In chunker.py:
def chunk_code_file(file_content, file_path, max_tokens=512):
    print(f"[CHUNK] Processing: {file_path}")
    # ... rest of function
    print(f"[CHUNK] Created {len(result)} chunks")

# In embeddings.py:
async def embed_code_chunks(...):
    print(f"[EMBED] Processing {len(chunks)} chunks")
    # ... rest of function
    print(f"[EMBED] Stored {stats['new_chunks']} new embeddings")
```
