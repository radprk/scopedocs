# Welcome to ScopeDocs! 🎓

> **Style:** New Engineer Bird's Eye View
> **Best for:** First day onboarding, understanding the big picture

---

## The 30-Second Summary

**ScopeDocs turns code into smart documentation that adapts to who's reading it.**

Imagine you're a new engineer trying to understand a codebase. Instead of getting the same dense wiki everyone else gets, ScopeDocs generates documentation *specifically for you* - your role, your goals, your current understanding.

That's what we're building.

---

## How It All Fits Together

Think of ScopeDocs as a pipeline with four stages:

```
📁 Code Repository
      ↓
   [1. INDEX]     → "Break code into meaningful chunks"
      ↓
   [2. EMBED]     → "Convert chunks to semantic vectors"
      ↓
   [3. SEARCH]    → "Find relevant chunks for any question"
      ↓
   [4. GENERATE]  → "Create tailored documentation"
      ↓
📄 Adaptive Documentation
```

**Stage 1 - Indexing:** We fetch code from GitHub and break it into semantic chunks (functions, classes) using tree-sitter. No code is stored - just pointers.

**Stage 2 - Embedding:** Each chunk gets converted to a 1024-dimensional vector using BGE-large. These vectors capture the *meaning* of the code.

**Stage 3 - Search:** When you ask a question, we embed your question and find the most similar code chunks using pgvector's cosine distance.

**Stage 4 - Generation:** We feed the relevant chunks to Llama 3.3 with audience-specific prompts. New engineer? You get a bird's eye view. On-call? You get the quick actionable version.

---

## The 5 Key Concepts That Make Everything Click

### 1. Multi-tenancy via Workspaces
Everything is scoped to a `workspace`. Each workspace has its own OAuth tokens, indexed repos, and generated docs. Think of workspaces as "organizations" or "teams".

### 2. RAG (Retrieval-Augmented Generation)
We don't ask the AI to memorize your codebase. Instead, we *retrieve* relevant code chunks at query time and *augment* the AI's prompt with them. This is called RAG, and it's why our docs are accurate.

### 3. Audience-Adaptive Prompts
The same code can generate completely different documentation. `backend/ai/prompts.py` defines different system prompts for different audiences:
- `new_engineer`: Top-down conceptual
- `oncall`: Quick and actionable
- `traditional`: Complete reference
- `custom`: Whatever you need

### 4. No Code Storage (SOC 2 Pattern)
We never store actual code. We store:
- File paths and line numbers (pointers)
- Content hashes (for change detection)
- Embeddings (semantic vectors)

When we need actual code, we fetch it fresh from GitHub.

### 5. FastAPI + Async Everywhere
The entire backend is async Python. Database calls use `asyncpg`, HTTP calls use `httpx`. This matters because we make lots of parallel API calls (GitHub, Together.ai) and async keeps everything fast.

---

## Your First Tour: The Main Files

Start with these files, in this order:

### 1. `backend/server.py` - The Front Door
This is where requests come in. It sets up FastAPI, includes all the routers, and defines the workspace/GitHub/Slack endpoints. Read this first to understand the API surface.

### 2. `backend/ai/routes.py` - The AI Brain
The `/api/ai/*` endpoints live here. Start with `generate_adaptive_documentation()` - it shows the full flow from search to generation.

### 3. `backend/ai/prompts.py` - The Secret Sauce
This is where we define how docs are tailored to different audiences. Read the `SYSTEM_PROMPTS` dictionary to understand the different "personalities" we give the AI.

### 4. `backend/ai/search.py` - Finding Relevant Code
The RAG search service. `search()` is the key method - it embeds your query and finds similar chunks.

### 5. `frontend/docs.html` - The User Experience
The documentation generator UI. See how users select their audience type and purpose.

---

## A Typical Request Flow

Let's trace what happens when a new engineer requests documentation:

```
User clicks "Generate Documentation"
  ↓
Frontend POSTs to /api/ai/generate-adaptive-doc
  ↓
Backend receives: {audience_type: "new_engineer", repo: "owner/repo"}
  ↓
RAGSearchService.search() runs:
  - Embeds the query via Together.ai
  - Queries pgvector for similar code chunks
  - Returns top 10 matches with file paths and line numbers
  ↓
build_generation_prompt() in prompts.py:
  - Picks the "new_engineer" system prompt
  - Builds a user prompt with code references
  ↓
TogetherClient.generate() calls Llama 3.3:
  - System prompt: "You're an expert mentor helping a new team member..."
  - User prompt: "Code locations: [1] server.py:10-50, [2] routes.py:100-150..."
  ↓
LLM returns markdown documentation
  ↓
Response includes:
  - Generated markdown content
  - References mapping [n] to file:line
  - Suggested next topics to explore
```

---

## Where to Go Next

Based on your role as a new engineer:

1. **Run it locally** - Follow `README.md` to get the server running
2. **Try the docs UI** - Go to `/docs` and generate documentation for a test repo
3. **Read the prompts** - `backend/ai/prompts.py` is the heart of the adaptive magic
4. **Trace a request** - Add print statements and follow a request through the system

---

## Quick Reference Cheat Sheet

| What | Where |
|------|-------|
| Main server | `backend/server.py` |
| AI endpoints | `backend/ai/routes.py` |
| Prompts/Audiences | `backend/ai/prompts.py` |
| Embedding logic | `backend/ai/embeddings.py` |
| RAG search | `backend/ai/search.py` |
| Together.ai client | `backend/ai/client.py` |
| Database helpers | `backend/storage/postgres.py` |
| OAuth handlers | `backend/integrations/oauth/routes.py` |
| Docs UI | `frontend/docs.html` |
| DB schema | `db/schema.sql` |

---

## You've Got This! 💪

Remember: You don't need to understand everything on day one. Start with the high-level flow, then dive deeper into the parts that matter for your first task.

The best way to learn this codebase? Use ScopeDocs to document itself. Meta, but effective.

---
*Generated with New Engineer Bird's Eye View style*
