"""
AST-Aware Code Chunking Module

Uses Chonkie with tree-sitter to chunk Python code by semantic boundaries
(functions, classes, etc.) rather than arbitrary character counts.

This ensures that code chunks are semantically coherent and don't split
mid-function or mid-class.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeChunk:
    """
    Represents a semantically coherent chunk of code.

    Attributes:
        content: The actual code text
        start_line: 1-indexed starting line in original file
        end_line: 1-indexed ending line in original file
        chunk_hash: SHA256 hash of the content
        chunk_index: Position of this chunk within the file (0-indexed)
    """

    content: str
    start_line: int
    end_line: int
    chunk_hash: str
    chunk_index: int

    def __post_init__(self):
        """Validate chunk data after initialization."""
        if self.start_line < 1:
            raise ValueError("start_line must be >= 1")
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be >= 0")


def _compute_chunk_hash(content: str) -> str:
    """Compute SHA256 hash of chunk content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_line_numbers(full_content: str, chunk_content: str, start_search: int = 0) -> tuple[int, int]:
    """
    Find the line numbers for a chunk within the full file content.

    Args:
        full_content: The complete file content
        chunk_content: The chunk content to find
        start_search: Character position to start searching from

    Returns:
        Tuple of (start_line, end_line), 1-indexed
    """
    # Find where the chunk appears in the full content
    chunk_start = full_content.find(chunk_content, start_search)
    if chunk_start == -1:
        # Chunk not found, fall back to counting newlines in chunk
        chunk_lines = chunk_content.count("\n") + 1
        return (1, chunk_lines)

    # Count newlines before chunk to get start line
    start_line = full_content[:chunk_start].count("\n") + 1

    # Count newlines in chunk to get end line
    end_line = start_line + chunk_content.count("\n")

    return (start_line, end_line)


def _create_fallback_chunk(file_content: str, file_path: str) -> list[CodeChunk]:
    """
    Create a single chunk for the entire file (fallback when parsing fails).

    Args:
        file_content: The complete file content
        file_path: Path to the file (for logging)

    Returns:
        List containing a single CodeChunk for the entire file
    """
    lines = file_content.split("\n")
    return [
        CodeChunk(
            content=file_content,
            start_line=1,
            end_line=len(lines),
            chunk_hash=_compute_chunk_hash(file_content),
            chunk_index=0,
        )
    ]


def chunk_code_file(
    file_content: str,
    file_path: str,
    max_tokens: int = 512,
) -> list[CodeChunk]:
    """
    Parse a Python file and return semantically coherent chunks.

    Uses Chonkie's CodeChunker with tree-sitter-python to chunk code
    by AST boundaries (functions, classes, etc.).

    Args:
        file_content: The raw source code as a string
        file_path: Path to the file (for error messages and language detection)
        max_tokens: Maximum tokens per chunk (default 512)

    Returns:
        List of CodeChunk objects representing semantic units

    Example:
        >>> content = open("myfile.py").read()
        >>> chunks = chunk_code_file(content, "myfile.py")
        >>> for chunk in chunks:
        ...     print(f"Lines {chunk.start_line}-{chunk.end_line}")
    """
    # Handle empty files
    if not file_content or not file_content.strip():
        logger.warning(f"Empty file: {file_path}")
        return []

    try:
        # Import Chonkie's CodeChunker
        from chonkie import CodeChunker

        # Initialize the chunker with tree-sitter-python
        # Chonkie handles tree-sitter setup internally
        chunker = CodeChunker(
            language="python",
            chunk_size=max_tokens,
        )

        # Chunk the code
        chonkie_chunks = chunker.chunk(file_content)

        if not chonkie_chunks:
            logger.warning(f"No chunks returned for {file_path}, using fallback")
            return _create_fallback_chunk(file_content, file_path)

        # Convert Chonkie chunks to our CodeChunk format
        result: list[CodeChunk] = []
        search_pos = 0

        for idx, chunk in enumerate(chonkie_chunks):
            chunk_text = chunk.text

            # Get line numbers for this chunk
            start_line, end_line = _get_line_numbers(file_content, chunk_text, search_pos)

            # Update search position to avoid finding the same chunk again
            chunk_pos = file_content.find(chunk_text, search_pos)
            if chunk_pos != -1:
                search_pos = chunk_pos + len(chunk_text)

            result.append(
                CodeChunk(
                    content=chunk_text,
                    start_line=start_line,
                    end_line=end_line,
                    chunk_hash=_compute_chunk_hash(chunk_text),
                    chunk_index=idx,
                )
            )

        logger.info(f"Chunked {file_path} into {len(result)} chunks")
        return result

    except ImportError as e:
        logger.error(f"Chonkie not installed: {e}. Using fallback chunker.")
        return _fallback_chunk_code(file_content, file_path, max_tokens)

    except Exception as e:
        logger.warning(f"Failed to chunk {file_path} with Chonkie: {e}. Using fallback.")
        return _fallback_chunk_code(file_content, file_path, max_tokens)


def _fallback_chunk_code(
    file_content: str,
    file_path: str,
    max_tokens: int = 512,
) -> list[CodeChunk]:
    """
    Fallback chunker that uses simple heuristics when tree-sitter fails.

    Tries to split on function/class definitions, otherwise treats
    the entire file as one chunk.

    Args:
        file_content: The raw source code
        file_path: Path to the file
        max_tokens: Maximum tokens per chunk (approximate)

    Returns:
        List of CodeChunk objects
    """
    import re

    lines = file_content.split("\n")

    # Approximate tokens as words (rough estimate: 1 token ≈ 4 chars)
    chars_per_chunk = max_tokens * 4

    # Try to find function and class definitions
    definition_pattern = re.compile(r"^(def |class |async def )", re.MULTILINE)
    matches = list(definition_pattern.finditer(file_content))

    if not matches:
        # No definitions found, return whole file as one chunk
        logger.info(f"No function/class definitions in {file_path}, treating as single chunk")
        return _create_fallback_chunk(file_content, file_path)

    # Split at definition boundaries
    chunks: list[CodeChunk] = []
    chunk_boundaries: list[int] = [0] + [m.start() for m in matches] + [len(file_content)]

    for idx in range(len(chunk_boundaries) - 1):
        start_pos = chunk_boundaries[idx]
        end_pos = chunk_boundaries[idx + 1]

        # Skip empty chunks (consecutive definitions)
        chunk_text = file_content[start_pos:end_pos].strip()
        if not chunk_text:
            continue

        # Calculate line numbers
        start_line = file_content[:start_pos].count("\n") + 1
        end_line = file_content[:end_pos].count("\n") + 1

        chunks.append(
            CodeChunk(
                content=chunk_text,
                start_line=start_line,
                end_line=end_line,
                chunk_hash=_compute_chunk_hash(chunk_text),
                chunk_index=len(chunks),
            )
        )

    # If we got no valid chunks, fall back to single chunk
    if not chunks:
        return _create_fallback_chunk(file_content, file_path)

    logger.info(f"Fallback chunker split {file_path} into {len(chunks)} chunks")
    return chunks


def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in a text string.

    Uses a simple heuristic: ~4 characters per token on average.
    For more accurate counting, use tiktoken.

    Args:
        text: The text to estimate tokens for

    Returns:
        Estimated token count
    """
    # Simple heuristic: average of 4 chars per token
    return len(text) // 4


def setup_tree_sitter() -> bool:
    """
    Verify tree-sitter-python is available.

    Chonkie handles most of the tree-sitter setup, but this function
    can be used to verify the installation is working.

    Returns:
        True if tree-sitter-python is available, False otherwise
    """
    try:
        from chonkie import CodeChunker

        # Try to create a chunker (this will fail if tree-sitter isn't set up)
        chunker = CodeChunker(language="python", chunk_size=512)

        # Try to chunk a simple file
        test_code = "def hello():\n    pass\n"
        chunks = chunker.chunk(test_code)

        logger.info("tree-sitter-python is available and working")
        return True

    except Exception as e:
        logger.error(f"tree-sitter-python setup failed: {e}")
        return False
