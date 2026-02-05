"""
GitHub code fetcher - fetches code on-demand from GitHub API.

This module implements the "embeddings + pointers" pattern where we don't
store raw code, but fetch it when needed via the GitHub API.

Rate limits:
- Authenticated: 5000 requests/hour
- Contents API: Returns files up to 1MB
- For larger files: Use Git Blobs API
"""

import base64
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import httpx

logger = logging.getLogger(__name__)


@dataclass
class GitHubFile:
    """Represents a file fetched from GitHub."""
    path: str
    content: str
    sha: str
    size: int
    encoding: str


@dataclass
class GitHubCommit:
    """Represents a commit from GitHub."""
    sha: str
    message: str
    author_name: str
    author_email: str
    date: str
    files_changed: List[str]


class GitHubFetcher:
    """
    Fetches code and metadata from GitHub API.

    Usage:
        fetcher = GitHubFetcher(access_token="ghp_...")

        # Fetch a single file
        file = await fetcher.fetch_file("owner/repo", "src/main.py")
        print(file.content)

        # Fetch all files in a repo
        files = await fetcher.fetch_repo_files("owner/repo")

        # Fetch specific lines (for displaying alongside docs)
        lines = await fetcher.fetch_lines("owner/repo", "src/main.py", 10, 25)
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://api.github.com"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def fetch_file(
        self,
        repo_full_name: str,
        file_path: str,
        ref: Optional[str] = None,
    ) -> Optional[GitHubFile]:
        """
        Fetch a single file from GitHub.

        Args:
            repo_full_name: Owner/repo format (e.g., "anthropics/claude")
            file_path: Path within the repo (e.g., "src/main.py")
            ref: Branch, tag, or commit SHA (default: default branch)

        Returns:
            GitHubFile with content, or None if not found
        """
        client = await self._get_client()

        url = f"/repos/{repo_full_name}/contents/{file_path}"
        params = {"ref": ref} if ref else {}

        try:
            response = await client.get(url, params=params)

            if response.status_code == 404:
                logger.warning(f"File not found: {repo_full_name}/{file_path}")
                return None

            response.raise_for_status()
            data = response.json()

            # Handle case where path is a directory
            if isinstance(data, list):
                logger.warning(f"Path is a directory: {repo_full_name}/{file_path}")
                return None

            # Decode content
            content = ""
            if data.get("encoding") == "base64":
                content = base64.b64decode(data["content"]).decode("utf-8")
            else:
                content = data.get("content", "")

            return GitHubFile(
                path=data["path"],
                content=content,
                sha=data["sha"],
                size=data["size"],
                encoding=data.get("encoding", "none"),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"GitHub API error fetching {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {file_path}: {e}")
            return None

    async def fetch_lines(
        self,
        repo_full_name: str,
        file_path: str,
        start_line: int,
        end_line: int,
        ref: Optional[str] = None,
    ) -> Optional[str]:
        """
        Fetch specific lines from a file.

        Args:
            repo_full_name: Owner/repo format
            file_path: Path within the repo
            start_line: Starting line (1-indexed, inclusive)
            end_line: Ending line (1-indexed, inclusive)
            ref: Branch, tag, or commit SHA

        Returns:
            The requested lines as a string, or None if failed
        """
        file = await self.fetch_file(repo_full_name, file_path, ref)
        if not file:
            return None

        lines = file.content.split("\n")

        # Validate line numbers
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            logger.warning(
                f"Invalid line range {start_line}-{end_line} for file with {len(lines)} lines"
            )
            # Return what we can
            start_line = max(1, start_line)
            end_line = min(len(lines), end_line)

        # Extract lines (convert to 0-indexed)
        return "\n".join(lines[start_line - 1 : end_line])

    async def fetch_repo_tree(
        self,
        repo_full_name: str,
        ref: Optional[str] = None,
        recursive: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetch the file tree of a repository.

        Args:
            repo_full_name: Owner/repo format
            ref: Branch, tag, or commit SHA (default: default branch)
            recursive: Whether to fetch recursively

        Returns:
            List of file/directory entries
        """
        client = await self._get_client()

        # First, get the default branch if ref not specified
        if not ref:
            repo_response = await client.get(f"/repos/{repo_full_name}")
            repo_response.raise_for_status()
            ref = repo_response.json()["default_branch"]

        # Get the tree
        url = f"/repos/{repo_full_name}/git/trees/{ref}"
        params = {"recursive": "1"} if recursive else {}

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return data.get("tree", [])

    async def fetch_repo_files(
        self,
        repo_full_name: str,
        ref: Optional[str] = None,
        file_extensions: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        max_file_size: int = 500_000,  # 500KB default
    ) -> List[GitHubFile]:
        """
        Fetch all code files from a repository.

        Args:
            repo_full_name: Owner/repo format
            ref: Branch, tag, or commit SHA
            file_extensions: Filter by extensions (e.g., [".py", ".js"])
            exclude_paths: Paths to exclude (e.g., ["node_modules", "vendor"])
            max_file_size: Skip files larger than this (bytes)

        Returns:
            List of GitHubFile objects
        """
        # Default code extensions
        if file_extensions is None:
            file_extensions = [
                ".py", ".js", ".ts", ".jsx", ".tsx",
                ".go", ".rs", ".java", ".c", ".cpp", ".h",
                ".rb", ".php", ".swift", ".kt", ".scala",
                ".sql", ".sh", ".bash", ".yaml", ".yml", ".json",
            ]

        # Default exclusions
        if exclude_paths is None:
            exclude_paths = [
                "node_modules", "vendor", "dist", "build", ".git",
                "__pycache__", ".venv", "venv", ".env",
                "coverage", ".pytest_cache", ".mypy_cache",
            ]

        # Get the file tree
        tree = await self.fetch_repo_tree(repo_full_name, ref)

        # Filter to relevant files
        files_to_fetch = []
        for item in tree:
            if item["type"] != "blob":
                continue

            path = item["path"]

            # Check exclusions
            if any(excl in path for excl in exclude_paths):
                continue

            # Check extension
            if not any(path.endswith(ext) for ext in file_extensions):
                continue

            # Check size
            if item.get("size", 0) > max_file_size:
                logger.info(f"Skipping large file: {path} ({item['size']} bytes)")
                continue

            files_to_fetch.append(path)

        logger.info(f"Fetching {len(files_to_fetch)} files from {repo_full_name}")

        # Fetch files (in batches to avoid rate limits)
        files = []
        for path in files_to_fetch:
            file = await self.fetch_file(repo_full_name, path, ref)
            if file:
                files.append(file)

        return files

    async def get_latest_commit(
        self,
        repo_full_name: str,
        ref: Optional[str] = None,
    ) -> Optional[GitHubCommit]:
        """
        Get the latest commit for a repo/branch.

        Args:
            repo_full_name: Owner/repo format
            ref: Branch or tag (default: default branch)

        Returns:
            GitHubCommit or None
        """
        client = await self._get_client()

        url = f"/repos/{repo_full_name}/commits"
        params = {"per_page": 1}
        if ref:
            params["sha"] = ref

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            commit = data[0]
            return GitHubCommit(
                sha=commit["sha"],
                message=commit["commit"]["message"],
                author_name=commit["commit"]["author"]["name"],
                author_email=commit["commit"]["author"]["email"],
                date=commit["commit"]["author"]["date"],
                files_changed=[],  # Would need another API call
            )
        except Exception as e:
            logger.error(f"Error fetching latest commit: {e}")
            return None

    async def get_commit_files(
        self,
        repo_full_name: str,
        commit_sha: str,
    ) -> List[Dict[str, Any]]:
        """
        Get files changed in a specific commit.

        Args:
            repo_full_name: Owner/repo format
            commit_sha: The commit SHA

        Returns:
            List of file change info (filename, status, additions, deletions)
        """
        client = await self._get_client()

        url = f"/repos/{repo_full_name}/commits/{commit_sha}"

        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            return data.get("files", [])
        except Exception as e:
            logger.error(f"Error fetching commit files: {e}")
            return []

    async def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get pull request details including files changed.

        Args:
            repo_full_name: Owner/repo format
            pr_number: PR number

        Returns:
            PR data including title, body, files changed
        """
        client = await self._get_client()

        try:
            # Get PR details
            pr_response = await client.get(
                f"/repos/{repo_full_name}/pulls/{pr_number}"
            )
            pr_response.raise_for_status()
            pr_data = pr_response.json()

            # Get files changed
            files_response = await client.get(
                f"/repos/{repo_full_name}/pulls/{pr_number}/files"
            )
            files_response.raise_for_status()
            files_data = files_response.json()

            return {
                "number": pr_data["number"],
                "title": pr_data["title"],
                "body": pr_data.get("body", ""),
                "state": pr_data["state"],
                "user": pr_data["user"]["login"],
                "base_branch": pr_data["base"]["ref"],
                "head_branch": pr_data["head"]["ref"],
                "merge_commit_sha": pr_data.get("merge_commit_sha"),
                "files": [
                    {
                        "filename": f["filename"],
                        "status": f["status"],
                        "additions": f["additions"],
                        "deletions": f["deletions"],
                    }
                    for f in files_data
                ],
            }
        except Exception as e:
            logger.error(f"Error fetching PR #{pr_number}: {e}")
            return None


# Utility function to get a fetcher from workspace tokens
async def get_fetcher_for_workspace(workspace_id: str) -> Optional[GitHubFetcher]:
    """
    Create a GitHubFetcher using stored workspace tokens.

    Args:
        workspace_id: The workspace UUID

    Returns:
        GitHubFetcher or None if GitHub not connected
    """
    from backend.integrations.auth import get_integration_token

    token = await get_integration_token("github", workspace_id)
    if not token:
        return None

    return GitHubFetcher(token.access_token)
