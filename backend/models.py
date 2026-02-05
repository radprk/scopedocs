from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid

# Enums
class ArtifactType(str, Enum):
    SLACK_MESSAGE = "slack_message"
    SLACK_THREAD = "slack_thread"
    GITHUB_PR = "github_pr"
    GITHUB_COMMIT = "github_commit"
    GITHUB_REVIEW = "github_review"
    LINEAR_ISSUE = "linear_issue"
    LINEAR_PROJECT = "linear_project"
    SCOPEDOC = "scopedoc"
    DECISION = "decision"

class RelationshipType(str, Enum):
    IMPLEMENTS = "implements"
    DISCUSSES = "discusses"
    OWNS = "owns"
    TOUCHES = "touches"
    DEPENDS_ON = "depends_on"
    DOCUMENTS = "documents"
    MENTIONS = "mentions"
    DERIVES_FROM = "derives_from"

class FreshnessLevel(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    OUTDATED = "outdated"

class IngestionSource(str, Enum):
    GITHUB = "github"
    SLACK = "slack"
    LINEAR = "linear"

class IngestionJobType(str, Enum):
    REFRESH = "refresh"
    BACKFILL = "backfill"

class IngestionJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

# Base Models
class ArtifactEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    artifact_type: ArtifactType
    artifact_id: str
    event_time: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any]
    source: str  # slack, github, linear
    metadata: Dict[str, Any] = {}

class WorkItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    external_id: str  # Linear issue ID
    title: str
    description: str
    status: str
    team: Optional[str] = None
    assignee: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    labels: List[str] = []

class PullRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    external_id: str  # GitHub PR number
    title: str
    description: str
    author: str
    status: str  # open, merged, closed
    repo: str
    files_changed: List[str] = []
    work_item_refs: List[str] = []  # References to Linear issues
    created_at: datetime = Field(default_factory=datetime.utcnow)
    merged_at: Optional[datetime] = None
    reviewers: List[str] = []

class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    external_id: str  # Slack thread ID
    channel: str
    thread_ts: str
    messages: List[Dict[str, Any]] = []
    participants: List[str] = []
    decision_extracted: Optional[str] = None
    work_item_refs: List[str] = []
    pr_refs: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ScopeDoc(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    project_name: str
    sections: Dict[str, Any] = {
        "background": "",
        "scope": "",
        "api_changes": "",
        "migration": "",
        "rollout": "",
        "ownership": "",
        "decisions": "",
        "risks": ""
    }
    freshness_score: float = 1.0
    freshness_level: FreshnessLevel = FreshnessLevel.FRESH
    last_verified_at: datetime = Field(default_factory=datetime.utcnow)
    evidence_links: List[Dict[str, str]] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Component(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: str  # service, repo, directory, api
    path: Optional[str] = None
    repo: Optional[str] = None
    owners: List[str] = []
    dependencies: List[str] = []

class Person(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    external_id: str
    name: str
    email: Optional[str] = None
    team: Optional[str] = None
    github_username: Optional[str] = None
    slack_id: Optional[str] = None

class Relationship(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    source_type: str
    target_id: str
    target_type: str
    relationship_type: RelationshipType
    confidence: float = 1.0
    evidence: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

class EmbeddedArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    artifact_id: str
    artifact_type: ArtifactType
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)

class IntegrationToken(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    integration: str
    workspace_id: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ExternalIDMapping(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    integration: str
    external_id: str
    internal_id: str
    artifact_type: ArtifactType
    created_at: datetime = Field(default_factory=datetime.utcnow)

# API Request/Response Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    question: str
    history: List[ChatMessage] = []

class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []

class DocDriftAlert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str
    project_name: str
    sections_affected: List[str]
    trigger_event: str  # PR merged, file changed, etc
    trigger_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    severity: str = "medium"  # low, medium, high

class IngestionJobPayload(BaseModel):
    source: IngestionSource
    since: datetime
    project_id: Optional[str] = None

class IngestionJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_key: str
    job_type: IngestionJobType
    payload: IngestionJobPayload
    status: IngestionJobStatus = IngestionJobStatus.QUEUED
    attempts: int = 0
    checkpoint: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# AI Layer Models
# =============================================================================

class DocType(str, Enum):
    """Types of generated documentation."""
    OVERVIEW = "overview"
    MODULE = "module"
    FILE = "file"
    FUNCTION = "function"


class LinkType(str, Enum):
    """Types of doc-to-code links."""
    EXPLAINS = "explains"
    REFERENCES = "references"
    EXAMPLE_OF = "example_of"


class MessageSource(str, Enum):
    """Source of embedded messages."""
    SLACK = "slack"
    LINEAR = "linear"


class CodeEmbedding(BaseModel):
    """Embedded code chunk with vector representation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    repo_full_name: str
    file_path: str
    commit_sha: str
    chunk_index: int
    start_line: int
    end_line: int
    content_hash: str
    embedding: Optional[List[float]] = None
    symbol_names: List[str] = []
    language: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GeneratedDoc(BaseModel):
    """AI-generated documentation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    repo_full_name: str
    file_path: Optional[str] = None
    doc_type: DocType
    title: str
    content: str
    embedding: Optional[List[float]] = None
    source_chunks: List[str] = []
    source_commit_sha: Optional[str] = None
    version: int = 1
    is_stale: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocCodeLink(BaseModel):
    """Link between documentation and code."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    doc_id: str
    doc_section: Optional[str] = None
    doc_line_start: Optional[int] = None
    doc_line_end: Optional[int] = None
    code_embedding_id: Optional[str] = None
    repo_full_name: str
    file_path: str
    code_line_start: int
    code_line_end: int
    link_type: LinkType = LinkType.EXPLAINS
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MessageEmbedding(BaseModel):
    """Embedded Slack/Linear message."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    source: MessageSource
    external_id: str
    channel_or_project: Optional[str] = None
    summary: Optional[str] = None
    embedding: Optional[List[float]] = None
    linked_code_chunks: List[str] = []
    linked_prs: List[str] = []
    linked_issues: List[str] = []
    message_type: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TraceabilityLink(BaseModel):
    """Link in the traceability graph (Linear issue -> PR -> Code)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    source_type: str  # 'linear_issue', 'github_pr', 'slack_message', 'code_file'
    source_external_id: str
    source_title: Optional[str] = None
    target_type: str
    target_external_id: str
    target_title: Optional[str] = None
    link_type: str  # 'implements', 'discusses', 'mentions', 'modifies'
    confidence: float = 1.0
    evidence: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatSession(BaseModel):
    """Chat session for conversational Q&A."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    repo_full_name: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessageRecord(BaseModel):
    """Message in a chat session."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    role: str  # 'user', 'assistant'
    content: str
    sources: List[Dict[str, Any]] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
