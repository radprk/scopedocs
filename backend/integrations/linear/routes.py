from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException

from backend.database import db, COLLECTIONS
from backend.ingest.normalize import normalize_linear_issue
from backend.integrations.auth import build_token_from_env, get_integration_token

router = APIRouter(prefix="/api/integrations/linear", tags=["integrations", "linear"])

LINEAR_API_URL = "https://api.linear.app/graphql"


@router.post("/webhook")
async def handle_linear_webhook(payload: Dict[str, Any]):
    issue_data = payload.get('data') or payload.get('issue') or payload
    if not isinstance(issue_data, dict):
        raise HTTPException(status_code=400, detail="Invalid Linear payload")

    work_item, relationships = await normalize_linear_issue(issue_data)
    await db[COLLECTIONS['work_items']].update_one(
        {'external_id': work_item.external_id},
        {'$set': work_item.model_dump()},
        upsert=True,
    )
    for rel in relationships:
        await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())

    return {'status': 'ok'}


@router.post("/poll")
async def poll_linear_updates(workspace_id: str, updated_since: Optional[str] = None):
    token = await get_integration_token('linear', workspace_id)
    if not token:
        token = build_token_from_env('linear', workspace_id)
    if not token:
        raise HTTPException(status_code=400, detail="Linear token not configured")

    since_value = updated_since or datetime.utcnow().isoformat()
    query = """
    query Issues($updatedSince: DateTime) {
        issues(filter: { updatedAt: { gt: $updatedSince } }) {
            nodes {
                id
                identifier
                title
                description
                updatedAt
                createdAt
                state { name }
                team { id name }
                assignee { name }
                project { id }
                labels { nodes { name } }
            }
        }
    }
    """
    variables = {'updatedSince': since_value}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            LINEAR_API_URL,
            headers={'Authorization': token.access_token},
            json={'query': query, 'variables': variables},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    data = response.json()
    if 'errors' in data:
        raise HTTPException(status_code=400, detail=data['errors'])

    issues = data.get('data', {}).get('issues', {}).get('nodes', [])
    stored = 0
    for issue in issues:
        work_item, relationships = await normalize_linear_issue(issue)
        await db[COLLECTIONS['work_items']].update_one(
            {'external_id': work_item.external_id},
            {'$set': work_item.model_dump()},
            upsert=True,
        )
        for rel in relationships:
            await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())
        stored += 1

    return {'status': 'ok', 'stored': stored, 'updated_since': since_value}
