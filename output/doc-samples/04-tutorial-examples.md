# ScopeDocs Tutorial: Building Your First Adaptive Doc 🎯

> **Style:** Tutorial & Examples
> **Best for:** Hands-on learning, getting started quickly

---

## What You'll Build

By the end of this tutorial, you'll:
1. Set up ScopeDocs locally
2. Connect a GitHub repository
3. Index code and generate embeddings
4. Generate adaptive documentation for different audiences
5. Understand how to customize prompts

**Prerequisites:**
- Python 3.11+
- PostgreSQL or Supabase account
- Together.ai API key (free tier works)
- A GitHub account

---

## Step 1: Get the Server Running

### Clone and Install

```bash
git clone https://github.com/your-org/scopedocs.git
cd scopedocs/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure Environment

Create `backend/.env`:

```bash
# Database (get from Supabase dashboard)
DATABASE_URL=postgresql://postgres:password@db.xxxx.supabase.co:5432/postgres

# Together.ai (get from https://api.together.xyz/settings/api-keys)
TOGETHER_API_KEY=your-key-here

# GitHub OAuth (create app at https://github.com/settings/developers)
GITHUB_CLIENT_ID=your-client-id
GITHUB_CLIENT_SECRET=your-client-secret
```

### Start the Server

```bash
uvicorn server:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
[AI] AI routes enabled - TOGETHER_API_KEY is set
```

### Try It

Open http://localhost:8000 - you should see:
```json
{
  "name": "ScopeDocs API",
  "status": "running",
  "ai_enabled": true
}
```

---

## Step 2: Create a Workspace and Connect GitHub

### Create Your First Workspace

```bash
curl -X POST http://localhost:8000/api/workspaces \
  -H "Content-Type: application/json" \
  -d '{"name": "My First Workspace", "slug": "my-workspace"}'
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My First Workspace",
  "slug": "my-workspace"
}
```

Save the `id` - you'll need it!

### Connect GitHub

1. Open http://localhost:8000/ui
2. Select your workspace from the dropdown
3. Click "Connect" on the GitHub card
4. Authorize the OAuth app
5. You'll be redirected back - GitHub should show "Connected" ✅

---

## Step 3: Index a Repository

Now let's index some code! We'll use a small public repo.

### Index the Repo

```bash
# Replace with your workspace_id
WORKSPACE_ID="550e8400-e29b-41d4-a716-446655440000"

curl -X POST http://localhost:8000/api/index/repo \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"branch\": \"master\"
  }"
```

**Expected Output:**
```json
{
  "status": "success",
  "stats": {
    "files_indexed": 42,
    "chunks_created": 156
  }
}
```

### Generate Embeddings

```bash
curl -X POST http://localhost:8000/api/index/embed \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\"
  }"
```

**Expected Output:**
```json
{
  "status": "success",
  "new_embeddings": 156,
  "total_embeddings": 156
}
```

---

## Step 4: Generate Your First Adaptive Doc

### Traditional Wiki Style

```bash
curl -X POST http://localhost:8000/api/ai/generate-adaptive-doc \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"audience_type\": \"traditional\",
    \"style\": \"reference\"
  }"
```

**What You Get:** Complete reference documentation with API details.

### New Engineer View

```bash
curl -X POST http://localhost:8000/api/ai/generate-adaptive-doc \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"audience_type\": \"new_engineer\",
    \"style\": \"narrative\",
    \"role\": \"backend developer\",
    \"team\": \"the API team\"
  }"
```

**What You Get:** A friendly, top-down explanation starting with the big picture.

### On-Call Emergency Mode

```bash
curl -X POST http://localhost:8000/api/ai/generate-adaptive-doc \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"audience_type\": \"oncall\",
    \"style\": \"concise\",
    \"purpose\": \"routing middleware\"
  }"
```

**What You Get:** Quick, actionable information focused on the specific component.

### Custom Purpose

```bash
curl -X POST http://localhost:8000/api/ai/generate-adaptive-doc \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"audience_type\": \"custom\",
    \"custom_context\": \"I am a security researcher looking for input validation and sanitization patterns in the request handling code\"
  }"
```

**What You Get:** Documentation specifically tailored to your stated purpose.

---

## Step 5: Try the UI

The web interface makes this even easier:

1. Go to http://localhost:8000/docs
2. Select your workspace
3. Select the repo you indexed
4. Choose an audience type (click one of the cards)
5. Choose a style (Narrative, Concise, Reference, Tutorial)
6. Click "Generate Documentation"

The documentation appears with clickable code references!

---

## Step 6: Customize the Prompts

The magic happens in `backend/ai/prompts.py`. Let's add a custom audience!

### Add a New Audience Type

Edit `prompts.py`:

```python
# Add to AudienceType enum
class AudienceType(str, Enum):
    TRADITIONAL = "traditional"
    NEW_ENGINEER = "new_engineer"
    ONCALL = "oncall"
    CUSTOM = "custom"
    SECURITY_REVIEWER = "security_reviewer"  # NEW!

# Add to SYSTEM_PROMPTS
SYSTEM_PROMPTS = {
    # ... existing prompts ...

    AudienceType.SECURITY_REVIEWER: """You are a security expert reviewing code.
Focus on:
- Input validation and sanitization
- Authentication and authorization patterns
- Potential injection vulnerabilities
- Secret handling and data exposure risks
- Rate limiting and abuse prevention
Write documentation that highlights security-relevant patterns and potential issues."""
}
```

### Test Your New Audience

```bash
curl -X POST http://localhost:8000/api/ai/generate-adaptive-doc \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"audience_type\": \"security_reviewer\",
    \"style\": \"concise\"
  }"
```

---

## Common Patterns

### Pattern 1: Generating Docs for a Specific File

```bash
curl -X POST http://localhost:8000/api/ai/generate-adaptive-doc \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"repo_full_name\": \"expressjs/express\",
    \"audience_type\": \"traditional\",
    \"file_path\": \"lib/router/index.js\"
  }"
```

### Pattern 2: Using Search Directly

```bash
curl -X POST http://localhost:8000/api/ai/search \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"query\": \"error handling middleware\",
    \"top_k\": 5
  }"
```

### Pattern 3: Chaining Docs (Deep Dive)

First, generate a high-level view:
```bash
# Get overview
curl ... audience_type=new_engineer

# Response includes suggested_next: ["Deep dive: router.js", ...]
```

Then generate focused docs:
```bash
# Dive into specific component
curl ... custom_context="Deep dive into the routing system"
```

---

## Troubleshooting

### "No code chunks found"
Run indexing first:
```bash
POST /api/index/repo
POST /api/index/embed
```

### "Together.ai error"
Check your API key:
```bash
echo $TOGETHER_API_KEY
curl -H "Authorization: Bearer $TOGETHER_API_KEY" https://api.together.xyz/v1/models
```

### "GitHub not connected"
Re-authenticate at `/api/oauth/github/connect?workspace_id=...`

---

## Next Steps

1. **Try different repositories** - Index your own repos!
2. **Experiment with styles** - See how `concise` vs `narrative` changes output
3. **Create custom audiences** - Add specialized views for your team
4. **Explore the code** - ScopeDocs is designed to document itself

---

## Quick Command Reference

```bash
# Create workspace
POST /api/workspaces {"name": "...", "slug": "..."}

# Index repo
POST /api/index/repo {"workspace_id": "...", "repo_full_name": "..."}

# Generate embeddings
POST /api/index/embed {"workspace_id": "...", "repo_full_name": "..."}

# Generate adaptive docs
POST /api/ai/generate-adaptive-doc {
  "workspace_id": "...",
  "repo_full_name": "...",
  "audience_type": "new_engineer|oncall|traditional|custom",
  "style": "narrative|concise|reference|tutorial",
  "custom_context": "...",  # For custom audience
  "purpose": "..."          # Focus area
}

# Search code
POST /api/ai/search {"workspace_id": "...", "query": "...", "top_k": 5}
```

---
*Generated with Tutorial & Examples style*
