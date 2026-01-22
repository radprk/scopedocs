from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Collection names
COLLECTIONS = {
    'artifact_events': 'artifact_events',
    'work_items': 'work_items',
    'pull_requests': 'pull_requests',
    'conversations': 'conversations',
    'scopedocs': 'scopedocs',
    'components': 'components',
    'people': 'people',
    'relationships': 'relationships',
    'embeddings': 'embeddings',
    'drift_alerts': 'drift_alerts'
}

async def init_db():
    """Initialize database with indexes"""
    # Create indexes for better query performance
    await db[COLLECTIONS['artifact_events']].create_index('artifact_id')
    await db[COLLECTIONS['artifact_events']].create_index('artifact_type')
    await db[COLLECTIONS['work_items']].create_index('external_id')
    await db[COLLECTIONS['pull_requests']].create_index('external_id')
    await db[COLLECTIONS['conversations']].create_index('external_id')
    await db[COLLECTIONS['scopedocs']].create_index('project_id')
    await db[COLLECTIONS['relationships']].create_index([('source_id', 1), ('target_id', 1)])
    await db[COLLECTIONS['embeddings']].create_index('artifact_id')

async def close_db():
    """Close database connection"""
    client.close()