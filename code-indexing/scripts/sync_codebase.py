#!/usr/bin/env python3
"""
Codebase Sync ETL Script

Indexes a codebase into Supabase using AST-aware chunking.
Uses content hashing to detect changes and only re-indexes what's changed.

Usage:
    python scripts/sync_codebase.py --repo-path ./dummy_repo --repo-id <uuid>

Environment Variables:
    SUPABASE_URL: Your Supabase project URL
    SUPABASE_KEY: Your Supabase anon or service key
"""

import argparse
import hashlib
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from indexing.chunker import chunk_code_file, CodeChunk

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Directories to ignore when walking the codebase
IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    "__pypackages__",
    "build",
    "dist",
    ".eggs",
    "*.egg-info",
}


@dataclass
class FileInfo:
    """Information about a file in the repository."""

    path: Path
    relative_path: str
    content: str
    content_hash: str
    path_hash: str


@dataclass
class SyncStats:
    """Statistics from a sync operation."""

    new_files: int = 0
    modified_files: int = 0
    deleted_files: int = 0
    unchanged_files: int = 0
    total_chunks: int = 0
    errors: list[str] = field(default_factory=list)


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_mock_embedding(dimensions: int = 768) -> list[float]:
    """
    Generate a mock embedding vector.

    In production, this would call an embedding API (e.g., OpenAI, Cohere).
    For now, we generate random floats for testing the data pipeline.

    Args:
        dimensions: Number of dimensions for the embedding vector

    Returns:
        List of random floats representing a mock embedding
    """
    return [random.random() for _ in range(dimensions)]


def should_ignore_path(path: Path) -> bool:
    """Check if a path should be ignored during indexing."""
    for part in path.parts:
        if part in IGNORE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def discover_python_files(repo_path: Path) -> list[FileInfo]:
    """
    Walk the repository and discover all Python files.

    Args:
        repo_path: Path to the repository root

    Returns:
        List of FileInfo objects for each Python file
    """
    files: list[FileInfo] = []

    for path in repo_path.rglob("*.py"):
        if should_ignore_path(path.relative_to(repo_path)):
            continue

        try:
            content = path.read_text(encoding="utf-8")
            relative_path = str(path.relative_to(repo_path))

            files.append(
                FileInfo(
                    path=path,
                    relative_path=relative_path,
                    content=content,
                    content_hash=compute_hash(content),
                    path_hash=compute_hash(relative_path),
                )
            )
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")

    return files


@dataclass
class IndexedFile:
    """Represents a file that's already indexed in the database."""

    file_path_hash: str
    file_path: str
    file_content_hash: str


class CodebaseSync:
    """
    Handles syncing a codebase to Supabase.

    Uses content hashing to detect changes and minimize re-indexing.
    """

    def __init__(self, supabase_url: str, supabase_key: str, repo_id: str):
        """
        Initialize the sync handler.

        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase API key
            repo_id: UUID of the repository being indexed
        """
        from supabase import create_client, Client

        self.client: Client = create_client(supabase_url, supabase_key)
        self.repo_id = repo_id

    def get_indexed_files(self) -> dict[str, IndexedFile]:
        """
        Fetch all currently indexed files for this repo.

        Returns:
            Dict mapping file_path_hash to IndexedFile
        """
        response = (
            self.client.table("file_path_lookup")
            .select("file_path_hash, file_path, file_content_hash")
            .eq("repo_id", self.repo_id)
            .execute()
        )

        return {
            row["file_path_hash"]: IndexedFile(
                file_path_hash=row["file_path_hash"],
                file_path=row["file_path"],
                file_content_hash=row["file_content_hash"],
            )
            for row in response.data
        }

    def categorize_files(
        self,
        current_files: list[FileInfo],
        indexed_files: dict[str, IndexedFile],
    ) -> tuple[list[FileInfo], list[FileInfo], list[FileInfo], list[IndexedFile]]:
        """
        Categorize files into NEW, MODIFIED, UNCHANGED, and DELETED.

        Args:
            current_files: Files currently in the repository
            indexed_files: Files already indexed in the database

        Returns:
            Tuple of (new_files, modified_files, unchanged_files, deleted_files)
        """
        new_files: list[FileInfo] = []
        modified_files: list[FileInfo] = []
        unchanged_files: list[FileInfo] = []

        current_hashes = set()

        for file_info in current_files:
            current_hashes.add(file_info.path_hash)

            if file_info.path_hash not in indexed_files:
                # File is new
                new_files.append(file_info)
            elif indexed_files[file_info.path_hash].file_content_hash != file_info.content_hash:
                # File was modified
                modified_files.append(file_info)
            else:
                # File is unchanged
                unchanged_files.append(file_info)

        # Find deleted files (in index but not in current)
        deleted_files = [
            indexed for hash_, indexed in indexed_files.items() if hash_ not in current_hashes
        ]

        return new_files, modified_files, unchanged_files, deleted_files

    def delete_file_chunks(self, file_path_hash: str) -> None:
        """
        Delete all chunks for a file.

        Args:
            file_path_hash: Hash of the file path
        """
        # Delete chunks
        self.client.table("code_chunks").delete().eq("repo_id", self.repo_id).eq(
            "file_path_hash", file_path_hash
        ).execute()

        # Delete from lookup
        self.client.table("file_path_lookup").delete().eq("repo_id", self.repo_id).eq(
            "file_path_hash", file_path_hash
        ).execute()

    def index_file(self, file_info: FileInfo) -> int:
        """
        Index a single file: chunk it and store in database.

        Args:
            file_info: Information about the file to index

        Returns:
            Number of chunks created
        """
        # Chunk the file
        chunks = chunk_code_file(file_info.content, file_info.relative_path)

        if not chunks:
            logger.warning(f"No chunks generated for {file_info.relative_path}")
            return 0

        # Insert into file_path_lookup
        self.client.table("file_path_lookup").upsert(
            {
                "repo_id": self.repo_id,
                "file_path_hash": file_info.path_hash,
                "file_path": file_info.relative_path,
                "file_content_hash": file_info.content_hash,
            },
            on_conflict="repo_id,file_path_hash",
        ).execute()

        # Insert chunks
        chunk_records = []
        for chunk in chunks:
            embedding = generate_mock_embedding()

            chunk_records.append(
                {
                    "repo_id": self.repo_id,
                    "file_path_hash": file_info.path_hash,
                    "chunk_hash": chunk.chunk_hash,
                    "chunk_index": chunk.chunk_index,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "embedding": embedding,
                }
            )

        # Batch insert chunks
        if chunk_records:
            self.client.table("code_chunks").upsert(
                chunk_records,
                on_conflict="repo_id,file_path_hash,chunk_index",
            ).execute()

        return len(chunks)

    def sync(self, repo_path: Path) -> SyncStats:
        """
        Sync the repository to Supabase.

        Args:
            repo_path: Path to the repository root

        Returns:
            SyncStats with counts of processed files
        """
        stats = SyncStats()

        logger.info(f"Discovering Python files in {repo_path}...")
        current_files = discover_python_files(repo_path)
        logger.info(f"Found {len(current_files)} Python files")

        logger.info("Fetching currently indexed files...")
        indexed_files = self.get_indexed_files()
        logger.info(f"Found {len(indexed_files)} indexed files")

        # Categorize files
        new_files, modified_files, unchanged_files, deleted_files = self.categorize_files(
            current_files, indexed_files
        )

        stats.new_files = len(new_files)
        stats.modified_files = len(modified_files)
        stats.unchanged_files = len(unchanged_files)
        stats.deleted_files = len(deleted_files)

        total_to_process = len(new_files) + len(modified_files) + len(deleted_files)
        processed = 0

        # Process deleted files
        for deleted in deleted_files:
            processed += 1
            logger.info(f"Processing file {processed} of {total_to_process}: DELETED {deleted.file_path}")
            try:
                self.delete_file_chunks(deleted.file_path_hash)
            except Exception as e:
                error_msg = f"Failed to delete {deleted.file_path}: {e}"
                logger.error(error_msg)
                stats.errors.append(error_msg)

        # Process modified files (delete old, then index new)
        for file_info in modified_files:
            processed += 1
            logger.info(
                f"Processing file {processed} of {total_to_process}: MODIFIED {file_info.relative_path}"
            )
            try:
                self.delete_file_chunks(file_info.path_hash)
                chunks = self.index_file(file_info)
                stats.total_chunks += chunks
            except Exception as e:
                error_msg = f"Failed to re-index {file_info.relative_path}: {e}"
                logger.error(error_msg)
                stats.errors.append(error_msg)

        # Process new files
        for file_info in new_files:
            processed += 1
            logger.info(f"Processing file {processed} of {total_to_process}: NEW {file_info.relative_path}")
            try:
                chunks = self.index_file(file_info)
                stats.total_chunks += chunks
            except Exception as e:
                error_msg = f"Failed to index {file_info.relative_path}: {e}"
                logger.error(error_msg)
                stats.errors.append(error_msg)

        return stats


def main():
    """Main entry point for the sync script."""
    parser = argparse.ArgumentParser(
        description="Sync a codebase to Supabase for semantic search"
    )
    parser.add_argument(
        "--repo-path",
        type=Path,
        required=True,
        help="Path to the repository to index",
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        required=True,
        help="UUID of the repository in the database",
    )
    args = parser.parse_args()

    # Validate repo path
    if not args.repo_path.exists():
        logger.error(f"Repository path does not exist: {args.repo_path}")
        sys.exit(1)

    if not args.repo_path.is_dir():
        logger.error(f"Repository path is not a directory: {args.repo_path}")
        sys.exit(1)

    # Get Supabase credentials
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        logger.error("SUPABASE_URL and SUPABASE_KEY environment variables must be set")
        logger.error("Copy .env.example to .env and fill in your credentials")
        sys.exit(1)

    # Run the sync
    logger.info(f"Starting sync for repo {args.repo_id}")
    logger.info(f"Repository path: {args.repo_path.absolute()}")

    syncer = CodebaseSync(supabase_url, supabase_key, args.repo_id)
    stats = syncer.sync(args.repo_path)

    # Print summary
    print("\n" + "=" * 50)
    print("SYNC COMPLETE")
    print("=" * 50)
    print(f"  New files:       {stats.new_files}")
    print(f"  Modified files:  {stats.modified_files}")
    print(f"  Deleted files:   {stats.deleted_files}")
    print(f"  Unchanged files: {stats.unchanged_files}")
    print(f"  Total chunks:    {stats.total_chunks}")

    if stats.errors:
        print(f"\n  Errors: {len(stats.errors)}")
        for error in stats.errors:
            print(f"    - {error}")

    print("=" * 50)


if __name__ == "__main__":
    main()
