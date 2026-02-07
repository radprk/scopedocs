# ScopeDocs - Learning Topics

A curated list of topics, technologies, and concepts you'll encounter in this codebase. Great for deep-diving or learning something new!

---

## 🧠 Core Concepts

### Retrieval-Augmented Generation (RAG)
The foundation of ScopeDocs. Instead of fine-tuning an LLM on code, we:
1. Convert code to vector embeddings
2. Store vectors in a database
3. At query time, find similar vectors
4. Feed relevant context to the LLM

**Learn more:**
- [RAG Explained (OpenAI)](https://platform.openai.com/docs/guides/embeddings/what-are-embeddings)
- [Building RAG Applications (LangChain)](https://python.langchain.com/docs/use_cases/question_answering/)
- [Vector Databases 101](https://www.pinecone.io/learn/vector-database/)

**Where in code:** `backend/ai/search.py`, `backend/ai/embeddings.py`

---

### Vector Embeddings & Semantic Search
Converting text to high-dimensional vectors that capture meaning. Similar texts = similar vectors.

**Key concepts:**
- Embedding dimensions (we use 1024 with BGE-large)
- Cosine similarity vs Euclidean distance
- Batching for efficient API calls

**Learn more:**
- [Word Embeddings Explained](https://towardsdatascience.com/word-embeddings-exploration-explanation-and-exploitation-with-code-in-python-5dac99d5d795)
- [BGE Models (BAAI)](https://huggingface.co/BAAI/bge-large-en-v1.5)
- [Sentence Transformers](https://www.sbert.net/)

**Where in code:** `backend/ai/client.py` (embed method), `backend/ai/embeddings.py`

---

### Code Chunking & AST Parsing
Breaking code into meaningful pieces (functions, classes) rather than arbitrary line counts.

**Key concepts:**
- Abstract Syntax Trees (AST)
- Tree-sitter for multi-language parsing
- Semantic vs syntactic chunking
- Token limits for embeddings

**Learn more:**
- [Tree-sitter Documentation](https://tree-sitter.github.io/tree-sitter/)
- [Chonkie Library](https://github.com/chonkie-ai/chonkie)
- [Code Chunking Strategies](https://www.llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5)

**Where in code:** `code-indexing/src/indexing/chunker.py`

---

## 🔧 Backend Technologies

### FastAPI
Modern Python web framework with async support, automatic API docs, and Pydantic validation.

**Key patterns in our code:**
- Async route handlers (`async def`)
- Pydantic models for request/response validation
- Dependency injection (not heavily used yet)
- Router organization

**Learn more:**
- [FastAPI Official Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [Async Programming in Python](https://realpython.com/async-io-python/)

**Where in code:** `backend/server.py`, `backend/ai/routes.py`

---

### PostgreSQL + pgvector
Vector similarity search directly in Postgres. No separate vector database needed!

**Key concepts:**
- `vector(1024)` column type
- `<=>` operator for cosine distance
- IVFFlat and HNSW indexes for fast search
- Upsert patterns (`ON CONFLICT DO UPDATE`)

**Learn more:**
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [Supabase Vector Guide](https://supabase.com/docs/guides/ai/vector-embeddings)
- [Vector Index Types](https://supabase.com/docs/guides/ai/choosing-compute-addon)

**Where in code:** `db/schema.sql`, `backend/ai/search.py`

---

### asyncpg
High-performance async PostgreSQL driver for Python.

**Key patterns:**
- Connection pooling (`create_pool`)
- Parameterized queries (`$1`, `$2` syntax)
- Context managers (`async with pool.acquire()`)
- Fetch vs execute vs fetchrow

**Learn more:**
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/current/)
- [Connection Pooling Explained](https://www.percona.com/blog/postgresql-connection-pooling-part-1-pros-and-cons/)

**Where in code:** `backend/storage/postgres.py`

---

### OAuth 2.0
Authentication flow for GitHub, Slack, and Linear integrations.

**Key concepts:**
- Authorization code flow
- Access tokens vs refresh tokens
- Scopes and permissions
- State parameter for CSRF protection

**Learn more:**
- [OAuth 2.0 Simplified](https://www.oauth.com/)
- [GitHub OAuth Guide](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
- [Slack OAuth](https://api.slack.com/authentication/oauth-v2)

**Where in code:** `backend/integrations/oauth/routes.py`, `backend/integrations/oauth/config.py`

---

## 🤖 AI & LLM Technologies

### Together.ai API
Serverless inference for embeddings and text generation.

**What we use:**
- BGE-large for embeddings (1024 dims)
- Llama 3.3 70B for generation
- Batch processing for efficiency

**Learn more:**
- [Together.ai Docs](https://docs.together.ai/docs/quickstart)
- [Model Catalog](https://api.together.ai/models)
- [Rate Limits](https://docs.together.ai/docs/rate-limits)

**Where in code:** `backend/ai/client.py`

---

### Prompt Engineering
Crafting effective prompts for different audiences and use cases.

**Key techniques in our code:**
- System vs user prompts
- Audience-specific personas
- Context injection (code references)
- Temperature and token tuning

**Learn more:**
- [OpenAI Prompt Engineering Guide](https://platform.openai.com/docs/guides/prompt-engineering)
- [Anthropic Prompt Design](https://docs.anthropic.com/claude/docs/prompt-design)
- [LangChain Prompts](https://python.langchain.com/docs/modules/model_io/prompts/)

**Where in code:** `backend/ai/prompts.py`

---

## 🏗 Architecture Patterns

### Multi-Tenancy
Isolating data between workspaces/organizations.

**Our approach:**
- `workspace_id` on every table
- Foreign keys for referential integrity
- Query-level filtering (WHERE workspace_id = ...)

**Learn more:**
- [Multi-tenant Architectures](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Row Level Security](https://supabase.com/docs/guides/auth/row-level-security)

**Where in code:** `db/schema.sql`, all query patterns

---

### No Code Storage (Security Pattern)
We never store actual source code - only pointers and embeddings.

**What we store:**
- File paths and line numbers
- Content hashes (for change detection)
- Vector embeddings

**Why it matters:**
- SOC 2 compliance
- Reduced security risk
- Always-fresh code from source

**Where in code:** `backend/routes/indexing.py` (note: no `content` column stored)

---

### Repository Pattern
Abstracting database access behind a service layer.

**Our implementation:**
- `EmbeddingService` wraps embedding operations
- `RAGSearchService` wraps search logic
- Postgres helpers in `storage/postgres.py`

**Learn more:**
- [Repository Pattern Explained](https://martinfowler.com/eaaCatalog/repository.html)
- [Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)

---

## 🌐 API & Integration Patterns

### GitHub API
REST API for fetching code, PRs, and repo metadata.

**Key concepts:**
- Personal access tokens vs OAuth tokens
- Rate limiting (5000 requests/hour with auth)
- Tree API for recursive file listing
- Raw content endpoint

**Learn more:**
- [GitHub REST API](https://docs.github.com/en/rest)
- [Rate Limiting](https://docs.github.com/en/rest/rate-limit)

**Where in code:** `backend/server.py` (GitHub endpoints)

---

### Linear API (GraphQL)
Project management data via GraphQL.

**Key concepts:**
- GraphQL queries and mutations
- Pagination with cursors
- Nested data fetching

**Learn more:**
- [Linear API Docs](https://developers.linear.app/docs/graphql/working-with-the-graphql-api)
- [GraphQL Introduction](https://graphql.org/learn/)

**Where in code:** `backend/server.py` (`api_list_linear_teams`)

---

### Slack API
Channel and message access.

**Key concepts:**
- Bot tokens vs user tokens
- Conversations API
- Pagination cursors
- Rate limits (tier-based)

**Learn more:**
- [Slack API Docs](https://api.slack.com/docs)
- [Conversations API](https://api.slack.com/methods#conversations)

**Where in code:** `backend/server.py` (`api_list_slack_channels`)

---

## 🎨 Frontend Technologies

### Vanilla JavaScript
No framework - just HTML, CSS, and JS.

**Patterns used:**
- Fetch API for HTTP requests
- DOM manipulation
- Event delegation
- Module pattern (functions as namespaces)

**Learn more:**
- [Modern JavaScript Tutorial](https://javascript.info/)
- [MDN Web Docs](https://developer.mozilla.org/)

**Where in code:** `frontend/docs.html`, `frontend/index.html`

---

### marked.js
Markdown to HTML renderer.

**Where in code:** `frontend/docs.html` (CDN import)

**Learn more:**
- [marked.js Documentation](https://marked.js.org/)

---

## 📚 Further Reading

### Books
- "Designing Data-Intensive Applications" by Martin Kleppmann
- "Building LLM Applications" by various (emerging field)
- "FastAPI Modern Python Web Development" by Bill Lubanovic

### Papers
- [BERT: Pre-training of Deep Bidirectional Transformers](https://arxiv.org/abs/1810.04805)
- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)
- [BGE: Text Embeddings by Weakly-Supervised Contrastive Pre-training](https://arxiv.org/abs/2309.07597)

### Courses
- [Full Stack LLM Bootcamp](https://fullstackdeeplearning.com/llm-bootcamp/)
- [FastAPI Crash Course](https://www.youtube.com/watch?v=7t2alSnE2-I)
- [PostgreSQL Tutorial](https://www.postgresqltutorial.com/)

---

*Last updated: 2024*
