# RAG Pipeline: From Question to Answer

This document explains how ScopeDocs retrieves code context and generates answers.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RAG PIPELINE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. INDEXING (one-time per repo)                                           │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │  GitHub  │───►│  Chunk   │───►│  Embed   │───►│  Store in Supabase   │  │
│  │  Fetch   │    │  (AST)   │    │ Together │    │  (pgvector)          │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────────────┘  │
│                                                                             │
│  2. RETRIEVAL (per question)                                               │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │ Question │───►│  Embed   │───►│  Vector  │───►│  Top-K Code Chunks   │  │
│  │          │    │ Together │    │  Search  │    │  (pointers only)     │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────────────┘  │
│                                                                             │
│  3. GENERATION                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │  Fetch   │───►│ Assemble │───►│   LLM    │───►│  Answer with [refs]  │  │
│  │  Code    │    │ Context  │    │  (Qwen)  │    │                      │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Indexing

### Input
- GitHub repository (owner/repo)
- OAuth token for API access

### What Happens
1. **Fetch files** from GitHub API (Python files only for now)
2. **Chunk code** using AST-aware parser (Chonkie + tree-sitter)
3. **Generate embeddings** using Together.ai BGE-large model
4. **Store in Supabase** with pgvector extension

### Output (code_embeddings table)
```sql
SELECT file_path, chunk_index, start_line, end_line, content_hash
FROM code_embeddings
WHERE workspace_id = 'your-workspace-id';
```

### What to Check in Supabase

```sql
-- How many chunks were created?
SELECT COUNT(*) FROM code_embeddings WHERE workspace_id = 'your-id';

-- Which files were indexed?
SELECT DISTINCT file_path FROM code_embeddings WHERE workspace_id = 'your-id';

-- Do embeddings exist? (check one)
SELECT id, file_path,
       embedding IS NOT NULL as has_embedding,
       array_length(embedding::real[], 1) as embedding_dim
FROM code_embeddings
WHERE workspace_id = 'your-id'
LIMIT 5;
```

**Expected**: Each row should have `has_embedding = true` and `embedding_dim = 1024`.

---

## Stage 2: Retrieval (Vector Search)

### Input
- User question: "How does authentication work?"
- workspace_id

### What Happens
1. **Embed the question** using the same model (BGE-large)
2. **Vector search** using pgvector's cosine similarity
3. **Return top-k** most similar code chunks

### The Search Query
```sql
-- This is what happens under the hood:
SELECT
    file_path,
    repo_full_name,
    start_line,
    end_line,
    1 - (embedding <=> $query_embedding::vector) as similarity
FROM code_embeddings
WHERE workspace_id = $workspace_id
ORDER BY embedding <=> $query_embedding::vector
LIMIT 10;
```

### Output (SearchResult objects)
```python
SearchResult(
    file_path="backend/auth/oauth.py",
    repo_full_name="radprk/scopedocs",
    start_line=45,
    end_line=78,
    similarity=0.82,  # Higher = more relevant
    code_content=None,  # Not fetched yet
)
```

### What to Check
- Similarity scores should be > 0.3 for relevant results
- Results should come from files related to the question

---

## Stage 3: Code Fetching (On-Demand)

### Why On-Demand?
**Security**: We don't store code in Supabase. We only store:
- File paths (pointers)
- Line numbers
- Content hashes (for change detection)
- Embeddings (vectors, not readable)

When we need actual code, we fetch it from GitHub.

### Input
- Search results with file paths and line numbers
- GitHub OAuth token

### What Happens
```python
# For each search result:
url = f"https://raw.githubusercontent.com/{repo}/main/{file_path}"
response = await http.get(url, headers={"Authorization": f"token {token}"})
lines = response.text.split("\n")[start_line-1:end_line]
```

### Output
```python
SearchResult(
    file_path="backend/auth/oauth.py",
    start_line=45,
    end_line=78,
    code_content="""
def authenticate_user(token: str) -> User:
    '''Validate OAuth token and return user.'''
    decoded = jwt.decode(token, SECRET_KEY)
    user_id = decoded.get('sub')
    return get_user_by_id(user_id)
""",
)
```

---

## Stage 4: Context Assembly

### Input
- List of SearchResults with code_content
- Original question

### What Happens
Context is formatted for the LLM:

```markdown
### [1] backend/auth/oauth.py:45-78
\`\`\`python
def authenticate_user(token: str) -> User:
    '''Validate OAuth token and return user.'''
    decoded = jwt.decode(token, SECRET_KEY)
    ...
\`\`\`

### [2] backend/models.py:10-25
\`\`\`python
class User(BaseModel):
    id: UUID
    email: str
    ...
\`\`\`
```

### Output (RAGContext)
```python
RAGContext(
    query="How does authentication work?",
    results=[...],  # List of SearchResults
    total_tokens_estimate=450,
)
```

---

## Stage 5: LLM Generation

### Input
- Assembled context
- User question
- System prompt

### The Prompt
```
System: You are a helpful assistant that answers questions about code.
Use the provided context to answer accurately. Always cite your sources.

Context:
[assembled context from Stage 4]

Question: How does authentication work?

Answer the question based on the context above. Cite specific files.
```

### What Happens
LLM (Qwen2.5-Coder-32B) generates an answer referencing the code:

### Output
```markdown
Authentication is handled in `backend/auth/oauth.py` [1].

The `authenticate_user` function validates JWT tokens by:
1. Decoding the token using the secret key
2. Extracting the user ID from the 'sub' claim
3. Looking up the user in the database

The User model [2] defines the structure with fields for id, email, etc.
```

---

## Reference Mapping

The UI needs to make `[1]`, `[2]` clickable. We provide a reference map:

```json
{
  "[1]": {
    "file_path": "backend/auth/oauth.py",
    "repo_full_name": "radprk/scopedocs",
    "start_line": 45,
    "end_line": 78
  },
  "[2]": {
    "file_path": "backend/models.py",
    "repo_full_name": "radprk/scopedocs",
    "start_line": 10,
    "end_line": 25
  }
}
```

When user clicks `[1]`, the UI:
1. Uses the file_path and line numbers
2. Fetches the code from GitHub (or uses cached version)
3. Displays in the code viewer pane

---

## Debugging Checklist

### 1. Check Indexing Worked
```sql
-- In Supabase SQL Editor:
SELECT
    repo_full_name,
    COUNT(*) as chunks,
    COUNT(DISTINCT file_path) as files
FROM code_embeddings
WHERE workspace_id = 'your-workspace-id'
GROUP BY repo_full_name;
```

### 2. Check Embeddings Exist
```sql
SELECT
    file_path,
    embedding IS NOT NULL as has_embedding
FROM code_embeddings
WHERE workspace_id = 'your-workspace-id'
LIMIT 10;
```

All should show `has_embedding = true`.

### 3. Test Vector Search
```sql
-- Manual similarity search (replace with actual embedding)
SELECT file_path,
       1 - (embedding <=> '[0.1, 0.2, ...]'::vector) as sim
FROM code_embeddings
WHERE workspace_id = 'your-workspace-id'
ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector
LIMIT 5;
```

### 4. Check API Logs
Server logs will show:
```
[RAG] Searching for: How does authentication...
[RAG] Query embedded, dim=1024
[RAG] Found 5 results
[RAG] Fetched backend/auth/oauth.py:45-78
```

---

## Encryption & Security

### What's Encrypted
- **OAuth tokens**: Stored in `oauth_tokens` table
  - Should use Supabase's encryption at rest
  - Consider encrypting `access_token` column with `pgcrypto`
- **Database connection**: Uses SSL by default with Supabase

### What's NOT Stored (Security by Design)
- **Code content**: Never stored, only fetched on-demand
- **Raw messages**: Slack/Linear messages are summarized, not stored verbatim

### To Add Encryption for OAuth Tokens
```sql
-- Encrypt tokens (run once):
ALTER TABLE oauth_tokens
ADD COLUMN access_token_encrypted bytea;

-- When inserting:
INSERT INTO oauth_tokens (access_token_encrypted, ...)
VALUES (pgp_sym_encrypt($token, $encryption_key), ...);

-- When reading:
SELECT pgp_sym_decrypt(access_token_encrypted, $encryption_key) as access_token
FROM oauth_tokens WHERE ...;
```

---

## Code Rendering

### Current State
The chunks are created and stored, but there's no UI to render actual documentation yet.

### What You Have
1. **Indexing** ✅ - Creates chunks in `code_embeddings`
2. **Embeddings** ✅ - Stores vectors for search (needs API key)
3. **RAG Search** ✅ - `backend/ai/search.py` can find relevant chunks
4. **LLM Client** ✅ - `backend/ai/client.py` can generate docs

### What's Missing for Full Rendering
1. **Doc Generation Endpoint** - Call LLM to generate markdown
2. **Store in generated_docs** - Save for caching
3. **UI to Display** - Render markdown with clickable refs

### Quick Test (Python)
```python
import asyncio
from backend.ai import ask_codebase
from backend.database import get_pool

async def test():
    pool = await get_pool()
    answer, refs = await ask_codebase(
        pool=pool,
        question="How does the server start?",
        workspace_id="your-workspace-id",
        github_token="ghp_...",
        repo_full_name="radprk/scopedocs",
    )
    print(answer)
    print(refs)

asyncio.run(test())
```
