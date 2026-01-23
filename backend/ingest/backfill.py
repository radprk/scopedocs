import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from backend.database import COLLECTIONS, db, init_db, close_db
from backend.storage.postgres import init_pg, set_integration_state, close_pool
from backend.ingest.pipeline import ingest_records

BACKFILL_COLLECTIONS = [
    COLLECTIONS["work_items"],
    COLLECTIONS["pull_requests"],
    COLLECTIONS["conversations"],
    COLLECTIONS["scopedocs"],
    COLLECTIONS["components"],
    COLLECTIONS["people"],
    COLLECTIONS["relationships"],
    COLLECTIONS["artifact_events"],
    COLLECTIONS["embeddings"],
    COLLECTIONS["drift_alerts"],
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill data into Postgres")
    parser.add_argument("--source", required=True, help="Source system name (github, slack, linear)")
    parser.add_argument("--since", help="ISO date (YYYY-MM-DD) to backfill from")
    parser.add_argument("--days", type=int, default=90, help="Days to look back if --since not provided")
    parser.add_argument("--mongo-only", action="store_true", help="Skip Postgres writes")
    return parser.parse_args()


def _since_datetime(args: argparse.Namespace) -> datetime:
    if args.since:
        return datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    return datetime.now(tz=timezone.utc) - timedelta(days=args.days)


def _filter_by_since(records: Iterable[Dict[str, Any]], since: datetime) -> List[Dict[str, Any]]:
    filtered = []
    for record in records:
        created_at = record.get("created_at") or record.get("updated_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = None
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at and created_at >= since:
            filtered.append(record)
        elif created_at is None:
            filtered.append(record)
    return filtered


async def _fetch_collection(collection: str, since: datetime) -> List[Dict[str, Any]]:
    query = {"created_at": {"$gte": since}}
    cursor = db[collection].find(query, {"_id": 0})
    results = await cursor.to_list(None)
    if results:
        return results
    cursor = db[collection].find({}, {"_id": 0})
    results = await cursor.to_list(None)
    return _filter_by_since(results, since)


async def run_backfill() -> None:
    args = _parse_args()
    since = _since_datetime(args)

    await init_db()
    await init_pg()

    records_by_collection: Dict[str, List[Dict[str, Any]]] = {}
    for collection in BACKFILL_COLLECTIONS:
        records_by_collection[collection] = await _fetch_collection(collection, since)

    await ingest_records(
        records_by_collection,
        write_postgres=not args.mongo_only,
        write_mongo=True,
    )

    await set_integration_state(args.source, "last_timestamp", since.isoformat())
    await set_integration_state(args.source, "last_cursor", None)

    await close_db()
    await close_pool()


if __name__ == "__main__":
    asyncio.run(run_backfill())
