# Embedding Architecture

How ScopeDocs generates vector embeddings using Together.ai.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      EMBEDDING FLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CodeChunk[]                                                     │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Check Hash  │───▶│ Call API    │───▶│   Store     │         │
│  │ (skip known)│    │ (Together.ai)│   │ (pgvector)  │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│                                                                  │
│  Input:             API Call:           Output:                  │
│  "def hello()..."   POST /embeddings    [0.12, -0.45, ...]     │
│                     model: BGE-large    (1024 dimensions)        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Location

- Client: `backend/ai/client.py`
- Service: `backend/ai/embeddings.py`
- Routes: `backend/ai/routes.py`

---

## Together.ai Client

**File**: `backend/ai/client.py`

```python
from together import Together

# Model configuration
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIMS = 1024

class TogetherClient:
    def __init__(self):
        self.client = Together(api_key=os.environ["TOGETHER_API_KEY"])

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of strings to embed (max 2048 tokens each)

        Returns:
            List of embedding vectors (1024 floats each)
        """
        response = self.client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts
        )

        return [item.embedding for item in response.data]
```

---

## Why BGE-large?

| Model | Dimensions | Quality | Speed | Cost |
|-------|------------|---------|-------|------|
| BGE-large-en-v1.5 | 1024 | Best | Medium | $0.016/1M tokens |
| BGE-base-en-v1.5 | 768 | Good | Fast | $0.008/1M tokens |
| all-MiniLM-L6-v2 | 384 | OK | Fastest | $0.002/1M tokens |

We chose **BGE-large** because:
1. Best quality for code understanding
2. 1024 dimensions capture nuance
3. Good balance of cost and performance

---

## Embedding Service

**File**: `backend/ai/embeddings.py`

```python
class EmbeddingService:
    def __init__(self, client: TogetherClient, storage: PostgresStorage):
        self.client = client
        self.storage = storage

    async def embed_code_chunks(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        chunks: List[CodeChunk]
    ) -> Dict:
        """
        Generate and store embeddings for code chunks.

        Returns:
            {
                "total": 100,
                "new_chunks": 75,
                "skipped": 25  # Already had embedding
            }
        """
        stats = {"total": len(chunks), "new_chunks": 0, "skipped": 0}

        for chunk in chunks:
            # Skip if already embedded (hash match)
            existing = await self.storage.get_chunk_by_hash(chunk.chunk_hash)
            if existing:
                stats["skipped"] += 1
                continue

            # Store chunk pointer
            chunk_id = await self.storage.store_chunk(
                workspace_id, repo_full_name, commit_sha, chunk
            )

            # Generate embedding
            embeddings = await self.client.embed([chunk.content])

            # Store embedding
            await self.storage.store_embedding(chunk_id, embeddings[0])
            stats["new_chunks"] += 1

        return stats
```

---

## Batching for Efficiency

Process chunks in batches to reduce API calls:

```python
async def embed_code_chunks_batched(self, chunks: List[CodeChunk], batch_size: int = 10):
    # Filter to only new chunks
    new_chunks = [c for c in chunks if not await self.storage.get_chunk_by_hash(c.chunk_hash)]

    # Process in batches
    for i in range(0, len(new_chunks), batch_size):
        batch = new_chunks[i:i + batch_size]

        # Store chunk pointers
        chunk_ids = [await self.storage.store_chunk(..., c) for c in batch]

        # Batch API call (much faster!)
        texts = [c.content for c in batch]
        embeddings = await self.client.embed(texts)  # Single API call

        # Store embeddings
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            await self.storage.store_embedding(chunk_id, embedding)
```

---

## API Endpoint

**File**: `backend/ai/routes.py`

```python
@router.post("/embed/code")
async def embed_code(request: EmbedCodeRequest):
    """
    Generate embeddings for indexed code chunks.

    Request:
        {
            "workspace_id": "ws_123",
            "repo_full_name": "owner/repo",
            "commit_sha": "abc123"
        }

    Response:
        {
            "total": 100,
            "new_chunks": 75,
            "skipped": 25
        }
    """
    # Get chunks from database
    chunks = await storage.list_chunks_without_embeddings(
        request.workspace_id,
        request.repo_full_name
    )

    # Generate embeddings
    service = EmbeddingService(client, storage)
    stats = await service.embed_code_chunks(
        request.workspace_id,
        request.repo_full_name,
        request.commit_sha,
        chunks
    )

    return stats
```

---

## Content Hashing

Skip unchanged code to save API costs:

```python
# When code changes, hash changes
"def hello(): print('hi')"    → hash: "abc123"
"def hello(): print('hello')" → hash: "def456"  # Different!

# Only embed if hash is new
existing = await storage.get_chunk_by_hash(chunk.chunk_hash)
if existing:
    print(f"[EMBED] Skipping (unchanged): {chunk.file_path}")
    return existing.embedding  # Reuse old embedding
```

---

## Vector Storage

Embeddings stored in PostgreSQL with pgvector:

```sql
-- Store embedding
INSERT INTO code_embeddings (id, chunk_id, embedding)
VALUES ('emb_123', 'chunk_456', '[0.12, -0.45, ...]'::vector(1024));

-- Similarity search (for future RAG)
SELECT c.file_path, c.start_line, c.end_line,
       1 - (e.embedding <=> query_vector) AS similarity
FROM code_embeddings e
JOIN code_chunks c ON e.chunk_id = c.id
ORDER BY e.embedding <=> query_vector
LIMIT 10;
```

---

## Debug Tips

Add prints to trace embedding:

```python
async def embed_code_chunks(self, chunks):
    print(f"[EMBED] Processing {len(chunks)} chunks")

    for chunk in chunks:
        print(f"[EMBED] Chunk: {chunk.file_path}:{chunk.start_line}-{chunk.end_line}")
        print(f"[EMBED] Hash: {chunk.chunk_hash[:16]}...")

        if await self.storage.get_chunk_by_hash(chunk.chunk_hash):
            print(f"[EMBED] → Skipped (exists)")
            continue

        embedding = await self.client.embed([chunk.content])
        print(f"[EMBED] → Generated: {embedding[0][:5]}... (1024 dims)")

        await self.storage.store_embedding(chunk_id, embedding[0])
        print(f"[EMBED] → Stored")

    print(f"[EMBED] Complete: {stats}")
```

---

## Error Handling

```python
async def embed_with_retry(self, texts: List[str], max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return await self.client.embed(texts)
        except RateLimitError:
            wait_time = 2 ** attempt  # Exponential backoff
            print(f"[EMBED] Rate limited, waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
        except APIError as e:
            print(f"[EMBED] API error: {e}")
            if attempt == max_retries - 1:
                raise

    raise Exception("Max retries exceeded")
```

---

## Related Files

- `backend/ai/client.py` - Together.ai API client
- `backend/storage/postgres.py` - Vector storage
- `code-indexing/src/indexing/chunker.py` - Produces chunks to embed
