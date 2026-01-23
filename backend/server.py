from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from typing import List, Dict, Any

# Import models and services
from models import (
    WorkItem, PullRequest, Conversation, ScopeDoc, Component,
    Person, Relationship, ChatRequest, ChatResponse, DocDriftAlert,
    ArtifactEvent, ArtifactType, RelationshipType
)
from database import db, COLLECTIONS, init_db, close_db
from postgres import (
    postgres_enabled,
    ensure_postgres_schema,
    postgres_connection,
    upsert_work_item,
    upsert_pull_request,
    upsert_conversation,
    insert_relationship,
    insert_artifact_event,
)
from mock_data_generator import MockDataGenerator
from doc_service import DocGenerationService, FreshnessDetectionService
from rag_service import RAGService
from ownership_service import OwnershipService
import anyio
import re

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Create the main app
app = FastAPI(title="ScopeDocs API", version="1.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Initialize services
doc_gen_service = DocGenerationService()
freshness_service = FreshnessDetectionService()
rag_service = RAGService()
ownership_service = OwnershipService()
mock_generator = MockDataGenerator()

issue_ref_pattern = re.compile(r"\b([A-Z]{2,}-\d+)\b")


def extract_issue_refs(text: str) -> List[str]:
    return list({match.group(1) for match in issue_ref_pattern.finditer(text or "")})


def _sync_postgres_work_item(work_item: Dict[str, Any], artifact_event: Dict[str, Any]) -> None:
    ensure_postgres_schema()
    with postgres_connection() as conn:
        upsert_work_item(conn, work_item)
        insert_artifact_event(conn, artifact_event)


def _sync_postgres_pull_request(
    pull_request: Dict[str, Any],
    relationships: List[Relationship],
    artifact_event: Dict[str, Any],
) -> None:
    ensure_postgres_schema()
    with postgres_connection() as conn:
        upsert_pull_request(conn, pull_request)
        for relationship in relationships:
            insert_relationship(conn, relationship.model_dump())
        insert_artifact_event(conn, artifact_event)


def _sync_postgres_conversation(conversation: Dict[str, Any], artifact_event: Dict[str, Any]) -> None:
    ensure_postgres_schema()
    with postgres_connection() as conn:
        upsert_conversation(conn, conversation)
        insert_artifact_event(conn, artifact_event)

# ===================
# MOCK DATA ENDPOINTS
# ===================

@api_router.post("/mock/generate-scenario")
async def generate_mock_scenario():
    """Generate a full mock scenario with all artifacts"""
    scenario = mock_generator.generate_full_scenario()
    
    # Save to database
    # Save people
    for person in scenario['people']:
        existing = await db[COLLECTIONS['people']].find_one({'external_id': person.external_id})
        if not existing:
            await db[COLLECTIONS['people']].insert_one(person.model_dump())
    
    # Save components
    for component in scenario['components']:
        existing = await db[COLLECTIONS['components']].find_one({'name': component.name})
        if not existing:
            await db[COLLECTIONS['components']].insert_one(component.model_dump())
    
    # Save work item
    await db[COLLECTIONS['work_items']].insert_one(scenario['work_item'].model_dump())
    
    # Save PR
    await db[COLLECTIONS['pull_requests']].insert_one(scenario['pr'].model_dump())
    
    # Save conversation
    await db[COLLECTIONS['conversations']].insert_one(scenario['conversation'].model_dump())
    
    # Save relationships
    for rel in scenario['relationships']:
        await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())
    
    return {
        'message': 'Mock scenario generated successfully',
        'project': scenario['project'],
        'work_item_id': scenario['work_item'].external_id,
        'pr_id': scenario['pr'].external_id,
        'conversation_id': scenario['conversation'].external_id
    }

@api_router.post("/mock/generate-multiple")
async def generate_multiple_scenarios(count: int = 5):
    """Generate multiple mock scenarios"""
    generated = []
    
    for i in range(count):
        scenario = mock_generator.generate_full_scenario()
        
        # Save people (only once)
        if i == 0:
            for person in scenario['people']:
                existing = await db[COLLECTIONS['people']].find_one({'external_id': person.external_id})
                if not existing:
                    await db[COLLECTIONS['people']].insert_one(person.model_dump())
            
            # Save components (only once)
            for component in scenario['components']:
                existing = await db[COLLECTIONS['components']].find_one({'name': component.name})
                if not existing:
                    await db[COLLECTIONS['components']].insert_one(component.model_dump())
        
        # Save artifacts
        await db[COLLECTIONS['work_items']].insert_one(scenario['work_item'].model_dump())
        await db[COLLECTIONS['pull_requests']].insert_one(scenario['pr'].model_dump())
        await db[COLLECTIONS['conversations']].insert_one(scenario['conversation'].model_dump())
        
        for rel in scenario['relationships']:
            await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())
        
        generated.append({
            'project': scenario['project']['name'],
            'work_item': scenario['work_item'].external_id
        })
    
    return {
        'message': f'Generated {count} mock scenarios',
        'scenarios': generated
    }

# ===================
# WEBHOOKS (INTEGRATIONS)
# ===================

@api_router.post("/webhooks/slack")
async def slack_webhook(payload: Dict[str, Any]):
    """Receive Slack events and persist them for integration testing."""
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})
    if not event:
        raise HTTPException(status_code=400, detail="Missing Slack event payload")

    thread_ts = event.get("thread_ts") or event.get("event_ts") or ""
    conversation = Conversation(
        external_id=thread_ts or event.get("event_ts", ""),
        channel=event.get("channel", "unknown"),
        thread_ts=thread_ts or event.get("event_ts", ""),
        messages=[event],
        participants=[event.get("user")] if event.get("user") else [],
        work_item_refs=extract_issue_refs(event.get("text", "")),
    )
    await db[COLLECTIONS['conversations']].insert_one(conversation.model_dump())

    artifact_event = ArtifactEvent(
        artifact_type=ArtifactType.SLACK_MESSAGE,
        artifact_id=conversation.id,
        data=payload,
        source="slack",
        metadata={"channel": conversation.channel, "event_id": payload.get("event_id")},
    )
    await db[COLLECTIONS['artifact_events']].insert_one(artifact_event.model_dump())

    if postgres_enabled():
        await anyio.to_thread.run_sync(
            _sync_postgres_conversation,
            conversation.model_dump(),
            artifact_event.model_dump(),
        )

    return {"status": "ok", "conversation_id": conversation.id}


@api_router.post("/webhooks/github")
async def github_webhook(payload: Dict[str, Any]):
    """Receive GitHub events and persist them for integration testing."""
    pr_payload = payload.get("pull_request")
    if not pr_payload:
        raise HTTPException(status_code=400, detail="Missing pull_request payload")

    status = "open"
    if payload.get("action") == "closed":
        status = "merged" if pr_payload.get("merged") else "closed"

    pr = PullRequest(
        external_id=str(pr_payload.get("number")),
        title=pr_payload.get("title", ""),
        description=pr_payload.get("body", ""),
        author=(pr_payload.get("user") or {}).get("login", "unknown"),
        status=status,
        repo=(payload.get("repository") or {}).get("full_name", "unknown"),
        files_changed=[],
        work_item_refs=extract_issue_refs(f"{pr_payload.get('title', '')}\n{pr_payload.get('body', '')}"),
        merged_at=pr_payload.get("merged_at"),
    )
    await db[COLLECTIONS['pull_requests']].insert_one(pr.model_dump())

    artifact_event = ArtifactEvent(
        artifact_type=ArtifactType.GITHUB_PR,
        artifact_id=pr.id,
        data=payload,
        source="github",
        metadata={"action": payload.get("action"), "delivery_id": payload.get("delivery_id")},
    )
    await db[COLLECTIONS['artifact_events']].insert_one(artifact_event.model_dump())

    relationships = []
    if pr.work_item_refs:
        work_items = await db[COLLECTIONS['work_items']].find(
            {"external_id": {"$in": pr.work_item_refs}},
            {"_id": 0},
        ).to_list(100)
        for item in work_items:
            rel = Relationship(
                source_id=item["id"],
                source_type="work_item",
                target_id=pr.id,
                target_type="pull_request",
                relationship_type=RelationshipType.IMPLEMENTS,
                evidence=[pr.external_id],
            )
            relationships.append(rel)
            await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())

    if postgres_enabled():
        await anyio.to_thread.run_sync(
            _sync_postgres_pull_request,
            pr.model_dump(),
            relationships,
            artifact_event.model_dump(),
        )

    return {"status": "ok", "pull_request_id": pr.id, "relationships": len(relationships)}


@api_router.post("/webhooks/linear")
async def linear_webhook(payload: Dict[str, Any]):
    """Receive Linear events and persist them for integration testing."""
    issue_payload = payload.get("data") or payload.get("issue") or {}
    if not issue_payload:
        raise HTTPException(status_code=400, detail="Missing Linear issue payload")

    work_item = WorkItem(
        external_id=issue_payload.get("identifier") or issue_payload.get("id") or "unknown",
        title=issue_payload.get("title", ""),
        description=issue_payload.get("description") or "",
        status=(issue_payload.get("state") or {}).get("name", issue_payload.get("state", "unknown")),
        team=(issue_payload.get("team") or {}).get("name"),
        assignee=(issue_payload.get("assignee") or {}).get("name"),
        project_id=(issue_payload.get("project") or {}).get("id"),
        labels=[label.get("name") for label in issue_payload.get("labels", []) if isinstance(label, dict)],
    )
    await db[COLLECTIONS['work_items']].insert_one(work_item.model_dump())

    artifact_event = ArtifactEvent(
        artifact_type=ArtifactType.LINEAR_ISSUE,
        artifact_id=work_item.id,
        data=payload,
        source="linear",
        metadata={"event_type": payload.get("type")},
    )
    await db[COLLECTIONS['artifact_events']].insert_one(artifact_event.model_dump())

    if postgres_enabled():
        await anyio.to_thread.run_sync(
            _sync_postgres_work_item,
            work_item.model_dump(),
            artifact_event.model_dump(),
        )

    return {"status": "ok", "work_item_id": work_item.id}

# ===================
# WORK ITEMS
# ===================

@api_router.get("/work-items", response_model=List[WorkItem])
async def get_work_items(project_id: str = None):
    """Get all work items, optionally filtered by project"""
    query = {}
    if project_id:
        query['project_id'] = project_id
    
    items = await db[COLLECTIONS['work_items']].find(query, {"_id": 0}).to_list(1000)
    return items

@api_router.get("/work-items/{item_id}", response_model=WorkItem)
async def get_work_item(item_id: str):
    """Get a specific work item"""
    item = await db[COLLECTIONS['work_items']].find_one({'id': item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found")
    return item

# ===================
# PULL REQUESTS
# ===================

@api_router.get("/pull-requests", response_model=List[PullRequest])
async def get_pull_requests(repo: str = None):
    """Get all pull requests, optionally filtered by repo"""
    query = {}
    if repo:
        query['repo'] = repo
    
    prs = await db[COLLECTIONS['pull_requests']].find(query, {"_id": 0}).to_list(1000)
    return prs

@api_router.get("/pull-requests/{pr_id}", response_model=PullRequest)
async def get_pull_request(pr_id: str):
    """Get a specific pull request"""
    pr = await db[COLLECTIONS['pull_requests']].find_one({'id': pr_id}, {"_id": 0})
    if not pr:
        raise HTTPException(status_code=404, detail="Pull request not found")
    return pr

# ===================
# CONVERSATIONS
# ===================

@api_router.get("/conversations", response_model=List[Conversation])
async def get_conversations(channel: str = None):
    """Get all conversations, optionally filtered by channel"""
    query = {}
    if channel:
        query['channel'] = channel
    
    conversations = await db[COLLECTIONS['conversations']].find(query, {"_id": 0}).to_list(1000)
    return conversations

# ===================
# SCOPEDOCS (Feature 1)
# ===================

@api_router.post("/scopedocs/generate")
async def generate_scopedoc(project_id: str, project_name: str):
    """Generate a ScopeDoc from a Linear project"""
    try:
        doc = await doc_gen_service.generate_doc_from_project(project_id, project_name)
        await db[COLLECTIONS['scopedocs']].insert_one(doc.model_dump())
        return {'message': 'Doc generated successfully', 'doc': doc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scopedocs", response_model=List[ScopeDoc])
async def get_scopedocs():
    """Get all ScopeDocs"""
    docs = await db[COLLECTIONS['scopedocs']].find({}, {"_id": 0}).to_list(1000)
    return docs

@api_router.get("/scopedocs/{doc_id}", response_model=ScopeDoc)
async def get_scopedoc(doc_id: str):
    """Get a specific ScopeDoc"""
    doc = await db[COLLECTIONS['scopedocs']].find_one({'id': doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="ScopeDoc not found")
    return doc

# ===================
# DOC FRESHNESS (Feature 2)
# ===================

@api_router.get("/freshness/{doc_id}")
async def check_doc_freshness(doc_id: str):
    """Check freshness of a specific doc"""
    try:
        result = await freshness_service.detect_drift(doc_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/freshness/check-all")
async def check_all_docs_freshness():
    """Check freshness of all docs"""
    docs = await db[COLLECTIONS['scopedocs']].find({}, {"_id": 0}).to_list(1000)
    
    results = []
    for doc_data in docs:
        doc = ScopeDoc(**doc_data)
        freshness_score = await freshness_service.calculate_freshness_score(doc)
        results.append({
            'doc_id': doc.id,
            'project_name': doc.project_name,
            'freshness_score': round(freshness_score, 2),
            'freshness_level': doc.freshness_level
        })
    
    return {'docs': results}

@api_router.post("/drift-alerts")
async def create_drift_alert(doc_id: str, trigger_pr_id: str):
    """Create a drift alert"""
    try:
        alert = await freshness_service.create_drift_alert(doc_id, trigger_pr_id)
        await db[COLLECTIONS['drift_alerts']].insert_one(alert.model_dump())
        return {'message': 'Alert created', 'alert': alert}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/drift-alerts", response_model=List[DocDriftAlert])
async def get_drift_alerts():
    """Get all drift alerts"""
    alerts = await db[COLLECTIONS['drift_alerts']].find({}, {"_id": 0}).to_list(1000)
    return alerts

# ===================
# ASK SCOPEY RAG (Feature 3)
# ===================

@api_router.post("/embeddings/generate-all")
async def generate_all_embeddings():
    """Generate embeddings for all artifacts"""
    try:
        # Clear existing embeddings
        await db[COLLECTIONS['embeddings']].delete_many({})
        
        result = await rag_service.embed_all_artifacts()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/ask-scopey", response_model=ChatResponse)
async def ask_scopey(request: ChatRequest):
    """Ask Scopey a question using RAG"""
    try:
        response = await rag_service.ask_scopey(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/search")
async def semantic_search(query: str, top_k: int = 5):
    """Semantic search across all artifacts"""
    try:
        results = await rag_service.semantic_search(query, top_k)
        return {'results': results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===================
# OWNERSHIP (Feature 4)
# ===================

@api_router.get("/ownership/{component_id}")
async def get_component_ownership(component_id: str):
    """Get ownership info for a component"""
    try:
        result = await ownership_service.resolve_ownership(component_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/ownership")
async def get_ownership_summary():
    """Get overall ownership summary"""
    try:
        result = await ownership_service.get_ownership_summary()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/components", response_model=List[Component])
async def get_components():
    """Get all components"""
    components = await db[COLLECTIONS['components']].find({}, {"_id": 0}).to_list(1000)
    return components

@api_router.get("/people", response_model=List[Person])
async def get_people():
    """Get all people"""
    people = await db[COLLECTIONS['people']].find({}, {"_id": 0}).to_list(1000)
    return people

# ===================
# RELATIONSHIPS
# ===================

@api_router.get("/relationships", response_model=List[Relationship])
async def get_relationships():
    """Get all relationships"""
    relationships = await db[COLLECTIONS['relationships']].find({}, {"_id": 0}).to_list(1000)
    return relationships

# ===================
# PROJECTS
# ===================

@api_router.get("/projects")
async def get_projects():
    """Get all unique projects from work items"""
    work_items = await db[COLLECTIONS['work_items']].find({}, {"_id": 0}).to_list(1000)
    
    projects_map = {}
    for item in work_items:
        project_id = item.get('project_id')
        if project_id and project_id not in projects_map:
            # Get project info from mock data
            from mock_data_generator import PROJECTS
            project_info = next((p for p in PROJECTS if p['id'] == project_id), None)
            if project_info:
                projects_map[project_id] = {
                    'id': project_id,
                    'name': project_info['name'],
                    'team': project_info['team'],
                    'work_items_count': 0
                }
        
        if project_id and project_id in projects_map:
            projects_map[project_id]['work_items_count'] += 1
    
    return {'projects': list(projects_map.values())}

# ===================
# STATS & DASHBOARD
# ===================

@api_router.get("/stats")
async def get_stats():
    """Get overall statistics"""
    stats = {
        'work_items': await db[COLLECTIONS['work_items']].count_documents({}),
        'pull_requests': await db[COLLECTIONS['pull_requests']].count_documents({}),
        'conversations': await db[COLLECTIONS['conversations']].count_documents({}),
        'scopedocs': await db[COLLECTIONS['scopedocs']].count_documents({}),
        'components': await db[COLLECTIONS['components']].count_documents({}),
        'people': await db[COLLECTIONS['people']].count_documents({}),
        'relationships': await db[COLLECTIONS['relationships']].count_documents({}),
        'embeddings': await db[COLLECTIONS['embeddings']].count_documents({}),
        'drift_alerts': await db[COLLECTIONS['drift_alerts']].count_documents({})
    }
    
    return stats

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_db():
    await init_db()
    if postgres_enabled():
        await anyio.to_thread.run_sync(ensure_postgres_schema)
    logger.info("Database initialized")

@app.on_event("shutdown")
async def shutdown_db():
    await close_db()
    logger.info("Database connection closed")
