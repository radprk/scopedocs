# Ingestion Architecture

How code enters ScopeDocs from GitHub.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION FLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User Request                                                    │
│       │                                                          │
│       ▼                                                          │
│  POST /api/index/repo                                           │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Get OAuth   │───▶│ Fetch Tree  │───▶│ Filter Files│         │
│  │   Token     │    │ from GitHub │    │  (.py, .js) │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│                                               │                  │
│                                               ▼                  │
│                      ┌─────────────┐    ┌─────────────┐         │
│                      │   Chunk     │◀───│ Fetch File  │         │
│                      │   Code      │    │  Contents   │         │
│                      └─────────────┘    └─────────────┘         │
│                            │                                     │
│                            ▼                                     │
│                      ┌─────────────┐                            │
│                      │   Return    │                            │
│                      │   Stats     │                            │
│                      └─────────────┘                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Entry Point

**File**: `backend/server.py`

```python
@app.post("/api/index/repo")
async def api_index_repo(data: IndexRepoRequest):
    """
    Index a GitHub repository.

    Request:
        {
            "workspace_id": "ws_123",
            "repo_full_name": "owner/repo",
            "branch": "main"  # optional, defaults to default branch
        }

    Response:
        {
            "files_processed": 42,
            "chunks_created": 156,
            "skipped_unchanged": 23
        }
    """
```

---

## Step 1: Get OAuth Token

```python
# Retrieve stored GitHub token for this workspace
token = await get_oauth_token(workspace_id, "github")

if not token:
    raise HTTPException(401, "GitHub not connected. Visit /api/oauth/github/connect")
```

---

## Step 2: Fetch Repository Tree

```python
# GitHub API: Get all files in the repository
async def fetch_repo_tree(token: str, repo: str, branch: str) -> List[str]:
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        })

    tree = response.json()["tree"]
    return [item["path"] for item in tree if item["type"] == "blob"]
```

Response example:
```json
{
    "tree": [
        {"path": "backend/server.py", "type": "blob"},
        {"path": "backend/models.py", "type": "blob"},
        {"path": "README.md", "type": "blob"}
    ]
}
```

---

## Step 3: Filter Files

Only process code files we can chunk:

```python
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".rb",
    ".c", ".cpp", ".h", ".hpp"
}

def should_process(path: str) -> bool:
    ext = Path(path).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS
```

---

## Step 4: Fetch File Contents

```python
async def fetch_file_content(token: str, repo: str, path: str) -> str:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3.raw"  # Get raw content
        })

    return response.text
```

**Important**: Use `Accept: application/vnd.github.v3.raw` to get raw file content instead of base64-encoded JSON.

---

## Step 5: Chunk Code

```python
from code_indexing.src.indexing.chunker import chunk_code_file

for file_path in filtered_files:
    content = await fetch_file_content(token, repo, file_path)
    chunks = chunk_code_file(content, file_path)

    for chunk in chunks:
        # Check if chunk already exists (by hash)
        existing = await get_chunk_by_hash(chunk.chunk_hash)

        if existing:
            stats["skipped_unchanged"] += 1
        else:
            await store_chunk(workspace_id, repo, commit_sha, chunk)
            stats["chunks_created"] += 1
```

---

## Rate Limiting

GitHub API has rate limits:
- Authenticated: 5,000 requests/hour
- Per-file fetch: 1 request per file

For large repos, batch requests:

```python
# Batch file fetches (up to 10 concurrent)
async def fetch_files_batch(token: str, repo: str, paths: List[str]) -> Dict[str, str]:
    semaphore = asyncio.Semaphore(10)

    async def fetch_one(path):
        async with semaphore:
            return path, await fetch_file_content(token, repo, path)

    results = await asyncio.gather(*[fetch_one(p) for p in paths])
    return dict(results)
```

---

## Incremental Updates

Only process changed files:

```python
async def index_repo_incremental(workspace_id, repo, new_commit, old_commit):
    # Get changed files between commits
    url = f"https://api.github.com/repos/{repo}/compare/{old_commit}...{new_commit}"

    response = await client.get(url, ...)
    changed_files = [f["filename"] for f in response.json()["files"]]

    # Only process changed files
    for file_path in changed_files:
        if should_process(file_path):
            content = await fetch_file_content(token, repo, file_path)
            chunks = chunk_code_file(content, file_path)
            # ... store chunks
```

---

## Debug Tips

Add prints to trace ingestion:

```python
@app.post("/api/index/repo")
async def api_index_repo(data: IndexRepoRequest):
    print(f"[INGEST] Starting: {data.repo_full_name}")

    files = await fetch_repo_tree(...)
    print(f"[INGEST] Found {len(files)} total files")

    filtered = [f for f in files if should_process(f)]
    print(f"[INGEST] Processing {len(filtered)} code files")

    for file_path in filtered:
        print(f"[INGEST] Fetching: {file_path}")
        content = await fetch_file_content(...)

        chunks = chunk_code_file(content, file_path)
        print(f"[INGEST] Created {len(chunks)} chunks from {file_path}")

    print(f"[INGEST] Complete: {stats}")
    return stats
```

---

## Error Handling

```python
async def fetch_file_content(token, repo, path):
    try:
        response = await client.get(url, ...)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"[INGEST] File not found: {path}")
            return None
        elif e.response.status_code == 403:
            print(f"[INGEST] Rate limited, waiting...")
            await asyncio.sleep(60)
            return await fetch_file_content(token, repo, path)  # Retry
        raise
```

---

## Related Files

- `backend/integrations/oauth/routes.py` - OAuth token management
- `code-indexing/src/indexing/chunker.py` - Code chunking
- `backend/storage/postgres.py` - Chunk storage
