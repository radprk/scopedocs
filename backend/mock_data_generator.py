import random
from datetime import datetime, timedelta
from typing import List
from models import (
    ArtifactEvent, ArtifactType, WorkItem, PullRequest, Conversation,
    Component, Person, Relationship, RelationshipType
)

# Sample data
TEAMS = ['Platform', 'Frontend', 'Backend', 'DevOps', 'Data']
STATUSES = ['backlog', 'in_progress', 'in_review', 'done']
PR_STATUSES = ['open', 'merged', 'closed']
REPOS = ['scopedocs-api', 'scopedocs-web', 'scopedocs-integrations', 'scopedocs-ml']
COMPONENT_TYPES = ['service', 'api', 'database', 'frontend']
NAMES = [
    'Alice Johnson', 'Bob Smith', 'Carol Davis', 'David Wilson',
    'Emma Brown', 'Frank Miller', 'Grace Lee', 'Henry Chen'
]

PROJECTS = [
    {'id': 'proj-1', 'name': 'User Authentication System', 'team': 'Platform'},
    {'id': 'proj-2', 'name': 'Real-time Notifications', 'team': 'Frontend'},
    {'id': 'proj-3', 'name': 'API Rate Limiting', 'team': 'Backend'},
    {'id': 'proj-4', 'name': 'Dashboard Analytics', 'team': 'Data'},
]

class MockDataGenerator:
    def __init__(self):
        self.people = self._generate_people()
        self.components = self._generate_components()
    
    def _generate_people(self) -> List[Person]:
        """Generate mock people"""
        people = []
        for i, name in enumerate(NAMES):
            person = Person(
                external_id=f'user-{i+1}',
                name=name,
                email=f'{name.lower().replace(" ", ".")}@scopedocs.ai',
                team=random.choice(TEAMS),
                github_username=name.lower().replace(' ', ''),
                slack_id=f'U{random.randint(100000, 999999)}'
            )
            people.append(person)
        return people
    
    def _generate_components(self) -> List[Component]:
        """Generate mock components"""
        components = [
            Component(
                name='Auth Service',
                type='service',
                repo='scopedocs-api',
                path='/services/auth',
                owners=['user-1', 'user-2']
            ),
            Component(
                name='Notification Service',
                type='service',
                repo='scopedocs-api',
                path='/services/notifications',
                owners=['user-3']
            ),
            Component(
                name='API Gateway',
                type='api',
                repo='scopedocs-api',
                path='/gateway',
                owners=['user-4', 'user-5']
            ),
            Component(
                name='Dashboard UI',
                type='frontend',
                repo='scopedocs-web',
                path='/src/dashboard',
                owners=['user-6', 'user-7']
            ),
        ]
        return components
    
    def generate_work_item(self, project: dict = None) -> WorkItem:
        """Generate a mock Linear work item"""
        if not project:
            project = random.choice(PROJECTS)
        
        titles = [
            f"Implement {random.choice(['JWT', 'OAuth', 'API', 'Database'])} integration",
            f"Add {random.choice(['validation', 'error handling', 'logging', 'monitoring'])} to {random.choice(['service', 'API', 'component'])}",
            f"Fix {random.choice(['performance', 'security', 'UX'])} issue in {random.choice(['auth', 'dashboard', 'API'])}",
            f"Update {random.choice(['documentation', 'tests', 'dependencies'])} for {random.choice(['service', 'component'])}"
        ]
        
        issue_num = random.randint(100, 999)
        return WorkItem(
            external_id=f'LIN-{issue_num}',
            title=random.choice(titles),
            description=f'This issue is part of {project["name"]} project. We need to implement the required changes.',
            status=random.choice(STATUSES),
            team=project['team'],
            assignee=random.choice(self.people).external_id,
            project_id=project['id'],
            labels=[random.choice(['bug', 'feature', 'improvement', 'tech-debt'])]
        )
    
    def generate_pull_request(self, work_item: WorkItem = None) -> PullRequest:
        """Generate a mock GitHub PR"""
        pr_num = random.randint(100, 999)
        files = [
            f'/src/{random.choice(["auth", "api", "services", "utils"])}/{random.choice(["index", "handler", "service"])}.py',
            f'/tests/test_{random.choice(["auth", "api", "services"])}.py'
        ]
        
        pr = PullRequest(
            external_id=f'PR-{pr_num}',
            title=work_item.title if work_item else 'Update implementation',
            description=f'Resolves {work_item.external_id}' if work_item else 'Bug fix',
            author=random.choice(self.people).github_username or 'developer',
            status=random.choice(PR_STATUSES),
            repo=random.choice(REPOS),
            files_changed=files,
            work_item_refs=[work_item.external_id] if work_item else [],
            reviewers=[p.github_username for p in random.sample(self.people, 2)]
        )
        
        if pr.status == 'merged':
            pr.merged_at = datetime.utcnow() - timedelta(hours=random.randint(1, 48))
        
        return pr
    
    def generate_conversation(self, work_item: WorkItem = None, pr: PullRequest = None) -> Conversation:
        """Generate a mock Slack conversation"""
        messages = [
            {
                'user': random.choice(self.people).slack_id or 'U123456',
                'text': f'Hey team, discussing {work_item.title if work_item else "the feature"}',
                'ts': (datetime.utcnow() - timedelta(hours=24)).isoformat()
            },
            {
                'user': random.choice(self.people).slack_id or 'U234567',
                'text': f'I think we should use approach A because it\'s more maintainable',
                'ts': (datetime.utcnow() - timedelta(hours=23)).isoformat()
            },
            {
                'user': random.choice(self.people).slack_id or 'U345678',
                'text': 'Agreed! Let\'s go with approach A',
                'ts': (datetime.utcnow() - timedelta(hours=22)).isoformat()
            }
        ]
        
        thread_id = f'thread-{random.randint(1000, 9999)}'
        return Conversation(
            external_id=thread_id,
            channel='#engineering',
            thread_ts=thread_id,
            messages=messages,
            participants=[msg['user'] for msg in messages],
            decision_extracted='Team agreed to use approach A for better maintainability',
            work_item_refs=[work_item.external_id] if work_item else [],
            pr_refs=[pr.external_id] if pr else []
        )
    
    def generate_relationships(self, work_item: WorkItem, pr: PullRequest, conversation: Conversation) -> List[Relationship]:
        """Generate relationships between artifacts"""
        relationships = []
        
        # PR implements Work Item
        relationships.append(Relationship(
            source_id=pr.id,
            source_type='pull_request',
            target_id=work_item.id,
            target_type='work_item',
            relationship_type=RelationshipType.IMPLEMENTS,
            confidence=0.95,
            evidence=[f'PR mentions {work_item.external_id}']
        ))
        
        # Conversation discusses Work Item
        relationships.append(Relationship(
            source_id=conversation.id,
            source_type='conversation',
            target_id=work_item.id,
            target_type='work_item',
            relationship_type=RelationshipType.DISCUSSES,
            confidence=0.9,
            evidence=['Slack thread mentions the issue']
        ))
        
        # Conversation discusses PR
        relationships.append(Relationship(
            source_id=conversation.id,
            source_type='conversation',
            target_id=pr.id,
            target_type='pull_request',
            relationship_type=RelationshipType.DISCUSSES,
            confidence=0.85,
            evidence=['PR linked in thread']
        ))
        
        # Component ownership
        component = random.choice(self.components)
        relationships.append(Relationship(
            source_id=work_item.assignee or 'user-1',
            source_type='person',
            target_id=component.id,
            target_type='component',
            relationship_type=RelationshipType.OWNS,
            confidence=0.8,
            evidence=['CODEOWNERS file']
        ))
        
        return relationships
    
    def generate_full_scenario(self) -> dict:
        """Generate a complete scenario with all artifacts and relationships"""
        project = random.choice(PROJECTS)
        work_item = self.generate_work_item(project)
        pr = self.generate_pull_request(work_item)
        conversation = self.generate_conversation(work_item, pr)
        relationships = self.generate_relationships(work_item, pr, conversation)
        
        return {
            'project': project,
            'work_item': work_item,
            'pr': pr,
            'conversation': conversation,
            'relationships': relationships,
            'people': self.people,
            'components': self.components
        }