# ScopeDocs Local Testing Guide

This guide will help you set up and test ScopeDocs on your local machine using Supabase as the database.

## Prerequisites

- **Python 3.11+** installed
- **Node.js 18+** installed
- **A Supabase account** (free tier works great)

## Step 1: Set Up Supabase

1. Go to [https://supabase.com](https://supabase.com) and create an account
2. Click "New Project"
3. Fill in:
   - **Project name**: `scopedocs` (or any name you like)
   - **Database password**: Create a strong password (save this!)
   - **Region**: Choose the closest to you
4. Wait for the project to be created (takes ~2 minutes)

### Get Your Connection String

1. In your Supabase project, go to **Settings** (gear icon in sidebar)
2. Click **Database**
3. Scroll down to **Connection string**
4. Select **URI** tab
5. Copy the string - it looks like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxxx.supabase.co:5432/postgres
   ```
6. Replace `[YOUR-PASSWORD]` with your actual database password

## Step 2: Set Up the Backend

### 2.1 Navigate to Backend Directory

```bash
cd /home/user/scopedocs/backend
```

### 2.2 Create Python Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# On Mac/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### 2.3 Install Dependencies

```bash
pip install -r requirements.txt
```

### 2.4 Create Environment File

```bash
# Copy the example file
cp .env.example .env

# Edit the .env file with your Supabase connection string
# You can use any text editor:
nano .env
# or
code .env
```

Your `.env` file should look like:
```
POSTGRES_DSN=postgresql://postgres:YOUR_PASSWORD@db.xxxxx.supabase.co:5432/postgres
CORS_ORIGINS=*
```

### 2.5 Start the Backend Server

```bash
uvicorn backend.server:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     PostgreSQL database initialized
```

### 2.6 Test the Backend

Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser.
You should see the FastAPI Swagger documentation.

## Step 3: Set Up the Frontend

Open a **new terminal** (keep the backend running).

### 3.1 Navigate to Frontend Directory

```bash
cd /home/user/scopedocs/frontend
```

### 3.2 Install Dependencies

```bash
npm install
```

### 3.3 Start the Frontend

```bash
REACT_APP_BACKEND_URL=http://localhost:8000 npm start
```

This will open [http://localhost:3000](http://localhost:3000) in your browser.

## Step 4: Test the Application

### Generate Mock Data

1. Go to the **Dashboard** (home page)
2. Click **"Generate Mock Data"** button
3. This creates:
   - Fake Linear issues (work items)
   - Fake GitHub PRs
   - Fake Slack conversations
   - People and components

### Check Supabase

1. Go to your Supabase dashboard
2. Click **Table Editor** in the sidebar
3. You should see tables with data:
   - `work_items` - Linear issues
   - `pull_requests` - GitHub PRs
   - `conversations` - Slack messages
   - `people` - Team members
   - `components` - Services/APIs
   - `relationships` - Connections between artifacts

### Test Document Generation

1. Go to **Projects** page
2. You'll see projects created from mock data
3. Click **"Generate ScopeDoc"** on any project
4. Go to **Docs** page to see the generated documentation

### Test Ask Scopey (AI Chatbot)

1. Go to **Ask Scopey** page
2. Click **"Generate Embeddings"** first (wait for it to complete)
3. Type a question like "What are the main projects?"
4. The chatbot will search your data and respond

## Testing Webhooks (Advanced)

If you want to test real Slack/GitHub/Linear webhooks:

### Option A: Use ngrok (Recommended)

```bash
# Install ngrok
# Mac: brew install ngrok
# Other: download from https://ngrok.com

# Start your backend first, then:
ngrok http 8000
```

ngrok gives you a public URL like `https://abc123.ngrok.io`

### Configuring Webhooks

**Slack:**
1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create a new app or select existing
3. Enable "Event Subscriptions"
4. Set Request URL: `https://YOUR-NGROK.ngrok.io/api/integrations/slack/events`
5. Subscribe to: `message.channels`, `app_mention`

**Linear:**
1. Go to Linear > Settings > API > Webhooks
2. Create webhook with URL: `https://YOUR-NGROK.ngrok.io/api/integrations/linear/webhook`
3. Select events: Issue created, Issue updated

**GitHub:**
1. Go to your repo > Settings > Webhooks
2. Add webhook with URL: `https://YOUR-NGROK.ngrok.io/api/integrations/github/webhook`
3. Select: Pull requests events

### Option B: Test with curl (Without Real Webhooks)

You can simulate webhooks using curl:

```bash
# Simulate a Slack message
curl -X POST http://localhost:8000/api/integrations/slack/events \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "type": "message",
      "text": "We decided to use React for the frontend LIN-123",
      "user": "U123",
      "channel": "C123",
      "ts": "1234567890.123456",
      "thread_ts": "1234567890.123456"
    }
  }'

# Simulate a GitHub PR
curl -X POST http://localhost:8000/api/integrations/github/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -d '{
    "action": "opened",
    "pull_request": {
      "number": 42,
      "title": "Fix authentication bug [LIN-123]",
      "body": "This PR fixes the login issue",
      "html_url": "https://github.com/org/repo/pull/42",
      "user": {"login": "developer"},
      "head": {"ref": "fix-auth"},
      "base": {"ref": "main"},
      "state": "open"
    },
    "repository": {"full_name": "org/repo"}
  }'

# Simulate a Linear issue update
curl -X POST http://localhost:8000/api/integrations/linear/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "id": "abc123",
      "identifier": "LIN-456",
      "title": "Implement new feature",
      "description": "This is a test issue",
      "state": {"name": "In Progress"},
      "team": {"name": "Engineering"},
      "assignee": {"name": "Alice"},
      "project": {"id": "proj-1"}
    }
  }'
```

## Quick Test Checklist

| Test | Command/Action | Expected Result |
|------|----------------|-----------------|
| Backend running | Visit `http://localhost:8000/docs` | See FastAPI docs |
| Frontend running | Visit `http://localhost:3000` | See dashboard |
| Database connected | Check backend terminal | No connection errors |
| Mock data | Click "Generate Mock Data" | Stats increase on dashboard |
| Supabase data | Check Table Editor | See rows in tables |
| Doc generation | Projects → Generate ScopeDoc | New doc in Docs page |
| AI chatbot | Ask Scopey → Generate Embeddings → Ask question | Get a response |

## Troubleshooting

### "POSTGRES_DSN not set" Error
- Make sure your `.env` file exists in the `backend` folder
- Make sure it contains `POSTGRES_DSN=...` with your Supabase connection string

### Connection Refused
- Check that the backend is running on port 8000
- Check that your Supabase project is active (not paused)

### Tables Not Created
- Tables are created automatically when the backend starts
- Check the backend terminal for any errors
- In Supabase, you can manually run the SQL from `storage/postgres.py` if needed

### Frontend Can't Connect to Backend
- Make sure `REACT_APP_BACKEND_URL=http://localhost:8000` is set when starting frontend
- Check browser console for CORS errors

### "Module not found" Errors
- Make sure you activated the virtual environment: `source venv/bin/activate`
- Try reinstalling dependencies: `pip install -r requirements.txt`

## What Each Feature Does

| Feature | What It Does | How to Test |
|---------|-------------|-------------|
| **Mock Data** | Creates fake Slack/GitHub/Linear data | Dashboard → Generate Mock Data |
| **Projects** | Lists all Linear projects | Click Projects in sidebar |
| **ScopeDoc Generation** | Auto-generates documentation from project data | Projects → Generate ScopeDoc |
| **Doc Freshness** | Tracks if docs are outdated | Docs page shows Fresh/Stale/Outdated |
| **Ask Scopey** | AI chatbot that answers questions about your codebase | Ask Scopey page |
| **Ownership** | Tracks who owns what components | Ownership page |

## Architecture Summary

```
┌─────────────────────┐      ┌─────────────────────┐
│   React Frontend    │      │     Supabase        │
│   (localhost:3000)  │      │   (PostgreSQL)      │
└──────────┬──────────┘      └──────────┬──────────┘
           │                            │
           │ HTTP/REST                  │ asyncpg
           │                            │
           ▼                            │
┌──────────────────────────────────────────────────┐
│              FastAPI Backend                      │
│              (localhost:8000)                     │
├─────────────────────────────────────────────────┤
│  • /api/mock/*        - Mock data generation     │
│  • /api/work-items    - Linear issues            │
│  • /api/pull-requests - GitHub PRs               │
│  • /api/conversations - Slack messages           │
│  • /api/scopedocs     - Generated documentation  │
│  • /api/ask-scopey    - AI chatbot               │
│  • /api/ownership     - Component ownership      │
│  • /api/integrations  - Webhook handlers         │
└──────────────────────────────────────────────────┘
```
