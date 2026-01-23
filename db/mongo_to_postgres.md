# Mongo to Postgres Mapping

This mapping mirrors `backend/models.py` and keeps Mongo-style fields aligned with the new SQL schema.

## work_items
- `work_items.id` -> `work_items.id`
- `work_items.external_id` -> `work_items.external_id`
- `work_items.title` -> `work_items.title`
- `work_items.description` -> `work_items.description`
- `work_items.status` -> `work_items.status`
- `work_items.team` -> `work_items.team`
- `work_items.assignee` -> `work_items.assignee`
- `work_items.project_id` -> `work_items.project_id`
- `work_items.created_at` -> `work_items.created_at`
- `work_items.updated_at` -> `work_items.updated_at`
- `work_items.labels` -> `work_items.labels`

## pull_requests
- `pull_requests.id` -> `pull_requests.id`
- `pull_requests.external_id` -> `pull_requests.external_id`
- `pull_requests.title` -> `pull_requests.title`
- `pull_requests.description` -> `pull_requests.description`
- `pull_requests.author` -> `pull_requests.author`
- `pull_requests.status` -> `pull_requests.status`
- `pull_requests.repo` -> `pull_requests.repo`
- `pull_requests.files_changed` -> `pull_requests.files_changed`
- `pull_requests.work_item_refs` -> `pull_requests.work_item_refs`
- `pull_requests.created_at` -> `pull_requests.created_at`
- `pull_requests.merged_at` -> `pull_requests.merged_at`
- `pull_requests.reviewers` -> `pull_requests.reviewers`

## conversations
- `conversations.id` -> `conversations.id`
- `conversations.external_id` -> `conversations.external_id`
- `conversations.channel` -> `conversations.channel`
- `conversations.thread_ts` -> `conversations.thread_ts`
- `conversations.messages` -> `conversations.messages`
- `conversations.participants` -> `conversations.participants`
- `conversations.decision_extracted` -> `conversations.decision_extracted`
- `conversations.work_item_refs` -> `conversations.work_item_refs`
- `conversations.pr_refs` -> `conversations.pr_refs`
- `conversations.created_at` -> `conversations.created_at`

## scopedocs
- `scopedocs.id` -> `scopedocs.id`
- `scopedocs.project_id` -> `scopedocs.project_id`
- `scopedocs.project_name` -> `scopedocs.project_name`
- `scopedocs.sections` -> `scopedocs.sections`
- `scopedocs.freshness_score` -> `scopedocs.freshness_score`
- `scopedocs.freshness_level` -> `scopedocs.freshness_level`
- `scopedocs.last_verified_at` -> `scopedocs.last_verified_at`
- `scopedocs.evidence_links` -> `scopedocs.evidence_links`
- `scopedocs.created_at` -> `scopedocs.created_at`
- `scopedocs.updated_at` -> `scopedocs.updated_at`

## components
- `components.id` -> `components.id`
- `components.name` -> `components.name`
- `components.type` -> `components.type`
- `components.path` -> `components.path`
- `components.repo` -> `components.repo`
- `components.owners` -> `components.owners`
- `components.dependencies` -> `components.dependencies`

## people
- `people.id` -> `people.id`
- `people.external_id` -> `people.external_id`
- `people.name` -> `people.name`
- `people.email` -> `people.email`
- `people.team` -> `people.team`
- `people.github_username` -> `people.github_username`
- `people.slack_id` -> `people.slack_id`

## relationships
- `relationships.id` -> `relationships.id`
- `relationships.source_id` -> `relationships.source_id` (FK to `components.id`)
- `relationships.source_type` -> `relationships.source_type`
- `relationships.target_id` -> `relationships.target_id` (FK to `components.id`)
- `relationships.target_type` -> `relationships.target_type`
- `relationships.relationship_type` -> `relationships.relationship_type`
- `relationships.confidence` -> `relationships.confidence`
- `relationships.evidence` -> `relationships.evidence`
- `relationships.created_at` -> `relationships.created_at`

## embeddings
- `embeddings.id` -> `embeddings.id`
- `embeddings.artifact_id` -> `embeddings.artifact_id`
- `embeddings.artifact_type` -> `embeddings.artifact_type`
- `embeddings.content` -> `embeddings.content`
- `embeddings.embedding` -> `embeddings.embedding`
- `embeddings.metadata` -> `embeddings.metadata`
- `embeddings.created_at` -> `embeddings.created_at`

## drift_alerts
- `drift_alerts.id` -> `drift_alerts.id`
- `drift_alerts.doc_id` -> `drift_alerts.doc_id`
- `drift_alerts.project_name` -> `drift_alerts.project_name`
- `drift_alerts.sections_affected` -> `drift_alerts.sections_affected`
- `drift_alerts.trigger_event` -> `drift_alerts.trigger_event`
- `drift_alerts.trigger_id` -> `drift_alerts.trigger_id`
- `drift_alerts.created_at` -> `drift_alerts.created_at`
- `drift_alerts.severity` -> `drift_alerts.severity`

## artifact_events
- `artifact_events.id` -> `artifact_events.id`
- `artifact_events.artifact_type` -> `artifact_events.artifact_type`
- `artifact_events.artifact_id` -> `artifact_events.artifact_id`
- `artifact_events.event_time` -> `artifact_events.event_time`
- `artifact_events.data` -> `artifact_events.data`
- `artifact_events.source` -> `artifact_events.source`
- `artifact_events.metadata` -> `artifact_events.metadata`
