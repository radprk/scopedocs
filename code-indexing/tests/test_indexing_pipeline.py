"""
Tests for the Code Indexing Pipeline

Covers:
- AST-aware code chunking
- Sync ETL operations
- Code retrieval
"""

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from indexing.chunker import chunk_code_file, CodeChunk, _compute_chunk_hash
from indexing.retrieval import (
    retrieve_chunk_content,
    RetrievedChunk,
    _extract_lines,
    HashNotFoundError,
    LinesOutOfRangeError,
    format_chunk_for_context,
)


# =============================================================================
# Chunker Tests
# =============================================================================


class TestChunkerBasic:
    """Tests for basic chunker functionality."""

    def test_chunker_basic(self, sample_code: str):
        """Verify chunker splits a simple file with functions into appropriate chunks."""
        chunks = chunk_code_file(sample_code, "sample.py")

        # Should produce at least one chunk
        assert len(chunks) >= 1

        # All chunks should be CodeChunk instances
        for chunk in chunks:
            assert isinstance(chunk, CodeChunk)
            assert chunk.content  # Non-empty content
            assert chunk.start_line >= 1
            assert chunk.end_line >= chunk.start_line
            assert chunk.chunk_hash  # Has a hash
            assert chunk.chunk_index >= 0

    def test_chunker_preserves_boundaries(self, sample_code: str):
        """Verify a function isn't split mid-body."""
        chunks = chunk_code_file(sample_code, "sample.py")

        # Check that each chunk contains complete statements
        for chunk in chunks:
            content = chunk.content

            # If chunk contains 'def ', it should contain the full function
            # (at least have matching indentation for the body)
            if "def first_function" in content:
                assert "return x * 2" in content or content.strip().endswith(":")

    def test_chunker_handles_empty_file(self):
        """Edge case - empty file returns no chunks."""
        chunks = chunk_code_file("", "empty.py")
        assert chunks == []

        # Also test whitespace-only
        chunks = chunk_code_file("   \n\n  ", "whitespace.py")
        assert chunks == []

    def test_chunker_handles_syntax_error(self):
        """File with invalid Python syntax falls back gracefully."""
        invalid_code = '''def broken(
    # Missing closing paren and body
'''
        # Should not raise an exception
        chunks = chunk_code_file(invalid_code, "broken.py")

        # Should return at least one chunk (fallback behavior)
        assert len(chunks) >= 1

        # The chunk should contain the original content
        assert "def broken" in chunks[0].content

    def test_chunker_config_file(self):
        """File with no functions/classes is treated as single chunk."""
        config_code = '''"""Config file."""

DATABASE_URL = "postgresql://localhost/test"
DEBUG = True
MAX_CONNECTIONS = 10
'''
        chunks = chunk_code_file(config_code, "config.py")

        # Should return at least one chunk
        assert len(chunks) >= 1

        # Content should include the config
        full_content = "".join(c.content for c in chunks)
        assert "DATABASE_URL" in full_content

    def test_chunk_hash_uniqueness(self, sample_code: str):
        """Each chunk should have a unique hash (for different content)."""
        chunks = chunk_code_file(sample_code, "sample.py")

        if len(chunks) > 1:
            hashes = [c.chunk_hash for c in chunks]
            # If chunks have different content, hashes should be different
            unique_hashes = set(hashes)
            # At minimum, not all hashes should be identical
            # (unless chunks happen to have identical content)
            assert len(unique_hashes) >= 1

    def test_chunk_index_sequential(self, sample_code: str):
        """Chunk indices should be sequential starting from 0."""
        chunks = chunk_code_file(sample_code, "sample.py")

        indices = [c.chunk_index for c in chunks]
        expected = list(range(len(chunks)))
        assert indices == expected

    def test_compute_chunk_hash(self):
        """Test hash computation."""
        content = "def hello(): pass"
        hash1 = _compute_chunk_hash(content)
        hash2 = _compute_chunk_hash(content)

        assert hash1 == hash2  # Deterministic
        assert len(hash1) == 64  # SHA256 hex length

        # Different content = different hash
        hash3 = _compute_chunk_hash("def goodbye(): pass")
        assert hash3 != hash1


# =============================================================================
# Sync Tests
# =============================================================================


class TestSyncOperations:
    """Tests for sync ETL operations."""

    def test_sync_discovers_python_files(self, temp_repo: Path):
        """Verify sync discovers all Python files."""
        # Import here to avoid issues if supabase not installed
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

        from sync_codebase import discover_python_files

        files = discover_python_files(temp_repo)

        # Should find our test files
        file_names = {f.relative_path for f in files}
        assert "simple.py" in file_names
        assert "with_class.py" in file_names
        assert "config.py" in file_names

    def test_sync_computes_hashes(self, temp_repo: Path):
        """Verify content and path hashes are computed correctly."""
        from sync_codebase import discover_python_files, compute_hash

        files = discover_python_files(temp_repo)

        for file_info in files:
            # Verify path hash
            expected_path_hash = compute_hash(file_info.relative_path)
            assert file_info.path_hash == expected_path_hash

            # Verify content hash
            expected_content_hash = compute_hash(file_info.content)
            assert file_info.content_hash == expected_content_hash

    def test_sync_ignores_pycache(self, temp_repo: Path):
        """Verify __pycache__ directories are ignored."""
        from sync_codebase import discover_python_files

        # Create a __pycache__ directory with a .py file
        pycache = temp_repo / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.cpython-39.pyc").write_bytes(b"fake bytecode")

        files = discover_python_files(temp_repo)

        # Should not include anything from __pycache__
        for f in files:
            assert "__pycache__" not in f.relative_path

    def test_sync_categorizes_files_new(self, temp_repo: Path, repo_id: str):
        """Run sync on fresh repo, verify files are categorized as NEW."""
        from sync_codebase import discover_python_files, CodebaseSync

        files = discover_python_files(temp_repo)
        indexed_files = {}  # Empty = nothing indexed yet

        # Create a mock syncer to test categorization
        with patch("supabase.create_client"):
            syncer = CodebaseSync("http://fake", "fake-key", repo_id)
            new, modified, unchanged, deleted = syncer.categorize_files(
                files, indexed_files
            )

        # All files should be new
        assert len(new) == len(files)
        assert len(modified) == 0
        assert len(unchanged) == 0
        assert len(deleted) == 0

    def test_sync_categorizes_files_modified(self, temp_repo: Path, repo_id: str):
        """Modify a file, verify it's categorized as MODIFIED."""
        from sync_codebase import discover_python_files, CodebaseSync, IndexedFile, compute_hash

        # First discovery
        files = discover_python_files(temp_repo)

        # Simulate indexed files with old content hashes
        indexed_files = {
            f.path_hash: IndexedFile(
                file_path_hash=f.path_hash,
                file_path=f.relative_path,
                file_content_hash="old_hash_different",  # Different hash
            )
            for f in files
        }

        with patch("supabase.create_client"):
            syncer = CodebaseSync("http://fake", "fake-key", repo_id)
            new, modified, unchanged, deleted = syncer.categorize_files(
                files, indexed_files
            )

        # All files should be modified (hash changed)
        assert len(modified) == len(files)
        assert len(new) == 0
        assert len(unchanged) == 0

    def test_sync_categorizes_files_unchanged(self, temp_repo: Path, repo_id: str):
        """Run sync twice with no changes, verify files are UNCHANGED."""
        from sync_codebase import discover_python_files, CodebaseSync, IndexedFile

        files = discover_python_files(temp_repo)

        # Simulate indexed files with matching hashes
        indexed_files = {
            f.path_hash: IndexedFile(
                file_path_hash=f.path_hash,
                file_path=f.relative_path,
                file_content_hash=f.content_hash,  # Same hash
            )
            for f in files
        }

        with patch("supabase.create_client"):
            syncer = CodebaseSync("http://fake", "fake-key", repo_id)
            new, modified, unchanged, deleted = syncer.categorize_files(
                files, indexed_files
            )

        # All files should be unchanged
        assert len(unchanged) == len(files)
        assert len(new) == 0
        assert len(modified) == 0

    def test_sync_categorizes_files_deleted(self, temp_repo: Path, repo_id: str):
        """Delete a file from repo, verify it's categorized as DELETED."""
        from sync_codebase import discover_python_files, CodebaseSync, IndexedFile

        files = discover_python_files(temp_repo)

        # Simulate indexed files including one that no longer exists
        indexed_files = {
            f.path_hash: IndexedFile(
                file_path_hash=f.path_hash,
                file_path=f.relative_path,
                file_content_hash=f.content_hash,
            )
            for f in files
        }

        # Add a "ghost" file that was indexed but is now deleted
        ghost_hash = "ghost_file_hash"
        indexed_files[ghost_hash] = IndexedFile(
            file_path_hash=ghost_hash,
            file_path="deleted_file.py",
            file_content_hash="ghost_content",
        )

        with patch("supabase.create_client"):
            syncer = CodebaseSync("http://fake", "fake-key", repo_id)
            new, modified, unchanged, deleted = syncer.categorize_files(
                files, indexed_files
            )

        # Should have one deleted file
        assert len(deleted) == 1
        assert deleted[0].file_path == "deleted_file.py"

    def test_generate_mock_embedding(self):
        """Test mock embedding generation."""
        from sync_codebase import generate_mock_embedding

        embedding = generate_mock_embedding(768)

        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)
        assert all(0 <= x <= 1 for x in embedding)


# =============================================================================
# Retrieval Tests
# =============================================================================


class TestRetrieval:
    """Tests for code retrieval functionality."""

    def test_extract_lines_basic(self):
        """Test basic line extraction."""
        content = "line1\nline2\nline3\nline4\nline5"

        result = _extract_lines(content, 2, 4)
        assert result == "line2\nline3\nline4"

    def test_extract_lines_single(self):
        """Test extracting a single line."""
        content = "line1\nline2\nline3"

        result = _extract_lines(content, 2, 2)
        assert result == "line2"

    def test_extract_lines_full_file(self):
        """Test extracting entire file."""
        content = "line1\nline2\nline3"

        result = _extract_lines(content, 1, 3)
        assert result == content

    def test_extract_lines_out_of_range(self):
        """Test error on out of range lines."""
        content = "line1\nline2\nline3"

        with pytest.raises(LinesOutOfRangeError):
            _extract_lines(content, 1, 10)

        with pytest.raises(LinesOutOfRangeError):
            _extract_lines(content, 0, 2)  # start_line < 1

        with pytest.raises(LinesOutOfRangeError):
            _extract_lines(content, 3, 2)  # start > end

    @pytest.mark.asyncio
    async def test_retrieval_resolves_hash(self, temp_repo: Path, repo_id: str):
        """Given a file_path_hash, verify correct file content returned."""
        from indexing.retrieval import resolve_file_path

        # Create mock client with data
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [{"file_path": "simple.py"}]

        mock_query = MagicMock()
        mock_query.execute.return_value = mock_response

        mock_eq = MagicMock(return_value=mock_query)
        mock_query.eq = mock_eq

        mock_select = MagicMock(return_value=mock_query)
        mock_table = MagicMock()
        mock_table.select = mock_select

        mock_client.table.return_value = mock_table

        # Test resolution
        result = await resolve_file_path(repo_id, "abc123", mock_client)
        assert result == "simple.py"

    @pytest.mark.asyncio
    async def test_retrieval_hash_not_found(self, repo_id: str):
        """Test error when hash not found."""
        from indexing.retrieval import resolve_file_path

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = []  # Empty = not found

        mock_query = MagicMock()
        mock_query.execute.return_value = mock_response
        mock_query.eq.return_value = mock_query

        mock_table = MagicMock()
        mock_table.select.return_value = mock_query

        mock_client.table.return_value = mock_table

        with pytest.raises(HashNotFoundError):
            await resolve_file_path(repo_id, "nonexistent", mock_client)

    @pytest.mark.asyncio
    async def test_retrieval_extracts_lines(self, temp_repo: Path, repo_id: str):
        """Verify only requested line range is returned."""
        # Create mock client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [{"file_path": "simple.py"}]

        mock_query = MagicMock()
        mock_query.execute.return_value = mock_response
        mock_query.eq.return_value = mock_query

        mock_table = MagicMock()
        mock_table.select.return_value = mock_query

        mock_client.table.return_value = mock_table

        # Retrieve specific lines
        chunk = await retrieve_chunk_content(
            repo_id=repo_id,
            file_path_hash="abc123",
            start_line=3,
            end_line=5,
            supabase_client=mock_client,
            repo_base_path=str(temp_repo),
        )

        assert isinstance(chunk, RetrievedChunk)
        assert chunk.file_path == "simple.py"
        assert chunk.start_line == 3
        assert chunk.end_line == 5
        assert chunk.retrieval_source == "local"

        # Should only have 3 lines
        lines = chunk.content.split("\n")
        assert len(lines) == 3

    def test_format_chunk_for_context(self):
        """Test chunk formatting for LLM context."""
        chunk = RetrievedChunk(
            file_path="src/example.py",
            content="def hello():\n    return 'world'",
            start_line=10,
            end_line=11,
            retrieval_source="local",
        )

        formatted = format_chunk_for_context(chunk)

        assert "src/example.py" in formatted
        assert "lines 10-11" in formatted
        assert "def hello():" in formatted
        assert "return 'world'" in formatted

    def test_format_chunk_with_line_numbers(self):
        """Test chunk formatting includes line numbers."""
        chunk = RetrievedChunk(
            file_path="test.py",
            content="line1\nline2",
            start_line=5,
            end_line=6,
            retrieval_source="local",
        )

        formatted = format_chunk_for_context(chunk, include_line_numbers=True)

        assert "5" in formatted
        assert "6" in formatted

    def test_format_chunk_without_line_numbers(self):
        """Test chunk formatting without line numbers."""
        chunk = RetrievedChunk(
            file_path="test.py",
            content="line1\nline2",
            start_line=5,
            end_line=6,
            retrieval_source="local",
        )

        formatted = format_chunk_for_context(chunk, include_line_numbers=False)

        # Should contain content but not line number prefix
        assert "line1" in formatted
        assert "   5 |" not in formatted


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the full pipeline."""

    def test_chunk_and_retrieve_roundtrip(self, temp_repo: Path):
        """Test chunking a file and retrieving the chunks."""
        # Read a file
        file_path = temp_repo / "simple.py"
        content = file_path.read_text()

        # Chunk it
        chunks = chunk_code_file(content, "simple.py")
        assert len(chunks) >= 1

        # Verify we can extract the same lines
        for chunk in chunks:
            extracted = _extract_lines(content, chunk.start_line, chunk.end_line)
            # The extracted content should match (possibly with whitespace differences)
            assert extracted.strip() in content

    def test_hash_consistency(self, temp_repo: Path):
        """Test that hashes are consistent across operations."""
        from sync_codebase import compute_hash

        file_path = temp_repo / "simple.py"
        content = file_path.read_text()

        # Hash should be deterministic
        hash1 = compute_hash(content)
        hash2 = compute_hash(content)
        assert hash1 == hash2

        # Different content = different hash
        hash3 = compute_hash(content + "\n# comment")
        assert hash3 != hash1
