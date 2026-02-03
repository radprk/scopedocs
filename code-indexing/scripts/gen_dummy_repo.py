#!/usr/bin/env python3
"""
Synthetic Test Data Generator for Code Indexing Pipeline

Generates a dummy_repo/ directory with realistic Python files for testing
the AST-aware chunker. Each file contains syntactically valid Python code
with functions, classes, docstrings, and realistic logic.

Usage:
    python scripts/gen_dummy_repo.py [--output-dir ./dummy_repo]
"""

import argparse
import os
from pathlib import Path

from faker import Faker

fake = Faker()
Faker.seed(42)  # For reproducible output


def generate_auth_py() -> str:
    """Generate auth.py - User authentication functions."""
    return '''"""
User Authentication Module

Provides functions for user authentication, password hashing,
and session management.
"""

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """Represents an authenticated user."""
    id: str
    username: str
    email: str
    created_at: float
    is_active: bool = True


@dataclass
class Session:
    """Represents a user session."""
    token: str
    user_id: str
    expires_at: float
    created_at: float


# In-memory storage for demo purposes
_users: dict[str, User] = {}
_sessions: dict[str, Session] = {}


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """
    Hash a password using SHA-256 with a salt.

    Args:
        password: The plaintext password to hash
        salt: Optional salt; if not provided, one will be generated

    Returns:
        Tuple of (hashed_password, salt)
    """
    if salt is None:
        salt = secrets.token_hex(16)

    salted_password = f"{salt}{password}"
    hashed = hashlib.sha256(salted_password.encode()).hexdigest()

    return hashed, salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        password: The plaintext password to verify
        hashed: The stored hash to compare against
        salt: The salt used when hashing

    Returns:
        True if password matches, False otherwise
    """
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, hashed)


def create_user(username: str, email: str, password: str) -> User:
    """
    Create a new user account.

    Args:
        username: Unique username for the account
        email: User's email address
        password: Plaintext password (will be hashed)

    Returns:
        The newly created User object

    Raises:
        ValueError: If username already exists
    """
    if username in _users:
        raise ValueError(f"Username '{username}' already exists")

    user_id = secrets.token_urlsafe(16)
    hashed_pw, salt = hash_password(password)

    user = User(
        id=user_id,
        username=username,
        email=email,
        created_at=time.time(),
    )

    _users[username] = user
    return user


def create_session(user: User, ttl_seconds: int = 3600) -> Session:
    """
    Create a new session for a user.

    Args:
        user: The user to create a session for
        ttl_seconds: Session lifetime in seconds (default: 1 hour)

    Returns:
        A new Session object with a unique token
    """
    token = secrets.token_urlsafe(32)
    now = time.time()

    session = Session(
        token=token,
        user_id=user.id,
        expires_at=now + ttl_seconds,
        created_at=now,
    )

    _sessions[token] = session
    return session


def validate_session(token: str) -> Optional[User]:
    """
    Validate a session token and return the associated user.

    Args:
        token: The session token to validate

    Returns:
        The User if session is valid, None otherwise
    """
    session = _sessions.get(token)

    if session is None:
        return None

    if time.time() > session.expires_at:
        del _sessions[token]
        return None

    for user in _users.values():
        if user.id == session.user_id:
            return user

    return None
'''


def generate_database_py() -> str:
    """Generate database.py - Database connection and queries."""
    return '''"""
Database Connection Module

Provides async database connection pooling and query execution
for PostgreSQL databases.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConnectionConfig:
    """Database connection configuration."""
    host: str = "localhost"
    port: int = 5432
    database: str = "app_db"
    user: str = "postgres"
    password: str = ""
    min_connections: int = 2
    max_connections: int = 10


@dataclass
class QueryResult:
    """Result of a database query."""
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    duration_ms: float = 0.0


class ConnectionPool:
    """
    Async connection pool for PostgreSQL.

    Manages a pool of database connections for efficient
    concurrent query execution.
    """

    def __init__(self, config: ConnectionConfig):
        """
        Initialize the connection pool.

        Args:
            config: Database connection configuration
        """
        self.config = config
        self._pool: list[Any] = []
        self._available: asyncio.Queue = asyncio.Queue()
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize the connection pool.

        Creates the minimum number of connections specified in config.
        """
        if self._initialized:
            return

        logger.info(
            f"Initializing connection pool: {self.config.min_connections} "
            f"to {self.config.max_connections} connections"
        )

        for _ in range(self.config.min_connections):
            conn = await self._create_connection()
            self._pool.append(conn)
            await self._available.put(conn)

        self._initialized = True

    async def _create_connection(self) -> dict:
        """Create a new database connection (mock implementation)."""
        await asyncio.sleep(0.01)  # Simulate connection time
        return {
            "host": self.config.host,
            "port": self.config.port,
            "database": self.config.database,
            "connected": True,
        }

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[dict, None]:
        """
        Acquire a connection from the pool.

        Yields:
            A database connection

        Example:
            async with pool.acquire() as conn:
                result = await execute_query(conn, "SELECT 1")
        """
        if not self._initialized:
            await self.initialize()

        conn = await self._available.get()
        try:
            yield conn
        finally:
            await self._available.put(conn)

    async def close(self) -> None:
        """Close all connections in the pool."""
        logger.info("Closing connection pool")
        self._initialized = False
        self._pool.clear()


async def execute_query(
    pool: ConnectionPool,
    query: str,
    params: Optional[tuple] = None,
) -> QueryResult:
    """
    Execute a database query.

    Args:
        pool: The connection pool to use
        query: SQL query string
        params: Optional query parameters

    Returns:
        QueryResult with rows and metadata
    """
    import time

    start = time.perf_counter()

    async with pool.acquire() as conn:
        # Mock query execution
        await asyncio.sleep(0.005)

        # Simulate different query types
        if query.strip().upper().startswith("SELECT"):
            rows = [{"id": 1, "name": "example"}]
            row_count = len(rows)
        else:
            rows = []
            row_count = 1

    duration_ms = (time.perf_counter() - start) * 1000

    logger.debug(f"Query executed in {duration_ms:.2f}ms: {query[:50]}...")

    return QueryResult(rows=rows, row_count=row_count, duration_ms=duration_ms)


async def execute_many(
    pool: ConnectionPool,
    query: str,
    params_list: list[tuple],
) -> int:
    """
    Execute a query multiple times with different parameters.

    Args:
        pool: The connection pool to use
        query: SQL query string with placeholders
        params_list: List of parameter tuples

    Returns:
        Total number of affected rows
    """
    total_rows = 0

    async with pool.acquire() as conn:
        for params in params_list:
            await asyncio.sleep(0.001)  # Simulate execution
            total_rows += 1

    logger.info(f"Executed batch query {len(params_list)} times")
    return total_rows
'''


def generate_api_client_py() -> str:
    """Generate api_client.py - External API integration."""
    return '''"""
External API Client Module

Provides HTTP client functionality for interacting with external APIs
with built-in retry logic, rate limiting, and error handling.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class HttpMethod(Enum):
    """HTTP request methods."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class ApiResponse:
    """Response from an API call."""
    status_code: int
    data: Optional[dict[str, Any]]
    headers: dict[str, str]
    elapsed_ms: float


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    exponential_base: float = 2.0


class RateLimiter:
    """
    Token bucket rate limiter.

    Limits the rate of API calls to avoid hitting rate limits.
    """

    def __init__(self, requests_per_second: float = 10.0):
        """
        Initialize the rate limiter.

        Args:
            requests_per_second: Maximum requests allowed per second
        """
        self.requests_per_second = requests_per_second
        self.tokens = requests_per_second
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Acquire a token, waiting if necessary.

        This method blocks until a token is available.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(
                self.requests_per_second,
                self.tokens + elapsed * self.requests_per_second
            )
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.requests_per_second
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class ApiClient:
    """
    Async HTTP client for external API calls.

    Features:
    - Automatic retry with exponential backoff
    - Rate limiting
    - Request/response logging
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None,
        rate_limit: float = 10.0,
    ):
        """
        Initialize the API client.

        Args:
            base_url: Base URL for all API requests
            api_key: Optional API key for authentication
            retry_config: Configuration for retry behavior
            rate_limit: Maximum requests per second
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.retry_config = retry_config or RetryConfig()
        self.rate_limiter = RateLimiter(rate_limit)

    def _build_headers(self, extra_headers: Optional[dict] = None) -> dict[str, str]:
        """Build request headers including authentication."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if extra_headers:
            headers.update(extra_headers)

        return headers

    async def _make_request(
        self,
        method: HttpMethod,
        endpoint: str,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> ApiResponse:
        """Make a single HTTP request (mock implementation)."""
        await asyncio.sleep(0.05)  # Simulate network latency

        # Mock response
        return ApiResponse(
            status_code=200,
            data={"success": True, "endpoint": endpoint},
            headers={"x-request-id": "mock-123"},
            elapsed_ms=50.0,
        )

    async def request(
        self,
        method: HttpMethod,
        endpoint: str,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> ApiResponse:
        """
        Make an API request with retry logic.

        Args:
            method: HTTP method to use
            endpoint: API endpoint (will be appended to base_url)
            data: Optional request body data
            headers: Optional extra headers

        Returns:
            ApiResponse with status, data, and metadata

        Raises:
            Exception: If all retries are exhausted
        """
        await self.rate_limiter.acquire()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        all_headers = self._build_headers(headers)

        last_error = None
        delay = self.retry_config.base_delay_seconds

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                logger.debug(f"API request attempt {attempt + 1}: {method.value} {url}")

                response = await self._make_request(method, endpoint, data, all_headers)

                if response.status_code < 500:
                    return response

                logger.warning(f"Server error {response.status_code}, will retry")

            except Exception as e:
                last_error = e
                logger.warning(f"Request failed: {e}")

            if attempt < self.retry_config.max_retries:
                await asyncio.sleep(delay)
                delay = min(
                    delay * self.retry_config.exponential_base,
                    self.retry_config.max_delay_seconds,
                )

        raise Exception(f"All retries exhausted. Last error: {last_error}")

    async def get(self, endpoint: str, **kwargs) -> ApiResponse:
        """Make a GET request."""
        return await self.request(HttpMethod.GET, endpoint, **kwargs)

    async def post(self, endpoint: str, data: dict, **kwargs) -> ApiResponse:
        """Make a POST request."""
        return await self.request(HttpMethod.POST, endpoint, data=data, **kwargs)
'''


def generate_utils_py() -> str:
    """Generate utils.py - Helper functions."""
    return '''"""
Utility Functions Module

Common helper functions used throughout the application.
"""

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional, TypeVar

T = TypeVar("T")


def slugify(text: str, max_length: int = 50) -> str:
    """
    Convert text to a URL-friendly slug.

    Args:
        text: The text to convert
        max_length: Maximum length of the resulting slug

    Returns:
        A lowercase, hyphenated string safe for URLs

    Examples:
        >>> slugify("Hello World!")
        'hello-world'
        >>> slugify("Café au Lait")
        'cafe-au-lait'
    """
    # Normalize unicode characters
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Convert to lowercase and replace spaces
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)

    return text[:max_length].rstrip("-")


def compute_hash(content: str | bytes, algorithm: str = "sha256") -> str:
    """
    Compute a hash of the given content.

    Args:
        content: String or bytes to hash
        algorithm: Hash algorithm to use (default: sha256)

    Returns:
        Hexadecimal hash string
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    hasher = hashlib.new(algorithm)
    hasher.update(content)
    return hasher.hexdigest()


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length.

    Args:
        text: The string to truncate
        max_length: Maximum length including suffix
        suffix: String to append when truncated

    Returns:
        Truncated string with suffix if needed
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


def parse_iso_datetime(date_string: str) -> datetime:
    """
    Parse an ISO 8601 datetime string.

    Args:
        date_string: ISO format datetime string

    Returns:
        datetime object in UTC

    Raises:
        ValueError: If the string cannot be parsed
    """
    # Handle common ISO formats
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_string, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    raise ValueError(f"Cannot parse datetime: {date_string}")


def deep_get(data: dict, path: str, default: Any = None) -> Any:
    """
    Get a nested value from a dictionary using dot notation.

    Args:
        data: The dictionary to search
        path: Dot-separated path to the value (e.g., "user.profile.name")
        default: Value to return if path not found

    Returns:
        The value at the path, or default if not found

    Examples:
        >>> data = {"user": {"profile": {"name": "Alice"}}}
        >>> deep_get(data, "user.profile.name")
        'Alice'
        >>> deep_get(data, "user.missing", "default")
        'default'
    """
    keys = path.split(".")
    result = data

    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return default

    return result


def chunk_list(items: list[T], chunk_size: int) -> list[list[T]]:
    """
    Split a list into chunks of specified size.

    Args:
        items: The list to split
        chunk_size: Maximum size of each chunk

    Returns:
        List of chunks

    Examples:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def format_bytes(num_bytes: int) -> str:
    """
    Format a byte count as a human-readable string.

    Args:
        num_bytes: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024

    return f"{num_bytes:.1f} PB"


def safe_int(value: Any, default: int = 0) -> int:
    """
    Safely convert a value to an integer.

    Args:
        value: The value to convert
        default: Default value if conversion fails

    Returns:
        Integer value or default
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def merge_dicts(base: dict, override: dict) -> dict:
    """
    Deep merge two dictionaries.

    Values in override take precedence. Nested dicts are merged recursively.

    Args:
        base: Base dictionary
        override: Dictionary with values to override

    Returns:
        New merged dictionary
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value

    return result
'''


def generate_models_py() -> str:
    """Generate models.py - Data classes/models."""
    return '''"""
Data Models Module

Defines the core data structures used throughout the application.
Uses dataclasses for clean, type-safe data modeling.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4


class Status(Enum):
    """Status values for various entities."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Priority(Enum):
    """Priority levels for tasks and issues."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class BaseModel:
    """Base model with common fields."""
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, UUID):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result


@dataclass
class Project(BaseModel):
    """Represents a project or repository."""
    name: str = ""
    description: str = ""
    owner_id: UUID = field(default_factory=uuid4)
    is_public: bool = False
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Get a display-friendly name."""
        return self.name.replace("-", " ").replace("_", " ").title()


@dataclass
class Task(BaseModel):
    """Represents a task or work item."""
    title: str = ""
    description: str = ""
    project_id: UUID = field(default_factory=uuid4)
    assignee_id: Optional[UUID] = None
    status: Status = Status.PENDING
    priority: Priority = Priority.MEDIUM
    due_date: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)

    def is_overdue(self) -> bool:
        """Check if the task is past its due date."""
        if self.due_date is None:
            return False
        return datetime.utcnow() > self.due_date and self.status != Status.COMPLETED


@dataclass
class Comment(BaseModel):
    """Represents a comment on a task or document."""
    content: str = ""
    author_id: UUID = field(default_factory=uuid4)
    parent_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    mentions: list[UUID] = field(default_factory=list)

    @property
    def is_reply(self) -> bool:
        """Check if this comment is a reply to another."""
        return self.parent_id is not None


@dataclass
class Notification(BaseModel):
    """Represents a user notification."""
    user_id: UUID = field(default_factory=uuid4)
    title: str = ""
    message: str = ""
    is_read: bool = False
    notification_type: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_as_read(self) -> None:
        """Mark the notification as read."""
        self.is_read = True
        self.updated_at = datetime.utcnow()


@dataclass
class AuditLog(BaseModel):
    """Represents an audit log entry."""
    user_id: UUID = field(default_factory=uuid4)
    action: str = ""
    resource_type: str = ""
    resource_id: UUID = field(default_factory=uuid4)
    changes: dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None

    def describe(self) -> str:
        """Generate a human-readable description of the action."""
        return f"{self.action} on {self.resource_type} ({self.resource_id})"


class ModelRegistry:
    """Registry for tracking and validating models."""

    _models: dict[str, type] = {}

    @classmethod
    def register(cls, model_class: type) -> type:
        """Register a model class."""
        cls._models[model_class.__name__] = model_class
        return model_class

    @classmethod
    def get(cls, name: str) -> Optional[type]:
        """Get a registered model by name."""
        return cls._models.get(name)

    @classmethod
    def all_models(cls) -> list[type]:
        """Get all registered models."""
        return list(cls._models.values())


# Register all models
for model in [Project, Task, Comment, Notification, AuditLog]:
    ModelRegistry.register(model)
'''


def main():
    """Generate the dummy repository with realistic Python files."""
    parser = argparse.ArgumentParser(
        description="Generate a dummy repository for testing the code indexer"
    )
    parser.add_argument(
        "--output-dir",
        default="dummy_repo",
        help="Output directory for generated files (default: dummy_repo)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "auth.py": generate_auth_py(),
        "database.py": generate_database_py(),
        "api_client.py": generate_api_client_py(),
        "utils.py": generate_utils_py(),
        "models.py": generate_models_py(),
    }

    print(f"Generating dummy repository in: {output_dir.absolute()}")
    print("-" * 50)

    total_lines = 0
    total_functions = 0
    total_classes = 0

    for filename, content in files.items():
        filepath = output_dir / filename
        filepath.write_text(content)

        # Count statistics
        lines = len(content.splitlines())
        functions = content.count("\ndef ") + content.count("\n    def ")
        classes = content.count("\nclass ")

        total_lines += lines
        total_functions += functions
        total_classes += classes

        print(f"  Created: {filename}")
        print(f"    - Lines: {lines}")
        print(f"    - Functions: {functions}")
        print(f"    - Classes: {classes}")

    print("-" * 50)
    print(f"Summary:")
    print(f"  - Total files: {len(files)}")
    print(f"  - Total lines: {total_lines}")
    print(f"  - Total functions: {total_functions}")
    print(f"  - Total classes: {total_classes}")
    print(f"\nDummy repository generated successfully!")


if __name__ == "__main__":
    main()
