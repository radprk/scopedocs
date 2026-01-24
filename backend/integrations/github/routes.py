from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from backend.database import db, COLLECTIONS
from backend.ingest.normalize import (
    normalize_github_pull_request,
    normalize_github_review,
    normalize_github_push,
)

router = APIRouter(prefix="/api/integrations/github", tags=["integrations", "github"])


@router.post("/webhook")
async def handle_github_webhook(request: Request):
    payload: Dict[str, Any] = await request.json()
    event_type = request.headers.get('X-GitHub-Event')
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    if event_type == 'pull_request':
        pr, relationships = await normalize_github_pull_request(payload)
        await db[COLLECTIONS['pull_requests']].update_one(
            {'external_id': pr.external_id},
            {'$set': pr.model_dump()},
            upsert=True,
        )
        for rel in relationships:
            await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())
        return {'status': 'ok', 'event': event_type}

    if event_type == 'pull_request_review':
        pr = await normalize_github_review(payload)
        if pr:
            existing = await db[COLLECTIONS['pull_requests']].find_one(
                {'external_id': pr.external_id},
                {'_id': 0},
            )
            if existing:
                reviewers = list({*existing.get('reviewers', []), *pr.reviewers})
                await db[COLLECTIONS['pull_requests']].update_one(
                    {'external_id': pr.external_id},
                    {'$set': {'reviewers': reviewers}},
                )
            else:
                await db[COLLECTIONS['pull_requests']].insert_one(pr.model_dump())
        return {'status': 'ok', 'event': event_type}

    if event_type == 'push':
        relationships = await normalize_github_push(payload)
        for rel in relationships:
            await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())
        return {'status': 'ok', 'event': event_type}

    return {'status': 'ignored', 'event': event_type}
