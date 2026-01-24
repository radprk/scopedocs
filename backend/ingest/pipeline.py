from typing import Any, Dict, Iterable, List, Mapping

from backend.database import COLLECTIONS
from backend.storage.postgres import (
    upsert_artifact_event,
    upsert_component,
    upsert_conversation,
    upsert_drift_alert,
    upsert_embedding,
    upsert_person,
    upsert_pull_request,
    upsert_relationship,
    upsert_scopedoc,
    upsert_work_item,
)

POSTGRES_UPSERTS = {
    COLLECTIONS["work_items"]: upsert_work_item,
    COLLECTIONS["pull_requests"]: upsert_pull_request,
    COLLECTIONS["conversations"]: upsert_conversation,
    COLLECTIONS["scopedocs"]: upsert_scopedoc,
    COLLECTIONS["components"]: upsert_component,
    COLLECTIONS["people"]: upsert_person,
    COLLECTIONS["relationships"]: upsert_relationship,
    COLLECTIONS["artifact_events"]: upsert_artifact_event,
    COLLECTIONS["embeddings"]: upsert_embedding,
    COLLECTIONS["drift_alerts"]: upsert_drift_alert,
}


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    return dict(payload)


async def ingest_records(
    records_by_collection: Mapping[str, Iterable[Any]],
) -> None:
    """Ingest records into PostgreSQL database"""
    for collection, records in records_by_collection.items():
        normalized: List[Dict[str, Any]] = [_normalize_payload(record) for record in records]
        upsert_func = POSTGRES_UPSERTS.get(collection)
        if upsert_func:
            for record in normalized:
                await upsert_func(record)
