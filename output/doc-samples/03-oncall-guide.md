# ScopeDocs On-Call Guide 🚨

> **Style:** On-Call / Incident Response
> **Best for:** Quick debugging, understanding what can break

---

## TL;DR

ScopeDocs is a RAG-based documentation generator.

**Critical components:**
- PostgreSQL/Supabase (stores embeddings)
- Together.ai API (generates embeddings and docs)
- GitHub API (fetches code)

**If docs aren't generating:** Check Together.ai API key and rate limits.
**If search returns nothing:** Check if embeddings exist in `code_embeddings` table.
**If OAuth fails:** Check provider credentials in environment.

---

## Critical Path

```
Request → FastAPI → RAG Search → Together.ai → Response
           ↓           ↓             ↓
       Postgres    Postgres      External
       (tokens)   (embeddings)    (API)
```

**What MUST work:**
1. PostgreSQL connection (env: `DATABASE_URL`)
2. Together.ai API (env: `TOGETHER_API_KEY`)
3. GitHub OAuth token (stored in `oauth_tokens` table)

---

## Common Failure Modes

### 1. "No code chunks found" Error
**Symptom:** `/api/ai/generate-adaptive-doc` returns 404
**Cause:** No embeddings in database for this repo
**Fix:**
```bash
# Check if embeddings exist
psql $DATABASE_URL -c "SELECT COUNT(*) FROM code_embeddings WHERE repo_full_name = 'owner/repo';"

# If 0: Run indexing first
POST /api/index/repo {"workspace_id": "...", "repo_full_name": "owner/repo"}
POST /api/index/embed {"workspace_id": "...", "repo_full_name": "owner/repo"}
```

### 2. Together.ai API Errors
**Symptom:** 500 errors on `/api/ai/*` endpoints
**Cause:** API key invalid, rate limited, or model unavailable
**Fix:**
```bash
# Test API key
curl -H "Authorization: Bearer $TOGETHER_API_KEY" https://api.together.xyz/v1/models

# Check logs for specific error
grep "Together.ai error" server.log
```
**Rate limits:** 60 requests/minute for embeddings, check response headers.

### 3. GitHub OAuth Expired
**Symptom:** "GitHub not connected" errors
**Cause:** Token in `oauth_tokens` table is expired or revoked
**Fix:**
```sql
-- Check token status
SELECT expires_at, created_at FROM oauth_tokens
WHERE workspace_id = 'xxx' AND provider = 'github';

-- If expired: User needs to re-authenticate at /api/oauth/github/connect
```

### 4. PostgreSQL Connection Issues
**Symptom:** 500 errors across all endpoints
**Cause:** Database connection pool exhausted or connection string wrong
**Check:**
```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1;"

# Check pool status in logs
grep "PostgreSQL" server.log
```

### 5. Slow Response Times
**Symptom:** Requests taking >30 seconds
**Cause:** Usually Together.ai embedding/generation latency
**Check:**
- Together.ai status page
- Request batch sizes (we batch 20 chunks at a time)
- pgvector index existence

---

## Dependencies

### External Services

| Service | Purpose | Health Check |
|---------|---------|--------------|
| PostgreSQL/Supabase | Data storage | `GET /health` |
| Together.ai | AI embeddings & generation | `GET /api/ai/health` |
| GitHub API | Code fetching | OAuth connection status |
| Slack API | (Phase 2) | OAuth connection status |
| Linear API | (Phase 2) | OAuth connection status |

### Internal Dependencies

```
/api/ai/generate-adaptive-doc
  └── requires: code_embeddings table populated
        └── requires: /api/index/embed ran successfully
              └── requires: /api/index/repo ran successfully
                    └── requires: GitHub OAuth connected
```

---

## Key Metrics & Logs

### What to Watch

```bash
# Embedding count (should be non-zero)
psql $DATABASE_URL -c "SELECT repo_full_name, COUNT(*) FROM code_embeddings GROUP BY 1;"

# Recent errors in logs
grep -i "error" server.log | tail -50

# Together.ai response times
grep "Calling LLM" server.log | tail -20
```

### Log Patterns

| Pattern | Meaning |
|---------|---------|
| `[API] POST /api/ai/generate-adaptive-doc` | Request received |
| `search_query:` | Query being embedded |
| `Calling LLM with N code references` | About to call Together.ai |
| `Generated doc: N chars` | Success |
| `LLM error:` | Together.ai failure |
| `Together.ai error (429)` | Rate limited |

---

## Quick Fixes

### Restart the Server
```bash
pkill -f "uvicorn server:app"
cd backend && uvicorn server:app --reload --port 8000
```

### Clear and Re-index
```bash
# Nuclear option: clear all embeddings for a repo
psql $DATABASE_URL -c "DELETE FROM code_embeddings WHERE repo_full_name = 'owner/repo';"

# Re-index
curl -X POST http://localhost:8000/api/index/repo \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "xxx", "repo_full_name": "owner/repo"}'

curl -X POST http://localhost:8000/api/index/embed \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "xxx", "repo_full_name": "owner/repo"}'
```

### Test Individual Components
```bash
# Test database
curl http://localhost:8000/health

# Test AI service
curl http://localhost:8000/api/ai/health

# Test OAuth status
curl http://localhost:8000/api/oauth/status/{workspace_id}
```

---

## Escalation

| Issue | Owner | Contact |
|-------|-------|---------|
| Backend/API | Platform team | #platform-oncall |
| Together.ai | AI team | #ai-eng |
| Database | Infra | #infra-oncall |
| OAuth/Integrations | Platform team | #platform-oncall |

---

## Environment Variables (Quick Reference)

```bash
DATABASE_URL=postgresql://...          # REQUIRED
TOGETHER_API_KEY=...                   # REQUIRED for AI
GITHUB_CLIENT_ID=...                   # For GitHub OAuth
GITHUB_CLIENT_SECRET=...               # For GitHub OAuth
CORS_ORIGINS=*                         # Optional
```

---
*Generated with On-Call Guide style*
