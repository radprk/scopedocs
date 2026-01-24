# ScopeDocs

MVP backend for integrating GitHub, Slack, and Linear with OAuth and daily sync.

## Structure

```
backend/
├── server.py              # FastAPI app
├── models.py              # Pydantic models
├── storage/postgres.py    # Database layer (Supabase)
├── integrations/
│   ├── auth.py            # Token management
│   └── oauth/             # OAuth flow (Linear, GitHub, Slack)
├── sync/                  # Daily pull scripts
│   ├── sync_github.py
│   ├── sync_slack.py
│   └── sync_linear.py
└── ingest/normalize.py    # Data normalization

db/
└── schema.sql             # PostgreSQL schema
```

## Setup

1. Create virtual environment:
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Configure `backend/.env`:
```env
# Database
DATABASE_URL=postgresql://...@aws-0-us-west-1.pooler.supabase.com:5432/postgres

# Personal tokens (for testing)
LINEAR_ACCESS_TOKEN=lin_api_xxx
GITHUB_ACCESS_TOKEN=ghp_xxx
SLACK_ACCESS_TOKEN=xoxb-xxx

# OAuth (for production)
LINEAR_CLIENT_ID=xxx
LINEAR_CLIENT_SECRET=xxx
GITHUB_CLIENT_ID=xxx
GITHUB_CLIENT_SECRET=xxx
SLACK_CLIENT_ID=xxx
SLACK_CLIENT_SECRET=xxx

# URLs
BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
```

3. Run the schema in Supabase SQL Editor (from `db/schema.sql`)

4. Start the server:
```bash
uvicorn backend.server:app --reload
```

## API Endpoints

### OAuth
- `GET /api/oauth/{provider}/connect?workspace_id=xxx` - Start OAuth flow
- `GET /api/oauth/{provider}/callback` - OAuth callback
- `GET /api/oauth/status/{workspace_id}` - Check connection status
- `DELETE /api/oauth/{provider}/disconnect?workspace_id=xxx` - Disconnect

### Sync
- `POST /api/sync/github` - Sync GitHub PRs
- `POST /api/sync/slack` - Sync Slack conversations
- `POST /api/sync/linear` - Sync Linear issues
- `POST /api/sync/all` - Sync all integrations

### Health
- `GET /` - API info
- `GET /health` - Health check
