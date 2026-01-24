from backend.models import ScopeDoc, WorkItem, PullRequest, Conversation, FreshnessLevel, DocDriftAlert
from typing import List, Dict, Any
from datetime import datetime, timedelta
from backend.database import db, COLLECTIONS

class DocGenerationService:
    """Service for generating living documentation"""

    async def generate_doc_from_project(self, project_id: str, project_name: str) -> ScopeDoc:
        """Generate a ScopeDoc from a Linear project"""

        # Fetch related artifacts
        cursor = await db[COLLECTIONS['work_items']].find({'project_id': project_id})
        work_items = await cursor.to_list(100)

        # Get related PRs
        work_item_ids = [item['external_id'] for item in work_items]
        if work_item_ids:
            cursor = await db[COLLECTIONS['pull_requests']].find(
                {'work_item_refs': {'$in': work_item_ids}}
            )
            prs = await cursor.to_list(100)
        else:
            prs = []

        # Get related conversations
        if work_item_ids:
            cursor = await db[COLLECTIONS['conversations']].find(
                {'work_item_refs': {'$in': work_item_ids}}
            )
            conversations = await cursor.to_list(100)
        else:
            conversations = []

        # Generate doc sections
        sections = await self._generate_sections(
            project_name, work_items, prs, conversations
        )

        # Get ownership info
        ownership_info = await self._get_ownership_info(work_items, prs)
        sections['ownership'] = ownership_info

        # Extract decisions
        decisions = self._extract_decisions(conversations)
        sections['decisions'] = decisions

        # Create evidence links
        evidence_links = self._create_evidence_links(work_items, prs, conversations)

        doc = ScopeDoc(
            project_id=project_id,
            project_name=project_name,
            sections=sections,
            evidence_links=evidence_links
        )

        return doc

    async def _generate_sections(self, project_name: str, work_items: List, prs: List, conversations: List) -> Dict[str, str]:
        """Generate doc sections from artifacts"""
        sections = {}

        # Background
        sections['background'] = f"""## Background
{project_name} is a key initiative aimed at improving our platform capabilities.
This project involves {len(work_items)} work items and has {len(prs)} associated pull requests.
"""

        # Scope
        sections['scope'] = """## Scope
Key deliverables:\n"""
        for item in work_items[:5]:  # Top 5
            sections['scope'] += f"- {item['title']} ({item['external_id']})\n"

        # API Changes
        api_changes = [pr for pr in prs if any('api' in f.lower() for f in pr.get('files_changed', []))]
        if api_changes:
            sections['api_changes'] = f"""## API Changes
{len(api_changes)} API-related changes have been made:
"""
            for pr in api_changes[:3]:
                sections['api_changes'] += f"- {pr['title']} (PR #{pr['external_id']})\n"
        else:
            sections['api_changes'] = "## API Changes\nNo API changes in this release."

        # Migration
        sections['migration'] = """## Migration Guide
No breaking changes expected. Standard deployment process applies.
"""

        # Rollout
        sections['rollout'] = """## Rollout Plan
1. Deploy to staging environment
2. Run integration tests
3. Deploy to production with feature flags
4. Monitor metrics and rollback if needed
"""

        # Risks
        sections['risks'] = """## Risks
- **Medium**: Potential performance impact on high-traffic endpoints
- **Low**: Database migration may require brief downtime
"""

        return sections

    async def _get_ownership_info(self, work_items: List, prs: List) -> str:
        """Get ownership information"""
        owners = set()
        for item in work_items:
            if item.get('assignee'):
                owners.add(item['assignee'])

        for pr in prs:
            if pr.get('author'):
                owners.add(pr['author'])

        # Get people details
        if owners:
            cursor = await db[COLLECTIONS['people']].find(
                {'external_id': {'$in': list(owners)}}
            )
            people = await cursor.to_list(100)
        else:
            people = []

        ownership_text = "## Ownership\n"
        for person in people:
            ownership_text += f"- {person['name']} ({person.get('team', 'Unknown Team')})\n"

        return ownership_text

    def _extract_decisions(self, conversations: List) -> str:
        """Extract decisions from conversations"""
        decisions_text = "## Key Decisions\n"

        for conv in conversations:
            if conv.get('decision_extracted'):
                decisions_text += f"- {conv['decision_extracted']} (from Slack thread {conv['external_id']})\n"

        if decisions_text == "## Key Decisions\n":
            decisions_text += "No major decisions documented yet.\n"

        return decisions_text

    def _create_evidence_links(self, work_items: List, prs: List, conversations: List) -> List[Dict[str, str]]:
        """Create evidence links"""
        links = []

        for item in work_items[:5]:
            links.append({
                'type': 'linear_issue',
                'id': item['external_id'],
                'title': item['title'],
                'url': f'https://linear.app/issue/{item["external_id"]}'
            })

        for pr in prs[:5]:
            links.append({
                'type': 'github_pr',
                'id': pr['external_id'],
                'title': pr['title'],
                'url': f'https://github.com/repo/{pr["external_id"]}'
            })

        return links


class FreshnessDetectionService:
    """Service for detecting doc freshness and drift"""

    async def calculate_freshness_score(self, doc: ScopeDoc) -> float:
        """Calculate doc freshness score (0.0 = outdated, 1.0 = fresh)"""
        score = 1.0

        # Time decay
        days_since_verification = (datetime.utcnow() - doc.last_verified_at).days
        time_penalty = min(days_since_verification * 0.05, 0.5)  # Max 50% penalty
        score -= time_penalty

        # Check for new PRs merged since last verification
        cursor = await db[COLLECTIONS['pull_requests']].find({
            'merged_at': {'$gte': doc.last_verified_at.isoformat()},
            'status': 'merged'
        })
        recent_prs = await cursor.to_list(100)

        # Check if any PRs touch components mentioned in doc
        relevant_prs = 0
        for pr in recent_prs:
            # Simple heuristic: if PR mentions project or related work items
            if any(link['id'] in pr.get('work_item_refs', []) for link in doc.evidence_links if link['type'] == 'linear_issue'):
                relevant_prs += 1

        pr_penalty = min(relevant_prs * 0.1, 0.4)  # Max 40% penalty
        score -= pr_penalty

        return max(0.0, min(1.0, score))

    async def detect_drift(self, doc_id: str) -> Dict[str, Any]:
        """Detect if a doc has drifted from reality"""
        doc = await db[COLLECTIONS['scopedocs']].find_one({'id': doc_id})
        if not doc:
            return {'error': 'Doc not found'}

        scope_doc = ScopeDoc(**doc)
        freshness_score = await self.calculate_freshness_score(scope_doc)

        # Determine freshness level
        if freshness_score >= 0.8:
            freshness_level = FreshnessLevel.FRESH
        elif freshness_score >= 0.5:
            freshness_level = FreshnessLevel.STALE
        else:
            freshness_level = FreshnessLevel.OUTDATED

        # Find trigger events (recent PRs that should update doc)
        cursor = await db[COLLECTIONS['pull_requests']].find({
            'merged_at': {'$gte': scope_doc.last_verified_at.isoformat()},
            'status': 'merged'
        })
        trigger_prs = await cursor.to_list(20)

        return {
            'doc_id': doc_id,
            'project_name': scope_doc.project_name,
            'freshness_score': freshness_score,
            'freshness_level': freshness_level,
            'trigger_events': len(trigger_prs),
            'last_verified': scope_doc.last_verified_at.isoformat(),
            'needs_update': freshness_level != FreshnessLevel.FRESH
        }

    async def create_drift_alert(self, doc_id: str, trigger_pr_id: str) -> DocDriftAlert:
        """Create a drift alert when a PR causes doc staleness"""
        doc = await db[COLLECTIONS['scopedocs']].find_one({'id': doc_id})
        pr = await db[COLLECTIONS['pull_requests']].find_one({'id': trigger_pr_id})

        if not doc or not pr:
            raise ValueError('Doc or PR not found')

        # Determine affected sections based on PR files
        affected_sections = []
        if any('api' in f.lower() for f in pr.get('files_changed', [])):
            affected_sections.append('api_changes')
        if any('migration' in f.lower() for f in pr.get('files_changed', [])):
            affected_sections.append('migration')

        severity = 'high' if len(affected_sections) > 2 else 'medium'

        alert = DocDriftAlert(
            doc_id=doc_id,
            project_name=doc['project_name'],
            sections_affected=affected_sections or ['general'],
            trigger_event=f"PR merged: {pr['title']}",
            trigger_id=trigger_pr_id,
            severity=severity
        )

        return alert
