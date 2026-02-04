"""
Normalization functions for converting external API data to internal models.
"""
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from backend.models import (
    Conversation,
    PullRequest,
    WorkItem,
    Relationship,
    RelationshipType,
    ArtifactType,
)
from backend.storage.postgres import (
    get_external_id_mapping,
    upsert_external_id_mapping,
)


# Regex patterns for extracting references
LINEAR_KEY_PATTERN = re.compile(r"\b[A-Z]{2,10}-\d+\b")
PR_REFERENCE_PATTERN = re.compile(r"#(\d+)")


def extract_linear_keys(text: str) -> List[str]:
    """Extract Linear issue identifiers like ENG-123 from text."""
    if not text:
        return []
    return list({match.group(0) for match in LINEAR_KEY_PATTERN.finditer(text)})


def extract_pr_numbers(text: str) -> List[str]:
    """Extract GitHub PR numbers like #456 from text."""
    if not text:
        return []
    return list({match.group(1) for match in PR_REFERENCE_PATTERN.finditer(text)})


async def get_or_create_mapping(
    integration: str,
    external_id: str,
    artifact_type: ArtifactType,
    internal_id: Optional[str] = None,
) -> str:
    """
    Ensure a stable internal UUID exists for a given external artifact.
    Uses PostgreSQL storage.
    """
    existing = await get_external_id_mapping(
        integration=integration,
        external_id=external_id,
        artifact_type=artifact_type.value,
    )
    if existing:
        return existing["internal_id"]

    internal_id = internal_id or str(uuid.uuid4())
    
    await upsert_external_id_mapping({
        "id": str(uuid.uuid4()),
        "integration": integration,
        "external_id": external_id,
        "internal_id": internal_id,
        "artifact_type": artifact_type.value,
    })
    
    return internal_id


async def normalize_slack_event(event: Dict[str, Any]) -> Tuple[Conversation, List[Relationship]]:
    """Normalize a Slack event into a Conversation and extract relationships."""
    thread_ts = event.get('thread_ts') or event.get('ts')
    channel = event.get('channel')
    external_id = thread_ts
    conversation_id = await get_or_create_mapping('slack', external_id, ArtifactType.SLACK_THREAD)

    message_text = event.get('text', '')
    user_id = event.get('user') or event.get('bot_id') or 'unknown'

    conversation = Conversation(
        id=conversation_id,
        channel=channel,
        thread_ts=thread_ts,
        messages=[{
            'user': user_id,
            'text': message_text,
            'ts': event.get('ts'),
        }],
        participants=[user_id],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    # Extract relationships from message text
    relationships = []
    
    # Look for Linear issue references
    linear_keys = extract_linear_keys(message_text)
    for key in linear_keys:
        relationships.append(Relationship(
            id=str(uuid.uuid4()),
            source_id=conversation_id,
            source_type=ArtifactType.SLACK_THREAD,
            target_id=key,  # Will be resolved later
            target_type=ArtifactType.LINEAR_ISSUE,
            relationship_type=RelationshipType.MENTIONS,
            created_at=datetime.utcnow(),
        ))

    # Look for PR references
    pr_numbers = extract_pr_numbers(message_text)
    for pr_num in pr_numbers:
        relationships.append(Relationship(
            id=str(uuid.uuid4()),
            source_id=conversation_id,
            source_type=ArtifactType.SLACK_THREAD,
            target_id=pr_num,  # Will be resolved later
            target_type=ArtifactType.GITHUB_PR,
            relationship_type=RelationshipType.MENTIONS,
            created_at=datetime.utcnow(),
        ))

    return conversation, relationships


async def normalize_linear_issue(issue: Dict[str, Any]) -> Tuple[WorkItem, List[Relationship]]:
    """Normalize a Linear issue into a WorkItem and extract relationships."""
    external_id = issue.get('id')
    issue_key = issue.get('identifier', '')
    
    work_item_id = await get_or_create_mapping('linear', external_id, ArtifactType.LINEAR_ISSUE)

    work_item = WorkItem(
        id=work_item_id,
        external_id=external_id,
        key=issue_key,
        title=issue.get('title', ''),
        description=issue.get('description', ''),
        status=issue.get('state', {}).get('name', 'Unknown'),
        assignee=issue.get('assignee', {}).get('name') if issue.get('assignee') else None,
        created_at=datetime.fromisoformat(issue.get('createdAt', datetime.utcnow().isoformat()).replace('Z', '+00:00')),
        updated_at=datetime.fromisoformat(issue.get('updatedAt', datetime.utcnow().isoformat()).replace('Z', '+00:00')),
    )

    relationships = []
    
    # Check description for PR references
    description = issue.get('description', '') or ''
    pr_numbers = extract_pr_numbers(description)
    for pr_num in pr_numbers:
        relationships.append(Relationship(
            id=str(uuid.uuid4()),
            source_id=work_item_id,
            source_type=ArtifactType.LINEAR_ISSUE,
            target_id=pr_num,
            target_type=ArtifactType.GITHUB_PR,
            relationship_type=RelationshipType.MENTIONS,
            created_at=datetime.utcnow(),
        ))

    return work_item, relationships


async def normalize_github_pull_request(pr: Dict[str, Any], repo: str) -> Tuple[PullRequest, List[Relationship]]:
    """Normalize a GitHub PR into a PullRequest and extract relationships."""
    external_id = str(pr.get('id'))
    pr_number = pr.get('number')
    
    pr_id = await get_or_create_mapping('github', external_id, ArtifactType.GITHUB_PR)

    pull_request = PullRequest(
        id=pr_id,
        external_id=external_id,
        number=pr_number,
        repo=repo,
        title=pr.get('title', ''),
        body=pr.get('body', '') or '',
        state=pr.get('state', 'unknown'),
        author=pr.get('user', {}).get('login', 'unknown'),
        created_at=datetime.fromisoformat(pr.get('created_at', datetime.utcnow().isoformat()).replace('Z', '+00:00')),
        updated_at=datetime.fromisoformat(pr.get('updated_at', datetime.utcnow().isoformat()).replace('Z', '+00:00')),
        merged_at=datetime.fromisoformat(pr.get('merged_at').replace('Z', '+00:00')) if pr.get('merged_at') else None,
    )

    relationships = []
    
    # Check title and body for Linear issue references
    text = f"{pr.get('title', '')} {pr.get('body', '') or ''}"
    linear_keys = extract_linear_keys(text)
    for key in linear_keys:
        relationships.append(Relationship(
            id=str(uuid.uuid4()),
            source_id=pr_id,
            source_type=ArtifactType.GITHUB_PR,
            target_id=key,
            target_type=ArtifactType.LINEAR_ISSUE,
            relationship_type=RelationshipType.IMPLEMENTS,
            created_at=datetime.utcnow(),
        ))

    return pull_request, relationships
