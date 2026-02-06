# Setup Guide

Get ScopeDocs running locally in 5 minutes.

## Prerequisites

- Python 3.10+
- PostgreSQL 14+ with pgvector extension
- GitHub OAuth App (for repository access)
- Together.ai API key (for embeddings)

## Step 1: Database Setup

```bash
# Install pgvector extension (Ubuntu/Debian)
sudo apt install postgresql-14-pgvector

# Or on macOS with Homebrew
brew install pgvector

# Create database
createdb scopedocs

# Enable pgvector and create tables
psql -d scopedocs -f db/schema.sql
```

Verify pgvector is installed:

```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

---

## Step 2: Environment Variables

Create a `.env` file or export these variables:

```bash
# Database
export DATABASE_URL="postgresql://localhost:5432/scopedocs"

# Together.ai (for embeddings)
export TOGETHER_API_KEY="your-together-api-key"

# GitHub OAuth App
export GITHUB_CLIENT_ID="your-github-client-id"
export GITHUB_CLIENT_SECRET="your-github-client-secret"

# Optional: Slack and Linear (for future phases)
export SLACK_CLIENT_ID="your-slack-client-id"
export SLACK_CLIENT_SECRET="your-slack-client-secret"
export LINEAR_CLIENT_ID="your-linear-client-id"
export LINEAR_CLIENT_SECRET="your-linear-client-secret"
```

### Getting API Keys

**Together.ai**:
1. Go to [together.ai](https://together.ai)
2. Create an account
3. Go to Settings → API Keys
4. Copy your API key

**GitHub OAuth App**:
1. Go to GitHub → Settings → Developer settings → OAuth Apps
2. Click "New OAuth App"
3. Set Authorization callback URL: `http://localhost:8000/api/oauth/github/callback`
4. Copy Client ID and generate Client Secret

---

## Step 3: Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install backend dependencies
pip install -r requirements.txt

# Install code-indexing dependencies
pip install -r code-indexing/requirements.txt
```

---

## Step 4: Start the Server

```bash
# From project root
python -m uvicorn backend.server:app --reload --port 8000
```

You should see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

---

## Step 5: Verify Installation

1. **Open the UI**: http://localhost:8000/ui
2. **Connect GitHub**: Click "Connect GitHub" and authorize
3. **Test Pipeline**: http://localhost:8000/pipeline.html

---

## Common Issues

### pgvector not found

```
ERROR: extension "vector" is not available
```

**Fix**: Install pgvector for your PostgreSQL version:

```bash
# Check your PostgreSQL version
psql --version

# Install matching pgvector
sudo apt install postgresql-XX-pgvector  # Replace XX with version
```

### Database connection refused

```
ERROR: connection refused
```

**Fix**: Ensure PostgreSQL is running:

```bash
sudo systemctl start postgresql
# or
brew services start postgresql
```

### Together.ai rate limit

```
ERROR: rate_limit_exceeded
```

**Fix**: Together.ai has rate limits on free tier. Wait a moment and retry, or upgrade your plan.

---

## Next Steps

1. Read the [Data Flow](data-flow.md) to understand how data moves through the system
2. Try the [Learning Path](learning-path.md) to understand each component
