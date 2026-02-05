"""
Traceability extractor - links Linear issues ↔ GitHub PRs ↔ Code.

This module extracts relationships between:
- Linear issues and GitHub PRs (via ticket references in PR titles/bodies)
- GitHub PRs and code files (via files changed in PR)
- Slack messages and code (via file path mentions)

The traceability graph enables queries like:
- "What ticket led to this code change?"
- "What code was modified for this feature?"
- "What discussions happened about this file?"
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set, Tuple
from enum import Enum
import asyncpg

logger = logging.getLogger(__name__)


class LinkType(str, Enum):
    """Types of traceability links."""
    IMPLEMENTS = "implements"      # PR implements a Linear issue
    MODIFIES = "modifies"          # PR modifies code files
    DISCUSSES = "discusses"        # Slack message discusses code/ticket
    MENTIONS = "mentions"          # Generic mention
    FIXES = "fixes"                # PR fixes an issue
    CLOSES = "closes"              # PR closes an issue


class ArtifactType(str, Enum):
    """Types of artifacts that can be linked."""
    LINEAR_ISSUE = "linear_issue"
    GITHUB_PR = "github_pr"
    GITHUB_COMMIT = "github_commit"
    SLACK_MESSAGE = "slack_message"
    CODE_FILE = "code_file"


@dataclass
class TraceabilityLink:
    """A link between two artifacts."""
    source_type: ArtifactType
    source_id: str
    source_title: Optional[str]
    target_type: ArtifactType
    target_id: str
    target_title: Optional[str]
    link_type: LinkType
    confidence: float
    evidence: str


@dataclass
class ExtractionResult:
    """Result of traceability extraction."""
    links: List[TraceabilityLink] = field(default_factory=list)
    ticket_refs_found: List[str] = field(default_factory=list)
    file_refs_found: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class TraceabilityExtractor:
    """
    Extracts traceability links from PRs, commits, and messages.

    Usage:
        extractor = TraceabilityExtractor(pool, team_keys=["SCP", "ENG"])

        # Extract from a PR
        result = extractor.extract_from_pr(
            pr_title="feat: Add auth flow (SCP-123)",
            pr_body="Implements the login feature from SCP-123",
            files_changed=["src/auth/login.py", "src/auth/oauth.py"],
        )

        # Store the links
        await extractor.store_links(workspace_id, result.links)
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        team_keys: Optional[List[str]] = None,
    ):
        """
        Initialize the extractor.

        Args:
            pool: Database connection pool
            team_keys: Linear team keys to look for (e.g., ["SCP", "ENG"])
                      If None, will detect any pattern like ABC-123
        """
        self.pool = pool
        self.team_keys = team_keys or []

        # Build regex pattern for ticket references
        if self.team_keys:
            # Match specific team keys: SCP-123, ENG-456
            keys_pattern = "|".join(re.escape(k) for k in self.team_keys)
            self.ticket_pattern = re.compile(
                rf"\b({keys_pattern})-(\d+)\b",
                re.IGNORECASE
            )
        else:
            # Match any pattern like ABC-123, PROJ-456
            self.ticket_pattern = re.compile(
                r"\b([A-Z]{2,10})-(\d+)\b",
                re.IGNORECASE
            )

        # Pattern for file paths in text
        self.file_pattern = re.compile(
            r"(?:^|\s|`|'|\")"  # Start of string, whitespace, or quote
            r"((?:[\w.-]+/)*[\w.-]+\."  # Path with directories
            r"(?:py|js|ts|jsx|tsx|go|rs|java|rb|php|c|cpp|h|sql|yaml|yml|json|md))"  # Extension
            r"(?:\s|$|`|'|\"|:|\))",  # End markers
            re.MULTILINE
        )

        # Common link keywords in PR titles/bodies
        self.link_keywords = {
            LinkType.IMPLEMENTS: ["implements", "implement", "for", "adds", "add"],
            LinkType.FIXES: ["fixes", "fix", "fixed", "resolves", "resolve", "resolved"],
            LinkType.CLOSES: ["closes", "close", "closed"],
        }

    async def get_team_keys_from_linear(self, workspace_id: str) -> List[str]:
        """
        Fetch Linear team keys from the API for a workspace.

        Args:
            workspace_id: The workspace UUID

        Returns:
            List of team keys (e.g., ["SCP", "ENG"])
        """
        from backend.integrations.auth import get_integration_token
        import httpx

        token = await get_integration_token("linear", workspace_id)
        if not token:
            logger.warning(f"Linear not connected for workspace {workspace_id}")
            return []

        query = """
        query {
            teams {
                nodes {
                    key
                }
            }
        }
        """

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.linear.app/graphql",
                    headers={
                        "Authorization": f"Bearer {token.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"query": query}
                )

                if response.status_code != 200:
                    logger.error(f"Linear API error: {response.status_code}")
                    return []

                data = response.json()
                teams = data.get("data", {}).get("teams", {}).get("nodes", [])
                keys = [team["key"] for team in teams]

                logger.info(f"Found Linear team keys: {keys}")
                return keys

        except Exception as e:
            logger.error(f"Error fetching Linear team keys: {e}")
            return []

    def extract_ticket_refs(self, text: str) -> List[Tuple[str, str]]:
        """
        Extract ticket references from text.

        Args:
            text: Text to search (PR title, body, commit message)

        Returns:
            List of (team_key, issue_number) tuples
        """
        if not text:
            return []

        matches = self.ticket_pattern.findall(text)
        # Convert to uppercase for consistency
        return [(key.upper(), num) for key, num in matches]

    def extract_file_refs(self, text: str) -> List[str]:
        """
        Extract file path references from text.

        Args:
            text: Text to search (Slack message, PR body)

        Returns:
            List of file paths mentioned
        """
        if not text:
            return []

        matches = self.file_pattern.findall(text)
        return list(set(matches))  # Deduplicate

    def determine_link_type(self, text: str) -> LinkType:
        """
        Determine the type of link based on keywords in text.

        Args:
            text: Text to analyze (PR title, body)

        Returns:
            Most likely LinkType
        """
        text_lower = text.lower()

        for link_type, keywords in self.link_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return link_type

        return LinkType.IMPLEMENTS  # Default

    def extract_from_pr(
        self,
        pr_number: int,
        pr_title: str,
        pr_body: Optional[str],
        files_changed: List[str],
        repo_full_name: str,
    ) -> ExtractionResult:
        """
        Extract traceability links from a pull request.

        Args:
            pr_number: PR number
            pr_title: PR title
            pr_body: PR description/body
            files_changed: List of files modified by the PR
            repo_full_name: Repository name (owner/repo)

        Returns:
            ExtractionResult with discovered links
        """
        result = ExtractionResult()
        combined_text = f"{pr_title}\n{pr_body or ''}"

        # Extract ticket references
        ticket_refs = self.extract_ticket_refs(combined_text)
        result.ticket_refs_found = [f"{key}-{num}" for key, num in ticket_refs]

        # Determine link type from PR title
        link_type = self.determine_link_type(combined_text)

        # Create links from PR to Linear issues
        for team_key, issue_num in ticket_refs:
            issue_id = f"{team_key}-{issue_num}"
            result.links.append(TraceabilityLink(
                source_type=ArtifactType.GITHUB_PR,
                source_id=f"{repo_full_name}#{pr_number}",
                source_title=pr_title,
                target_type=ArtifactType.LINEAR_ISSUE,
                target_id=issue_id,
                target_title=None,  # Would need to fetch from Linear
                link_type=link_type,
                confidence=0.9 if issue_id in pr_title else 0.7,
                evidence=f"Found '{issue_id}' in PR {'title' if issue_id in pr_title else 'body'}",
            ))

        # Create links from PR to code files
        result.file_refs_found = files_changed
        for file_path in files_changed:
            result.links.append(TraceabilityLink(
                source_type=ArtifactType.GITHUB_PR,
                source_id=f"{repo_full_name}#{pr_number}",
                source_title=pr_title,
                target_type=ArtifactType.CODE_FILE,
                target_id=f"{repo_full_name}:{file_path}",
                target_title=file_path,
                link_type=LinkType.MODIFIES,
                confidence=1.0,  # Files changed is definitive
                evidence="File listed in PR diff",
            ))

        logger.info(
            f"Extracted {len(result.links)} links from PR #{pr_number}: "
            f"{len(ticket_refs)} tickets, {len(files_changed)} files"
        )

        return result

    def extract_from_slack_message(
        self,
        message_id: str,
        message_text: str,
        channel_name: str,
    ) -> ExtractionResult:
        """
        Extract traceability links from a Slack message.

        Args:
            message_id: Slack message timestamp/ID
            message_text: Message content
            channel_name: Channel name

        Returns:
            ExtractionResult with discovered links
        """
        result = ExtractionResult()

        # Extract ticket references
        ticket_refs = self.extract_ticket_refs(message_text)
        result.ticket_refs_found = [f"{key}-{num}" for key, num in ticket_refs]

        # Extract file references
        file_refs = self.extract_file_refs(message_text)
        result.file_refs_found = file_refs

        # Create links to Linear issues
        for team_key, issue_num in ticket_refs:
            issue_id = f"{team_key}-{issue_num}"
            result.links.append(TraceabilityLink(
                source_type=ArtifactType.SLACK_MESSAGE,
                source_id=message_id,
                source_title=f"Message in #{channel_name}",
                target_type=ArtifactType.LINEAR_ISSUE,
                target_id=issue_id,
                target_title=None,
                link_type=LinkType.DISCUSSES,
                confidence=0.7,
                evidence=f"Found '{issue_id}' in Slack message",
            ))

        # Create links to code files
        for file_path in file_refs:
            result.links.append(TraceabilityLink(
                source_type=ArtifactType.SLACK_MESSAGE,
                source_id=message_id,
                source_title=f"Message in #{channel_name}",
                target_type=ArtifactType.CODE_FILE,
                target_id=file_path,
                target_title=file_path,
                link_type=LinkType.DISCUSSES,
                confidence=0.6,
                evidence=f"Found file path '{file_path}' in message",
            ))

        return result

    async def store_links(
        self,
        workspace_id: str,
        links: List[TraceabilityLink],
    ) -> int:
        """
        Store traceability links in the database.

        Args:
            workspace_id: Workspace UUID
            links: List of links to store

        Returns:
            Number of links stored
        """
        if not links:
            return 0

        stored = 0
        async with self.pool.acquire() as conn:
            for link in links:
                try:
                    await conn.execute(
                        """
                        INSERT INTO traceability_links (
                            workspace_id, source_type, source_external_id, source_title,
                            target_type, target_external_id, target_title,
                            link_type, confidence, evidence
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (workspace_id, source_type, source_external_id, target_type, target_external_id)
                        DO UPDATE SET
                            source_title = EXCLUDED.source_title,
                            target_title = EXCLUDED.target_title,
                            link_type = EXCLUDED.link_type,
                            confidence = EXCLUDED.confidence,
                            evidence = EXCLUDED.evidence
                        """,
                        workspace_id,
                        link.source_type.value,
                        link.source_id,
                        link.source_title,
                        link.target_type.value,
                        link.target_id,
                        link.target_title,
                        link.link_type.value,
                        link.confidence,
                        link.evidence,
                    )
                    stored += 1
                except Exception as e:
                    logger.error(f"Error storing link: {e}")

        logger.info(f"Stored {stored}/{len(links)} traceability links")
        return stored

    async def get_links_for_artifact(
        self,
        workspace_id: str,
        artifact_type: ArtifactType,
        artifact_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all links related to an artifact (as source or target).

        Args:
            workspace_id: Workspace UUID
            artifact_type: Type of the artifact
            artifact_id: ID of the artifact

        Returns:
            List of related links
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM traceability_links
                WHERE workspace_id = $1
                  AND (
                    (source_type = $2 AND source_external_id = $3)
                    OR (target_type = $2 AND target_external_id = $3)
                  )
                ORDER BY created_at DESC
                """,
                workspace_id,
                artifact_type.value,
                artifact_id,
            )
            return [dict(row) for row in rows]

    async def get_code_to_ticket_chain(
        self,
        workspace_id: str,
        file_path: str,
        repo_full_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Get the chain from code file → PRs → Linear issues.

        This answers: "What tickets led to changes in this file?"

        Args:
            workspace_id: Workspace UUID
            file_path: Path to the code file
            repo_full_name: Repository name

        Returns:
            List of chains with PR and ticket info
        """
        code_id = f"{repo_full_name}:{file_path}"

        async with self.pool.acquire() as conn:
            # First, get PRs that modified this file
            pr_links = await conn.fetch(
                """
                SELECT source_external_id, source_title
                FROM traceability_links
                WHERE workspace_id = $1
                  AND target_type = $2
                  AND target_external_id = $3
                  AND source_type = $4
                """,
                workspace_id,
                ArtifactType.CODE_FILE.value,
                code_id,
                ArtifactType.GITHUB_PR.value,
            )

            chains = []
            for pr_link in pr_links:
                pr_id = pr_link["source_external_id"]
                pr_title = pr_link["source_title"]

                # Get tickets linked to this PR
                ticket_links = await conn.fetch(
                    """
                    SELECT target_external_id, link_type, evidence
                    FROM traceability_links
                    WHERE workspace_id = $1
                      AND source_type = $2
                      AND source_external_id = $3
                      AND target_type = $4
                    """,
                    workspace_id,
                    ArtifactType.GITHUB_PR.value,
                    pr_id,
                    ArtifactType.LINEAR_ISSUE.value,
                )

                chains.append({
                    "file": file_path,
                    "pr_id": pr_id,
                    "pr_title": pr_title,
                    "tickets": [
                        {
                            "id": t["target_external_id"],
                            "link_type": t["link_type"],
                            "evidence": t["evidence"],
                        }
                        for t in ticket_links
                    ],
                })

            return chains
