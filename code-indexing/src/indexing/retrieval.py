"""
Code Retrieval Module

Fetches actual code content at query time after vector search returns
chunk metadata. This maintains our security model where raw code is
never stored in the database.

For MVP: Reads from local filesystem.
Future: Will fetch from GitHub API.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """
    Represents retrieved code content.

    Attributes:
        file_path: The actual file path
        content: The code content for the requested lines
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (1-indexed)
        retrieval_source: Where the code was fetched from ("local" or "github")
    """

    file_path: str
    content: str
    start_line: int
    end_line: int
    retrieval_source: str


class RetrievalError(Exception):
    """Error during code retrieval."""

    pass


class FileNotFoundError(RetrievalError):
    """File not found in lookup or filesystem."""

    pass


class HashNotFoundError(RetrievalError):
    """File path hash not found in lookup table."""

    pass


class LinesOutOfRangeError(RetrievalError):
    """Requested lines are outside the file's range."""

    pass


async def _fetch_from_github(
    repo_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
) -> str:
    """
    Fetch code content from GitHub API.

    TODO: Implement GitHub API fetch for production.

    Args:
        repo_id: UUID of the repository
        file_path: Path to the file within the repository
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (1-indexed)

    Returns:
        The code content for the requested lines

    Raises:
        NotImplementedError: This is a stub for future implementation
    """
    raise NotImplementedError(
        "GitHub fetch not yet implemented. "
        "For production, implement using PyGitHub or httpx with GitHub API. "
        "Will need: repo owner/name lookup from repo_id, "
        "GitHub token management, and rate limiting."
    )


def _extract_lines(content: str, start_line: int, end_line: int) -> str:
    """
    Extract specific lines from content.

    Args:
        content: Full file content
        start_line: Starting line (1-indexed)
        end_line: Ending line (1-indexed, inclusive)

    Returns:
        Content for the requested line range

    Raises:
        LinesOutOfRangeError: If lines are outside file bounds
    """
    lines = content.split("\n")
    total_lines = len(lines)

    if start_line < 1:
        raise LinesOutOfRangeError(f"start_line must be >= 1, got {start_line}")

    if end_line > total_lines:
        raise LinesOutOfRangeError(
            f"end_line {end_line} exceeds file length {total_lines}"
        )

    if start_line > end_line:
        raise LinesOutOfRangeError(
            f"start_line {start_line} > end_line {end_line}"
        )

    # Convert to 0-indexed and extract
    extracted = lines[start_line - 1 : end_line]
    return "\n".join(extracted)


async def resolve_file_path(
    repo_id: str,
    file_path_hash: str,
    supabase_client,
) -> str:
    """
    Resolve a file path hash to the actual file path.

    Args:
        repo_id: UUID of the repository
        file_path_hash: SHA256 hash of the file path
        supabase_client: Supabase client instance

    Returns:
        The actual file path

    Raises:
        HashNotFoundError: If the hash is not found in lookup table
    """
    response = (
        supabase_client.table("file_path_lookup")
        .select("file_path")
        .eq("repo_id", repo_id)
        .eq("file_path_hash", file_path_hash)
        .execute()
    )

    if not response.data:
        raise HashNotFoundError(
            f"No file path found for hash {file_path_hash[:16]}... in repo {repo_id}"
        )

    return response.data[0]["file_path"]


async def retrieve_chunk_content(
    repo_id: str,
    file_path_hash: str,
    start_line: int,
    end_line: int,
    supabase_client,
    repo_base_path: Optional[str] = None,
) -> RetrievedChunk:
    """
    Given chunk metadata from vector search, fetch the actual code.

    For MVP: Fetches from file_path_lookup to get real path,
    then reads from local filesystem.

    Future: Will fetch from GitHub API instead.

    Args:
        repo_id: UUID of the repository
        file_path_hash: SHA256 hash of the file path
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (1-indexed)
        supabase_client: Supabase client instance
        repo_base_path: Base path to the local repository (required for local retrieval)

    Returns:
        RetrievedChunk with the actual code content

    Raises:
        HashNotFoundError: If the file path hash is not in the lookup table
        FileNotFoundError: If the file doesn't exist on disk
        LinesOutOfRangeError: If requested lines are outside file bounds
        ValueError: If repo_base_path is not provided for local retrieval

    Example:
        >>> chunk = await retrieve_chunk_content(
        ...     repo_id="550e8400-...",
        ...     file_path_hash="abc123...",
        ...     start_line=10,
        ...     end_line=25,
        ...     supabase_client=client,
        ...     repo_base_path="./my_repo"
        ... )
        >>> print(chunk.content)
    """
    # Resolve hash to actual path
    file_path = await resolve_file_path(repo_id, file_path_hash, supabase_client)

    logger.debug(f"Resolved hash {file_path_hash[:16]}... to {file_path}")

    # For MVP, we require a local path
    if repo_base_path is None:
        raise ValueError(
            "repo_base_path is required for local retrieval. "
            "GitHub API retrieval not yet implemented."
        )

    # Build full path and read file
    full_path = Path(repo_base_path) / file_path

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    try:
        content = full_path.read_text(encoding="utf-8")
    except Exception as e:
        raise RetrievalError(f"Failed to read file {full_path}: {e}")

    # Extract the requested lines
    extracted_content = _extract_lines(content, start_line, end_line)

    return RetrievedChunk(
        file_path=file_path,
        content=extracted_content,
        start_line=start_line,
        end_line=end_line,
        retrieval_source="local",
    )


async def retrieve_multiple_chunks(
    chunks_metadata: list[dict],
    supabase_client,
    repo_base_path: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    Retrieve multiple chunks in batch.

    Args:
        chunks_metadata: List of dicts with keys:
            - repo_id: UUID of the repository
            - file_path_hash: SHA256 hash of file path
            - start_line: Starting line number
            - end_line: Ending line number
        supabase_client: Supabase client instance
        repo_base_path: Base path to local repository

    Returns:
        List of RetrievedChunk objects (in same order as input)

    Note:
        Failed retrievals will be logged but won't stop processing.
        The returned list may be shorter than input if some fail.
    """
    results: list[RetrievedChunk] = []

    for meta in chunks_metadata:
        try:
            chunk = await retrieve_chunk_content(
                repo_id=meta["repo_id"],
                file_path_hash=meta["file_path_hash"],
                start_line=meta["start_line"],
                end_line=meta["end_line"],
                supabase_client=supabase_client,
                repo_base_path=repo_base_path,
            )
            results.append(chunk)
        except RetrievalError as e:
            logger.error(f"Failed to retrieve chunk: {e}")
            continue

    return results


def format_chunk_for_context(chunk: RetrievedChunk, include_line_numbers: bool = True) -> str:
    """
    Format a retrieved chunk for inclusion in LLM context.

    Args:
        chunk: The retrieved chunk
        include_line_numbers: Whether to prefix each line with its number

    Returns:
        Formatted string suitable for LLM context

    Example output:
        ```python
        # File: src/auth.py (lines 10-25)
        10 | def authenticate(username, password):
        11 |     '''Authenticate a user.'''
        12 |     user = find_user(username)
        ...
        ```
    """
    header = f"# File: {chunk.file_path} (lines {chunk.start_line}-{chunk.end_line})"

    if include_line_numbers:
        lines = chunk.content.split("\n")
        numbered_lines = []
        for i, line in enumerate(lines):
            line_num = chunk.start_line + i
            numbered_lines.append(f"{line_num:4d} | {line}")
        body = "\n".join(numbered_lines)
    else:
        body = chunk.content

    return f"```python\n{header}\n{body}\n```"
