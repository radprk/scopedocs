from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import uuid
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Import models and services
from models import (
    WorkItem, PullRequest, Conversation, ScopeDoc, Component,
    Person, Relationship, ChatRequest, ChatResponse, DocDriftAlert,
    IngestionJobPayload, IngestionJob, IngestionJobType, IngestionJobStatus, IngestionSource
)
from database import db, COLLECTIONS, init_db, close_db
from mock_data_generator import MockDataGenerator
from doc_service import DocGenerationService, FreshnessDetectionService
from rag_service import RAGService
from ownership_service import OwnershipService
from integrations.slack.routes import router as slack_router
from integrations.github.routes import router as github_router
from integrations.linear.routes import router as linear_router

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
scheduler = AsyncIOScheduler(timezone="UTC")

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
# INGESTION JOBS (Feature 5)
# ===================

def serialize_payload(payload: IngestionJobPayload) -> Dict[str, Any]:
    return {
        "source": payload.source.value,
        "since": payload.since,
        "project_id": payload.project_id
    }

def build_job_key(job_type: IngestionJobType, payload: IngestionJobPayload) -> str:
    project_key = payload.project_id or "all"
    since_key = payload.since.isoformat()
    return f"{job_type.value}:{payload.source.value}:{project_key}:{since_key}"

async def upsert_ingestion_job(
    job_type: IngestionJobType,
    payload: IngestionJobPayload
) -> Dict[str, Any]:
    job_key = build_job_key(job_type, payload)
    now = datetime.utcnow()

    insert_doc = IngestionJob(
        id=str(uuid.uuid4()),
        job_key=job_key,
        job_type=job_type,
        payload=payload,
        status=IngestionJobStatus.QUEUED,
        created_at=now,
        updated_at=now
    ).model_dump()
    insert_doc["job_type"] = job_type.value
    insert_doc["payload"] = serialize_payload(payload)
    insert_doc["status"] = IngestionJobStatus.QUEUED.value

    update_doc = {
        "$set": {
            "job_key": job_key,
            "job_type": job_type.value,
            "payload": serialize_payload(payload),
            "updated_at": now
        },
        "$setOnInsert": insert_doc
    }
    await db[COLLECTIONS['ingestion_jobs']].update_one(
        {"job_key": job_key},
        update_doc,
        upsert=True
    )
    return await db[COLLECTIONS['ingestion_jobs']].find_one({"job_key": job_key}, {"_id": 0})

async def execute_ingestion_job(job_doc: Dict[str, Any]) -> Dict[str, Any]:
    if not job_doc:
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    checkpoint = job_doc.get("checkpoint")
    payload_since = job_doc.get("payload", {}).get("since")
    if (
        job_doc.get("status") == IngestionJobStatus.SUCCESS.value
        and checkpoint
        and payload_since
        and checkpoint >= payload_since
    ):
        return job_doc

    now = datetime.utcnow()
    await db[COLLECTIONS['ingestion_jobs']].update_one(
        {"job_key": job_doc["job_key"]},
        {
            "$set": {
                "status": IngestionJobStatus.RUNNING.value,
                "last_run_at": now,
                "updated_at": now
            },
            "$inc": {"attempts": 1}
        }
    )

    try:
        completed_at = datetime.utcnow()
        await db[COLLECTIONS['ingestion_jobs']].update_one(
            {"job_key": job_doc["job_key"]},
            {
                "$set": {
                    "status": IngestionJobStatus.SUCCESS.value,
                    "last_success_at": completed_at,
                    "checkpoint": completed_at,
                    "last_error": None,
                    "updated_at": completed_at
                }
            }
        )
    except Exception as exc:
        await db[COLLECTIONS['ingestion_jobs']].update_one(
            {"job_key": job_doc["job_key"]},
            {
                "$set": {
                    "status": IngestionJobStatus.FAILED.value,
                    "last_error": str(exc),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        raise

    return await db[COLLECTIONS['ingestion_jobs']].find_one({"job_key": job_doc["job_key"]}, {"_id": 0})

async def latest_refresh_checkpoint(source: IngestionSource, project_id: Optional[str] = None) -> Optional[datetime]:
    query: Dict[str, Any] = {
        "job_type": IngestionJobType.REFRESH.value,
        "payload.source": source.value,
        "checkpoint": {"$ne": None}
    }
    if project_id:
        query["payload.project_id"] = project_id
    job = await db[COLLECTIONS['ingestion_jobs']].find_one(
        query,
        sort=[("checkpoint", -1)],
        projection={"_id": 0, "checkpoint": 1}
    )
    return job["checkpoint"] if job else None

async def run_scheduled_refreshes():
    for source in IngestionSource:
        last_checkpoint = await latest_refresh_checkpoint(source)
        since = last_checkpoint or (datetime.utcnow() - timedelta(days=1))
        payload = IngestionJobPayload(source=source, since=since)
        job_doc = await upsert_ingestion_job(IngestionJobType.REFRESH, payload)
        await execute_ingestion_job(job_doc)

@api_router.post("/ingest/refresh", response_model=IngestionJob)
async def refresh_ingestion(payload: IngestionJobPayload):
    """Queue and run a refresh ingestion job."""
    job_doc = await upsert_ingestion_job(IngestionJobType.REFRESH, payload)
    return await execute_ingestion_job(job_doc)

@api_router.post("/ingest/backfill", response_model=IngestionJob)
async def backfill_ingestion(payload: IngestionJobPayload):
    """Queue and run a backfill ingestion job."""
    job_doc = await upsert_ingestion_job(IngestionJobType.BACKFILL, payload)
    return await execute_ingestion_job(job_doc)

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
app.include_router(slack_router)
app.include_router(github_router)
app.include_router(linear_router)

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
    scheduler.add_job(run_scheduled_refreshes, CronTrigger(hour=0, minute=0))
    scheduler.start()
    await run_scheduled_refreshes()
    logger.info("Database initialized")

@app.on_event("shutdown")
async def shutdown_db():
    scheduler.shutdown()
    await close_db()
    logger.info("Database connection closed")
