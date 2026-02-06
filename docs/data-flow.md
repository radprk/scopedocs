# Data Flow

How data moves through ScopeDocs, from GitHub to documentation.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA FLOW                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │
│  │ GitHub  │───▶│  Fetch  │───▶│  Chunk  │───▶│  Embed  │───▶│  Store  │   │
│  │  API    │    │  Code   │    │  Code   │    │ Vectors │    │   DB    │   │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘   │
│                                                                              │
│  OAuth Token    File Content   CodeChunk[]    float[1024]    PostgreSQL    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Authentication

**Entry point**: `backend/integrations/oauth/routes.py`

```python
# User clicks "Connect GitHub" → redirects to GitHub OAuth
/api/oauth/github/connect
    → GitHub OAuth page
    → User authorizes
    → /api/oauth/github/callback
    → Token stored in oauth_tokens table
```

**Data stored**:

```sql
INSERT INTO oauth_tokens (workspace_id, provider, access_token)
VALUES ('ws_123', 'github', 'gho_xxxxx');
```

---

## Stage 2: Fetch Code

**Entry point**: `backend/server.py` → `/api/index/repo`

```python
# Request:
POST /api/index/repo
{
    "workspace_id": "ws_123",
    "repo_full_name": "owner/repo",
    "branch": "main"
}

# Process:
1. Get OAuth token from oauth_tokens
2. Call GitHub API: GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
3. For each .py file: GET /repos/{owner}/{repo}/contents/{path}
4. Pass file content to chunker
```

**Key insight**: We fetch code on-demand from GitHub, we don't store it.

---

## Stage 3: Chunk Code

**Entry point**: `code-indexing/src/indexing/chunker.py`

```python
# Input: Raw file content
file_content = """
def hello():
    print("Hello")

def goodbye():
    print("Goodbye")
"""

# Process: chunk_code_file()
1. Parse with tree-sitter (AST)
2. Split at function/class boundaries
3. Hash each chunk for change detection

# Output: List[CodeChunk]
[
    CodeChunk(
        content="def hello():\n    print(\"Hello\")",
        start_line=1,
        end_line=2,
        chunk_hash="abc123..."
    ),
    CodeChunk(
        content="def goodbye():\n    print(\"Goodbye\")",
        start_line=4,
        end_line=5,
        chunk_hash="def456..."
    )
]
```

**Key insight**: Chunks split at semantic boundaries, not arbitrary line counts.

---

## Stage 4: Generate Embeddings

**Entry point**: `backend/ai/embeddings.py`

```python
# Input: CodeChunk[]
chunks = [chunk1, chunk2, ...]

# Process: embed_code_chunks()
1. Check chunk_hash in DB → skip if already embedded
2. Call Together.ai API:
   POST https://api.together.xyz/v1/embeddings
   {
       "model": "BAAI/bge-large-en-v1.5",
       "input": ["def hello()...", "def goodbye()..."]
   }
3. Store embeddings in code_embeddings table

# Output: float[1024] per chunk
[0.123, -0.456, 0.789, ...]  # 1024 dimensions
```

**Key insight**: Content hashing means we only embed changed chunks.

---

## Stage 5: Store in Database

**Schema**: `db/schema.sql`

```sql
-- Pointer to code location (NOT the code itself)
INSERT INTO code_chunks (
    workspace_id,
    repo_full_name,
    file_path,
    start_line,
    end_line,
    chunk_hash
) VALUES (...);

-- Vector embedding
INSERT INTO code_embeddings (
    chunk_id,
    embedding
) VALUES (
    'chunk_123',
    '[0.123, -0.456, ...]'::vector(1024)
);
```

**Key insight**: We store pointers + embeddings, not source code.

---

## Stage 6: Generate Documentation (Week 2)

**Future flow**:

```python
# Input: User query
"How does authentication work?"

# Process:
1. Embed the query → float[1024]
2. Vector similarity search in code_embeddings
3. Get top-k chunk pointers
4. Fetch actual code from GitHub (on-demand)
5. Pass code + query to LLM (Qwen via Together.ai)
6. Generate documentation with [n] references

# Output: Markdown with code references
"Authentication uses OAuth2 flow [1]. The callback handler [2]..."
```

---

## Debug Trace

To see data flow in action, add these prints:

```python
# backend/server.py - Stage 2
@app.post("/api/index/repo")
async def api_index_repo(data: dict):
    print(f"[FETCH] Starting: {data['repo_full_name']}")
    # ... fetch logic
    print(f"[FETCH] Got {len(files)} files")

# code-indexing/chunker.py - Stage 3
def chunk_code_file(file_content, file_path, max_tokens=512):
    print(f"[CHUNK] Input: {file_path} ({len(file_content)} bytes)")
    # ... chunk logic
    print(f"[CHUNK] Output: {len(chunks)} chunks")

# backend/ai/embeddings.py - Stage 4
async def embed_code_chunks(...):
    print(f"[EMBED] Input: {len(chunks)} chunks")
    # ... embed logic
    print(f"[EMBED] New: {stats['new_chunks']}, Skipped: {stats['skipped']}")
```

---

## Data Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA LIFECYCLE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Source Code (GitHub)                                           │
│      │                                                          │
│      ▼                                                          │
│  Temporary: In-memory during processing                         │
│      │                                                          │
│      ├──▶ Chunk Hash (SHA256) ──▶ Stored in DB                 │
│      │                                                          │
│      ├──▶ File Pointer ──▶ Stored in DB                        │
│      │    (path, start_line, end_line)                         │
│      │                                                          │
│      └──▶ Embedding Vector ──▶ Stored in DB                    │
│           (float[1024])                                         │
│                                                                  │
│  Source Code ──▶ NOT STORED (SOC 2 compliant)                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```
