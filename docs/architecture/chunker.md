# Chunker Architecture

The chunker is the heart of ScopeDocs. It splits code into semantic units that preserve meaning.

## Location

`code-indexing/src/indexing/chunker.py`

## Why AST-Aware Chunking?

**Naive approach** (bad):
```python
# Split every 50 lines
chunks = [code[i:i+50] for i in range(0, len(lines), 50)]
```

This breaks functions in the middle, loses context, and creates meaningless chunks.

**AST-aware approach** (good):
```python
# Split at function/class boundaries
def hello():        # ← Chunk 1 starts
    print("hi")     # ← Chunk 1 ends

def goodbye():      # ← Chunk 2 starts
    print("bye")    # ← Chunk 2 ends
```

This preserves semantic meaning - each chunk is a complete unit.

---

## Core Data Structure

```python
# Lines 19-46: CodeChunk dataclass
@dataclass
class CodeChunk:
    content: str      # The actual code text
    start_line: int   # Where it starts in file
    end_line: int     # Where it ends in file
    chunk_hash: str   # SHA256 for change detection
    language: str     # "python", "javascript", etc.
    file_path: str    # Original file path
```

**Key fields**:
- `content`: Used temporarily for embedding, then discarded
- `start_line/end_line`: Stored permanently as pointers
- `chunk_hash`: Used to detect if code changed (skip re-embedding)

---

## Main Function

```python
# Lines 104-186: chunk_code_file
def chunk_code_file(
    file_content: str,
    file_path: str,
    max_tokens: int = 512
) -> List[CodeChunk]:
    """
    Split a code file into semantic chunks.

    Args:
        file_content: The raw source code
        file_path: Path for language detection
        max_tokens: Maximum tokens per chunk (for embedding limits)

    Returns:
        List of CodeChunk objects
    """
```

---

## How It Works

### Step 1: Language Detection

```python
# Detect language from file extension
extension = Path(file_path).suffix.lower()
language = EXTENSION_TO_LANGUAGE.get(extension, "text")

# Supported: .py, .js, .ts, .go, .rs, .java, .rb, .c, .cpp, .h
```

### Step 2: Parse AST

```python
# Use tree-sitter to parse code into AST
from chonkie import SemanticChunker

chunker = SemanticChunker(
    tokenizer="cl100k_base",  # GPT-4 tokenizer
    max_chunk_size=max_tokens,
    language=language
)
```

### Step 3: Split at Boundaries

Tree-sitter identifies:
- Function definitions
- Class definitions
- Method definitions
- Top-level statements

Each becomes a chunk (unless too large).

### Step 4: Handle Large Functions

```python
# If a function exceeds max_tokens, split further
if len(tokens) > max_tokens:
    # Split at logical breakpoints:
    # - Blank lines
    # - Comments
    # - Statement boundaries
```

### Step 5: Generate Hash

```python
import hashlib

def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()

chunk.chunk_hash = hash_content(chunk.content)
```

---

## Example

Input file (`example.py`):
```python
"""Module docstring."""

import os

def fetch_data(url: str) -> dict:
    """Fetch data from URL."""
    response = requests.get(url)
    return response.json()

class DataProcessor:
    """Process fetched data."""

    def __init__(self, config):
        self.config = config

    def process(self, data):
        return self.transform(data)

    def transform(self, data):
        return {k: v.upper() for k, v in data.items()}
```

Output chunks:
```python
[
    CodeChunk(
        content='"""Module docstring."""\n\nimport os',
        start_line=1,
        end_line=3,
        chunk_hash="abc123..."
    ),
    CodeChunk(
        content='def fetch_data(url: str) -> dict:\n    """Fetch data from URL."""\n    response = requests.get(url)\n    return response.json()',
        start_line=5,
        end_line=8,
        chunk_hash="def456..."
    ),
    CodeChunk(
        content='class DataProcessor:\n    """Process fetched data."""\n    \n    def __init__(self, config):\n        self.config = config\n    \n    def process(self, data):\n        return self.transform(data)\n    \n    def transform(self, data):\n        return {k: v.upper() for k, v in data.items()}',
        start_line=10,
        end_line=20,
        chunk_hash="ghi789..."
    )
]
```

---

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_tokens` | 512 | Maximum tokens per chunk |
| `min_chunk_size` | 50 | Minimum characters (skip tiny chunks) |
| `overlap` | 0 | Token overlap between chunks (for context) |

---

## Debug Tips

Add prints to understand chunking:

```python
def chunk_code_file(file_content, file_path, max_tokens=512):
    print(f"[CHUNK] Processing: {file_path}")
    print(f"[CHUNK] File size: {len(file_content)} bytes")

    # ... chunking logic ...

    for i, chunk in enumerate(chunks):
        print(f"[CHUNK] {i+1}: lines {chunk.start_line}-{chunk.end_line} ({len(chunk.content)} chars)")

    print(f"[CHUNK] Total: {len(chunks)} chunks")
    return chunks
```

---

## Related Files

- `backend/ai/embeddings.py` - Consumes chunks, generates embeddings
- `db/schema.sql` - `code_chunks` table stores pointers
- `backend/server.py` - `/api/index/repo` endpoint triggers chunking
