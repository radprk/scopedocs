import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from models import (
    Conversation,
    PullRequest,
    WorkItem,
    Relationship,
    RelationshipType,
    ArtifactType,
)
from database import db, COLLECTIONS

LINEAR_KEY_PATTERN = re.compile(r"\b[A-Z]{2,10}-\d+\b")
PR_REFERENCE_PATTERN = re.compile(r"#(\d+)")


def extract_linear_keys(text: str) -> List[str]:
    if not text:
        return []
    return list({match.group(0) for match in LINEAR_KEY_PATTERN.finditer(text)})


def extract_pr_numbers(text: str) -> List[str]:
    if not text:
        return []
    return list({match.group(1) for match in PR_REFERENCE_PATTERN.finditer(text)})


async def get_or_create_mapping(
    integration: str,
    external_id: str,
    artifact_type: ArtifactType,
    internal_id: Optional[str] = None,
) -> str:
    existing = await db[COLLECTIONS['external_id_mappings']].find_one(
        {
            'integration': integration,
            'external_id': external_id,
            'artifact_type': artifact_type.value,
        },
        {'_id': 0},
    )
    if existing:
        return existing['internal_id']

    internal_id = internal_id or str(uuid.uuid4())
    await db[COLLECTIONS['external_id_mappings']].insert_one(
        {
            'id': str(uuid.uuid4()),
            'integration': integration,
            'external_id': external_id,
            'internal_id': internal_id,
            'artifact_type': artifact_type.value,
            'created_at': datetime.utcnow(),
        }
    )
    return internal_id


async def normalize_slack_event(event: Dict[str, Any]) -> Tuple[Conversation, List[Relationship]]:
    thread_ts = event.get('thread_ts') or event.get('ts')
    channel = event.get('channel')
    external_id = thread_ts
    conversation_id = await get_or_create_mapping('slack', external_id, ArtifactType.SLACK_THREAD)

    message_text = event.get('text', '')
    user_id = event.get('user') or event.get('bot_id') or 'unknown'
    work_item_refs = extract_linear_keys(message_text)
    pr_refs = extract_pr_numbers(message_text)

    message_data = {
        'ts': event.get('ts'),
        'user': user_id,
        'text': message_text,
        'thread_ts': thread_ts,
        'event_ts': event.get('event_ts'),
    }

    conversation = Conversation(
        id=conversation_id,
        external_id=external_id,
        channel=channel,
        thread_ts=thread_ts,
        messages=[message_data],
        participants=[user_id],
        work_item_refs=work_item_refs,
        pr_refs=pr_refs,
    )

    relationships: List[Relationship] = []
    for work_item_ref in work_item_refs:
        work_item_id = await get_or_create_mapping(
            'linear',
            work_item_ref,
            ArtifactType.LINEAR_ISSUE,
        )
        relationships.append(
            Relationship(
                source_id=conversation_id,
                source_type='conversation',
                target_id=work_item_id,
                target_type='work_item',
                relationship_type=RelationshipType.DISCUSSES,
                evidence=[message_text],
            )
        )
    for pr_ref in pr_refs:
        pr_id = await get_or_create_mapping('github', pr_ref, ArtifactType.GITHUB_PR)
        relationships.append(
            Relationship(
                source_id=conversation_id,
                source_type='conversation',
                target_id=pr_id,
                target_type='pull_request',
                relationship_type=RelationshipType.MENTIONS,
                evidence=[message_text],
            )
        )

    return conversation, relationships


async def normalize_github_pull_request(payload: Dict[str, Any]) -> Tuple[PullRequest, List[Relationship]]:
    pr_data = payload.get('pull_request', {})
    repo = payload.get('repository', {}).get('full_name', '')
    pr_number = str(pr_data.get('number') or payload.get('number'))
    internal_id = await get_or_create_mapping('github', pr_number, ArtifactType.GITHUB_PR)

    title = pr_data.get('title', '')
    body = pr_data.get('body', '') or ''
    work_item_refs = extract_linear_keys(f"{title}\n{body}")

    pr = PullRequest(
        id=internal_id,
        external_id=pr_number,
        title=title,
        description=body,
        author=pr_data.get('user', {}).get('login', 'unknown'),
        status='merged' if pr_data.get('merged') else pr_data.get('state', 'open'),
        repo=repo,
        files_changed=[],
        work_item_refs=work_item_refs,
        created_at=_parse_datetime(pr_data.get('created_at')),
        merged_at=_parse_datetime(pr_data.get('merged_at')),
        reviewers=[review.get('login') for review in pr_data.get('requested_reviewers', [])],
    )

    relationships: List[Relationship] = []
    for work_item_ref in work_item_refs:
        work_item_id = await get_or_create_mapping('linear', work_item_ref, ArtifactType.LINEAR_ISSUE)
        relationships.append(
            Relationship(
                source_id=internal_id,
                source_type='pull_request',
                target_id=work_item_id,
                target_type='work_item',
                relationship_type=RelationshipType.IMPLEMENTS,
                evidence=[title],
            )
        )

    return pr, relationships


async def normalize_github_review(payload: Dict[str, Any]) -> Optional[PullRequest]:
    pr_data = payload.get('pull_request', {})
    pr_number = str(pr_data.get('number') or payload.get('number'))
    if not pr_number:
        return None

    internal_id = await get_or_create_mapping('github', pr_number, ArtifactType.GITHUB_PR)
    reviewer = payload.get('review', {}).get('user', {}).get('login')
    reviewers = [reviewer] if reviewer else []

    return PullRequest(
        id=internal_id,
        external_id=pr_number,
        title=pr_data.get('title', ''),
        description=pr_data.get('body', '') or '',
        author=pr_data.get('user', {}).get('login', 'unknown'),
        status='merged' if pr_data.get('merged') else pr_data.get('state', 'open'),
        repo=payload.get('repository', {}).get('full_name', ''),
        files_changed=[],
        work_item_refs=extract_linear_keys(pr_data.get('title', '') + "\n" + (pr_data.get('body') or '')),
        created_at=_parse_datetime(pr_data.get('created_at')),
        merged_at=_parse_datetime(pr_data.get('merged_at')),
        reviewers=reviewers,
    )


async def normalize_github_push(payload: Dict[str, Any]) -> List[Relationship]:
    relationships: List[Relationship] = []
    for commit in payload.get('commits', []):
        message = commit.get('message', '')
        for work_item_ref in extract_linear_keys(message):
            work_item_id = await get_or_create_mapping('linear', work_item_ref, ArtifactType.LINEAR_ISSUE)
            relationships.append(
                Relationship(
                    source_id=commit.get('id', str(uuid.uuid4())),
                    source_type='github_commit',
                    target_id=work_item_id,
                    target_type='work_item',
                    relationship_type=RelationshipType.TOUCHES,
                    evidence=[message],
                )
            )
    return relationships


async def normalize_linear_issue(issue: Dict[str, Any]) -> Tuple[WorkItem, List[Relationship]]:
    external_id = issue.get('id') or issue.get('identifier')
    internal_id = await get_or_create_mapping('linear', external_id, ArtifactType.LINEAR_ISSUE)
    identifier = issue.get('identifier')
    if identifier and identifier != external_id:
        await get_or_create_mapping('linear', identifier, ArtifactType.LINEAR_ISSUE, internal_id=internal_id)

    title = issue.get('title', '')
    description = issue.get('description', '') or ''
    status = issue.get('state', {}).get('name') or issue.get('state') or 'unknown'
    team = (issue.get('team') or {}).get('name') if isinstance(issue.get('team'), dict) else issue.get('team')
    assignee = (issue.get('assignee') or {}).get('name') if isinstance(issue.get('assignee'), dict) else issue.get('assignee')
    project = issue.get('project') or {}
    project_id = project.get('id') if isinstance(project, dict) else project

    labels = []
    label_data = issue.get('labels')
    if isinstance(label_data, dict):
        labels = [label.get('name') for label in label_data.get('nodes', []) if label.get('name')]
    elif isinstance(label_data, list):
        labels = [label.get('name', label) for label in label_data]

    work_item = WorkItem(
        id=internal_id,
        external_id=external_id,
        title=title,
        description=description,
        status=status,
        team=team,
        assignee=assignee,
        project_id=project_id,
        created_at=_parse_datetime(issue.get('createdAt')),
        updated_at=_parse_datetime(issue.get('updatedAt')),
        labels=labels,
    )

    relationships: List[Relationship] = []
    for pr_ref in extract_pr_numbers(description):
        pr_id = await get_or_create_mapping('github', pr_ref, ArtifactType.GITHUB_PR)
        relationships.append(
            Relationship(
                source_id=work_item.id,
                source_type='work_item',
                target_id=pr_id,
                target_type='pull_request',
                relationship_type=RelationshipType.DEPENDS_ON,
                evidence=[description],
            )
        )

    return work_item, relationships


def _parse_datetime(value: Optional[str]) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return datetime.utcnow()
