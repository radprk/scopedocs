"""
ScopeDocs API Server - Minimal MVP
OAuth + Database + Sync workflows only
"""
from fastapi import FastAPI
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path

# Import routers
from backend.sync.routes import router as sync_router
from backend.integrations.oauth.routes import router as oauth_router
from backend.storage.postgres import init_pg, close_pool

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Create the main app
app = FastAPI(title="ScopeDocs API", version="1.0.0")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Include routers
app.include_router(sync_router)
app.include_router(oauth_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": "ScopeDocs API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "oauth": "/api/oauth/{provider}/connect",
            "sync": "/api/sync/{integration}",
            "health": "/health"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.on_event("startup")
async def startup():
    try:
        await init_pg()
        logger.info("PostgreSQL database initialized")
    except Exception as e:
        logger.warning(f"Database not available: {e}")
        logger.info("Running without database - OAuth testing still works")


@app.on_event("shutdown")
async def shutdown():
    await close_pool()
    logger.info("Database connection closed")
