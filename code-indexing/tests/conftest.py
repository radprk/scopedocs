"""
Pytest Configuration and Fixtures

Shared fixtures for testing the code indexing pipeline.
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, AsyncMock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def temp_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """
    Create a temporary repository with sample Python files.

    Yields:
        Path to the temporary repository
    """
    # Create simple Python files
    (tmp_path / "simple.py").write_text(
        '''"""Simple module."""

def hello():
    """Say hello."""
    return "Hello, World!"

def goodbye():
    """Say goodbye."""
    return "Goodbye!"
'''
    )

    (tmp_path / "with_class.py").write_text(
        '''"""Module with a class."""

class Calculator:
    """A simple calculator."""

    def __init__(self):
        """Initialize the calculator."""
        self.result = 0

    def add(self, x: int, y: int) -> int:
        """Add two numbers."""
        self.result = x + y
        return self.result

    def subtract(self, x: int, y: int) -> int:
        """Subtract y from x."""
        self.result = x - y
        return self.result
'''
    )

    (tmp_path / "empty.py").write_text("")

    (tmp_path / "syntax_error.py").write_text(
        '''"""This file has a syntax error."""

def broken(
    # Missing closing paren and colon
'''
    )

    (tmp_path / "config.py").write_text(
        '''"""Configuration file with no functions."""

DATABASE_URL = "postgresql://localhost/test"
DEBUG = True
MAX_CONNECTIONS = 10

SETTINGS = {
    "timeout": 30,
    "retries": 3,
}
'''
    )

    yield tmp_path


@pytest.fixture
def sample_code() -> str:
    """Return sample Python code for testing."""
    return '''"""Sample module for testing."""

import os
from typing import Optional


def first_function(x: int) -> int:
    """First function."""
    return x * 2


def second_function(y: str) -> str:
    """Second function."""
    return y.upper()


class SampleClass:
    """A sample class."""

    def __init__(self, value: int):
        """Initialize with a value."""
        self.value = value

    def get_value(self) -> int:
        """Return the value."""
        return self.value

    def set_value(self, new_value: int) -> None:
        """Set a new value."""
        self.value = new_value
'''


@pytest.fixture
def repo_id() -> str:
    """Return a test repository UUID."""
    return str(uuid.uuid4())


@pytest.fixture
def mock_supabase_client() -> MagicMock:
    """
    Create a mock Supabase client for testing.

    Returns:
        MagicMock configured to simulate Supabase responses
    """
    client = MagicMock()

    # Mock table method to return a chainable query builder
    def create_table_mock(table_name: str):
        table = MagicMock()

        # Store data for simulation
        table._data = []

        def select_mock(*args, **kwargs):
            query = MagicMock()

            def eq_mock(column, value):
                eq_query = MagicMock()

                def execute_mock():
                    result = MagicMock()
                    # Filter data based on conditions
                    result.data = [
                        row for row in table._data
                        if row.get(column) == value
                    ]
                    return result

                eq_query.execute = execute_mock
                eq_query.eq = eq_mock  # Allow chaining
                return eq_query

            query.eq = eq_mock
            query.execute = lambda: MagicMock(data=table._data)
            return query

        def upsert_mock(data, **kwargs):
            upsert_query = MagicMock()
            if isinstance(data, list):
                table._data.extend(data)
            else:
                table._data.append(data)
            upsert_query.execute = lambda: MagicMock(data=[data] if not isinstance(data, list) else data)
            return upsert_query

        def delete_mock():
            delete_query = MagicMock()

            def eq_mock(column, value):
                eq_query = MagicMock()

                def inner_eq(col2, val2):
                    final_query = MagicMock()
                    final_query.execute = lambda: MagicMock(data=[])
                    return final_query

                eq_query.eq = inner_eq
                eq_query.execute = lambda: MagicMock(data=[])
                return eq_query

            delete_query.eq = eq_mock
            return delete_query

        table.select = select_mock
        table.upsert = upsert_mock
        table.delete = delete_mock

        return table

    client.table = create_table_mock
    return client


@pytest.fixture
def mock_supabase_with_data(mock_supabase_client: MagicMock, repo_id: str) -> MagicMock:
    """
    Create a mock Supabase client with pre-populated data.

    Args:
        mock_supabase_client: Base mock client
        repo_id: Repository UUID

    Returns:
        Mock client with sample file_path_lookup data
    """
    # Add sample data to file_path_lookup
    lookup_table = mock_supabase_client.table("file_path_lookup")
    lookup_table._data = [
        {
            "repo_id": repo_id,
            "file_path_hash": "abc123hash",
            "file_path": "src/sample.py",
            "file_content_hash": "content123",
        },
        {
            "repo_id": repo_id,
            "file_path_hash": "def456hash",
            "file_path": "src/utils.py",
            "file_content_hash": "content456",
        },
    ]

    return mock_supabase_client
