# ScopeDocs MVP - Local Testing Guide

This guide will help you test the ScopeDocs MVP end-to-end on your local machine.

## What You'll Achieve

By the end of this guide, you'll have:
1. ✅ Connected to Supabase (PostgreSQL)
2. ✅ Pulled data from Linear
3. ✅ Pulled data from GitHub
4. ✅ Pulled data from Slack
5. ✅ Seen how they all link together

---

## Prerequisites

- Python 3.9+ installed
- A Supabase account (free tier works)
- API keys from Linear, GitHub, and/or Slack

---

## Step 1: Set Up Supabase (5 minutes)

### 1.1 Create a Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Sign in / Create account
3. Click "New Project"
4. Fill in:
   - **Name**: `scopedocs`
   - **Password**: Create a strong password (save it!)
   - **Region**: Pick closest to you
5. Wait ~2 minutes for project to be ready

### 1.2 Get Your Connection String

1. In your project, go to **Settings** (gear icon)
2. Click **Database**
3. Scroll to **Connection string**
4. Select **URI** tab
5. Copy the string (replace `[YOUR-PASSWORD]` with your actual password)

It looks like:
```
postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres
```

**Note**: Use the "Session pooler" connection string if you're on IPv4 (most home networks).

---

## Step 2: Set Up Local Environment (5 minutes)

### 2.1 Clone and Install

```bash
cd scopedocs

# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Mac/Linux
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install asyncpg httpx python-dotenv fastapi uvicorn
```

### 2.2 Create Your .env File

Create `backend/.env` with your credentials:

```bash
# backend/.env

# Supabase connection (REQUIRED)
POSTGRES_DSN=postgresql://postgres.xxxx:YOUR_PASSWORD@aws-0-us-west-1.pooler.supabase.com:5432/postgres

# Linear API key (get from Linear → Settings → API → Personal API keys)
LINEAR_API_KEY=lin_api_xxxxxxxxxx

# GitHub token (get from GitHub → Settings → Developer settings → Personal access tokens)
GITHUB_TOKEN=ghp_xxxxxxxxxx

# Slack bot token (get from api.slack.com/apps → Your App → OAuth → Bot Token)
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxx
```

---

## Step 3: Initialize Database (1 minute)

Run the setup script to create tables:

```bash
python scripts/setup_database.py
```

Expected output:
```
🔧 Setting up ScopeDocs database...

📡 Connected to Supabase
📝 Creating tables...
✅ Database setup complete!

Tables created:
   • linear_issues  - Store Linear tickets
   • github_prs     - Store GitHub PRs
   • slack_messages - Store Slack threads
   • links          - Connections between artifacts
```

**Verify in Supabase:**
1. Go to your Supabase project
2. Click "Table Editor" in sidebar
3. You should see 4 new tables

---

## Step 4: Test Linear Integration (2 minutes)

### 4.1 Get Your Linear API Key

1. Open Linear
2. Click Settings (gear icon in bottom left)
3. Go to **API** section
4. Under "Personal API keys", click **Create key**
5. Copy the key (starts with `lin_api_`)
6. Add to your `backend/.env`

### 4.2 Pull Linear Issues

```bash
python scripts/pull_linear.py
```

Expected output:
```
🔄 Pulling issues from Linear...

   Fetched 50 issues...
   Fetched 100 issues...
✅ Fetched 127 issues from Linear

💾 Storing in Supabase...
✅ Stored 127 issues

🔗 Creating links...
✅ Created 23 links

==================================================
✅ Linear sync complete!
   Issues: 127
   Links: 23
```

**Verify in Supabase:**
- Check `linear_issues` table - you should see your issues!
- Check `links` table - you should see connections between issues

---

## Step 5: Test GitHub Integration (2 minutes)

### 5.1 Get Your GitHub Token

1. Go to GitHub → Settings → Developer settings
2. Click "Personal access tokens" → "Tokens (classic)"
3. Click "Generate new token (classic)"
4. Select scopes:
   - `repo` (for private repos)
   - OR `public_repo` (for public repos only)
5. Copy the token (starts with `ghp_`)
6. Add to your `backend/.env`

### 5.2 Pull GitHub PRs

```bash
python scripts/pull_github.py --repo your-org/your-repo
```

Example:
```bash
python scripts/pull_github.py --repo facebook/react --max 50
```

Expected output:
```
🔄 Pulling PRs from GitHub: facebook/react
   State: all, Max: 50

   Fetched 50 PRs...
✅ Fetched 50 PRs from GitHub

💾 Storing in Supabase...
✅ Stored 50 PRs

🔗 Creating links to Linear issues...
✅ Created 12 links

==================================================
✅ GitHub sync complete!
   PRs: 50
   Links to Linear: 12
```

**Verify in Supabase:**
- Check `github_prs` table
- Check `links` table for new PR → Issue links

---

## Step 6: Test Slack Integration (5 minutes)

### 6.1 Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click "Create New App" → "From scratch"
3. Name it "ScopeDocs" and select your workspace

### 6.2 Add Bot Permissions

1. Go to "OAuth & Permissions"
2. Under "Bot Token Scopes", add:
   - `channels:history` - Read messages in public channels
   - `channels:read` - List channels
   - `groups:history` - Read messages in private channels (optional)
   - `groups:read` - List private channels (optional)
   - `users:read` - Get user names

### 6.3 Install App

1. Click "Install to Workspace"
2. Authorize the permissions
3. Copy "Bot User OAuth Token" (starts with `xoxb-`)
4. Add to your `backend/.env`

### 6.4 Invite Bot to Channel

In Slack:
```
/invite @ScopeDocs
```

### 6.5 Pull Slack Messages

```bash
python scripts/pull_slack.py --channel general --days 30
```

Expected output:
```
🔄 Pulling messages from Slack: #general
   Last 30 days

   Found channel: C012345678
   Fetched 50 messages...
   Fetched 89 messages...
✅ Fetched 89 messages from Slack

💾 Storing in Supabase...
✅ Stored 45 message threads

🔗 Creating links to Linear issues and PRs...
✅ Created 8 links

==================================================
✅ Slack sync complete!
   Message threads: 45
   Links: 8
```

---

## Step 7: View Your Data (API)

Start the API server:

```bash
python scripts/simple_api.py
```

Output:
```
🚀 Starting ScopeDocs MVP API...
   Open http://localhost:8000/docs for Swagger UI
```

### Try These Endpoints

**Overview stats:**
```
http://localhost:8000/stats
```

**List Linear issues:**
```
http://localhost:8000/linear/issues
```

**Get FULL CONTEXT for an issue (the magic!):**
```
http://localhost:8000/context/ENG-123
```

This returns the issue + all linked PRs + all Slack discussions!

**Search across everything:**
```
http://localhost:8000/search?q=authentication
```

---

## Summary: Commands Cheat Sheet

```bash
# 1. Set up database (run once)
python scripts/setup_database.py

# 2. Pull from Linear
python scripts/pull_linear.py

# 3. Pull from GitHub
python scripts/pull_github.py --repo org/repo

# 4. Pull from Slack
python scripts/pull_slack.py --channel general

# 5. Start API
python scripts/simple_api.py
```

---

## Troubleshooting

### "POSTGRES_DSN not set"
- Make sure `backend/.env` exists with your connection string

### "Connection refused" / "timeout"
- Check your Supabase project is not paused
- Make sure you're using the Session pooler connection string (for IPv4)

### "LINEAR_API_KEY not set"
- Add your Linear API key to `backend/.env`

### "Repository not found" (GitHub)
- Make sure the repo exists and your token has access
- For private repos, use a token with `repo` scope

### "Channel not found" (Slack)
- Invite the bot to the channel: `/invite @ScopeDocs`
- Make sure the bot has `channels:read` permission

### No links being created
- Links are created when issues mention each other or PRs mention issues
- Example: If a PR title contains "ENG-123", it creates a link

---

## What's Next?

After testing works:

1. **Add more data**: Run the pull scripts on more repos/channels
2. **Set up cron**: Run pulls daily with cron or scheduled tasks
3. **Build UI**: Connect a frontend to the API
4. **Add AI**: Use the context for AI-powered summaries

---

## File Structure

```
scopedocs/
├── backend/
│   └── .env                 # Your API keys (create this!)
├── scripts/
│   ├── setup_database.py    # Creates tables in Supabase
│   ├── pull_linear.py       # Pulls from Linear
│   ├── pull_github.py       # Pulls from GitHub
│   ├── pull_slack.py        # Pulls from Slack
│   └── simple_api.py        # API to view data
└── TESTING.md               # This guide
```
