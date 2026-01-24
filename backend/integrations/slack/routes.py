from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.database import db, COLLECTIONS
from backend.ingest.normalize import normalize_slack_event

router = APIRouter(prefix="/api/integrations/slack", tags=["integrations", "slack"])

ALLOWED_EVENTS = {"message", "app_mention"}


@router.post("/events")
async def handle_slack_events(payload: Dict[str, Any]):
    if payload.get('type') == 'url_verification':
        return {'challenge': payload.get('challenge')}

    event = payload.get('event')
    if not event:
        raise HTTPException(status_code=400, detail="Missing event payload")

    event_type = event.get('type')
    if event_type not in ALLOWED_EVENTS:
        return {'status': 'ignored', 'reason': f"Unsupported event type: {event_type}"}

    if event_type == 'message' and event.get('subtype'):
        return {'status': 'ignored', 'reason': f"Unsupported message subtype: {event.get('subtype')}"}

    conversation, relationships = await normalize_slack_event(event)

    existing = await db[COLLECTIONS['conversations']].find_one(
        {'external_id': conversation.external_id},
        {'_id': 0},
    )
    if existing:
        new_messages = existing.get('messages', []) + conversation.messages
        participants = list({*existing.get('participants', []), *conversation.participants})
        work_item_refs = list({*existing.get('work_item_refs', []), *conversation.work_item_refs})
        pr_refs = list({*existing.get('pr_refs', []), *conversation.pr_refs})
        await db[COLLECTIONS['conversations']].update_one(
            {'external_id': conversation.external_id},
            {
                '$set': {
                    'messages': new_messages,
                    'participants': participants,
                    'work_item_refs': work_item_refs,
                    'pr_refs': pr_refs,
                }
            },
        )
    else:
        await db[COLLECTIONS['conversations']].insert_one(conversation.model_dump())

    for rel in relationships:
        await db[COLLECTIONS['relationships']].insert_one(rel.model_dump())

    return {'status': 'ok'}
