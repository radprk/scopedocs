# ScopeDocs - Living Documentation Platform

**Event-sourced knowledge orchestration for modern engineering teams**

ScopeDocs is a comprehensive documentation platform that automatically generates and maintains living documentation from your workflow artifacts across Slack, GitHub, and Linear.

---

## 🚀 Features

### ✅ **Feature 1: ScopeDoc per Linear Project**
- Auto-generate comprehensive documentation from Linear projects
- Pulls data from work items, PRs, and Slack conversations
- Structured sections: Background, Scope, API Changes, Migration, Rollout, Ownership, Decisions, Risks
- Evidence-backed documentation with source links

### ✅ **Feature 2: Doc Freshness Detection & PR → Doc Drift**
- Real-time freshness scoring (0.0 = outdated, 1.0 = fresh)
- Automatic detection when merged PRs make docs stale
- Visual freshness indicators (Fresh, Stale, Outdated)
- Drift alerts when documentation needs updates
- Time decay and event-based freshness calculation

### ✅ **Feature 3: Ask Scopey - RAG-Powered Chatbot**
- Semantic search across all artifacts (Linear, GitHub, Slack, Docs)
- OpenAI GPT-4 powered responses with source citations
- Vector embeddings using text-embedding-3-large
- Conversational interface with chat history
- Confidence scores for each source

### ✅ **Feature 4: Ownership Tracking**
- Component ownership from CODEOWNERS and Linear teams
- Ownership resolution with confidence scores
- Distribution dashboard showing who owns what
- Repository and path-based component tracking

---

## 🏗️ Architecture

### **Tech Stack**
- **Backend**: FastAPI + Python 3.11
- **Frontend**: React 19 + Tailwind CSS + shadcn/ui
- **Database**: MongoDB (event-sourced design, PostgreSQL-ready)
- **LLM**: OpenAI (GPT-4, text-embedding-3-large) via Emergent LLM Key
- **Vector Search**: In-memory with NumPy (pgvector-ready)

### **Core Components**

```
┌─────────────────────────────────────────────────┐
│           EVENT INGESTION LAYER                 │
│  Slack • GitHub • Linear (Mock Data Ready)      │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│        NORMALIZATION & KNOWLEDGE GRAPH          │
│  • ArtifactEvents  • Relationships              │
│  • Work Items      • Components                 │
│  • Pull Requests   • People                     │
│  • Conversations   • Embeddings                 │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│              CORE SERVICES                      │
│  • Doc Generation   • Freshness Detection      │
│  • RAG Service      • Ownership Resolution      │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│           FRONTEND INTERFACES                   │
│  Dashboard • Projects • Docs • Ask Scopey       │
└─────────────────────────────────────────────────┘
```

---

## 📦 Data Models

### **Canonical Entities**
- **WorkItem**: Linear issues with status, team, assignee, labels
- **PullRequest**: GitHub PRs with files changed, reviewers, merge status
- **Conversation**: Slack threads with decision extraction
- **ScopeDoc**: Generated documentation with freshness tracking
- **Component**: Services, APIs, repos with ownership
- **Person**: Team members with GitHub/Slack identities
- **Relationship**: Graph edges (implements, discusses, owns, touches, documents)
- **EmbeddedArtifact**: Vector embeddings for semantic search

### **Relationship Types**
- `IMPLEMENTS`: PR implements Work Item
- `DISCUSSES`: Conversation discusses PR/Issue
- `OWNS`: Person owns Component
- `TOUCHES`: PR touches Component
- `DOCUMENTS`: Doc documents Work Item
- `MENTIONS`: Artifact mentions another
- `DERIVES_FROM`: Doc derives from Artifacts

---

## 🎯 Getting Started

### **1. Generate Mock Data**
```bash
# Via API
curl -X POST http://localhost:8001/api/mock/generate-multiple?count=5

# Or via Frontend Dashboard
Click "Generate Mock Data" button
```

This creates:
- 5 Linear work items across 4 projects
- 5 GitHub PRs with file changes
- 5 Slack conversations with decisions
- Component and ownership mappings
- Relationship graph connections

### **2. Generate ScopeDocs**
```bash
# Get projects
curl http://localhost:8001/api/projects

# Generate doc for a project
curl -X POST "http://localhost:8001/api/scopedocs/generate?project_id=proj-1&project_name=User%20Authentication%20System"
```

### **3. Enable Ask Scopey**
```bash
# Generate embeddings (required for RAG)
curl -X POST http://localhost:8001/api/embeddings/generate-all

# Ask a question
curl -X POST http://localhost:8001/api/ask-scopey \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the main features of the authentication system?",
    "history": []
  }'
```

### **4. Check Doc Freshness**
```bash
# Check single doc
curl http://localhost:8001/api/freshness/{doc_id}

# Check all docs
curl -X POST http://localhost:8001/api/freshness/check-all
```

### **5. View Ownership**
```bash
# Get ownership summary
curl http://localhost:8001/api/ownership

# Get component ownership
curl http://localhost:8001/api/ownership/{component_id}
```

---

## 📚 API Endpoints

### **Mock Data**
- `POST /api/mock/generate-scenario` - Generate single scenario
- `POST /api/mock/generate-multiple?count=N` - Generate N scenarios

### **Artifacts**
- `GET /api/work-items` - List all work items
- `GET /api/work-items/{id}` - Get specific work item
- `GET /api/pull-requests` - List all PRs
- `GET /api/conversations` - List all Slack threads
- `GET /api/people` - List all team members
- `GET /api/components` - List all components
- `GET /api/projects` - List all projects

### **ScopeDocs (Feature 1)**
- `POST /api/scopedocs/generate` - Generate doc from project
- `GET /api/scopedocs` - List all docs
- `GET /api/scopedocs/{id}` - Get specific doc

### **Freshness (Feature 2)**
- `GET /api/freshness/{doc_id}` - Check doc freshness
- `POST /api/freshness/check-all` - Check all docs
- `POST /api/drift-alerts` - Create drift alert
- `GET /api/drift-alerts` - List all alerts

### **Ask Scopey (Feature 3)**
- `POST /api/embeddings/generate-all` - Generate embeddings
- `POST /api/ask-scopey` - Ask question
- `GET /api/search?query=X` - Semantic search

### **Ownership (Feature 4)**
- `GET /api/ownership` - Ownership summary
- `GET /api/ownership/{component_id}` - Component ownership

### **Stats**
- `GET /api/stats` - Overall statistics

---

## 🎨 Frontend Pages

### **Dashboard** (`/`)
- Overview statistics
- Generate mock data
- Quick access to all features

### **Projects** (`/projects`)
- View all Linear projects
- Work item counts per project
- Generate ScopeDocs for projects

### **Docs** (`/docs`)
- List all ScopeDocs
- Freshness indicators
- Evidence link counts

### **Doc View** (`/docs/:id`)
- Full documentation with all sections
- Freshness warnings
- Evidence links with external URLs
- Structured sections (Background, Scope, API Changes, etc.)

### **Ask Scopey** (`/ask-scopey`)
- RAG-powered chatbot
- Semantic search across all artifacts
- Source citations with similarity scores
- Chat history support

### **Ownership** (`/ownership`)
- Ownership distribution dashboard
- Component ownership details
- Team and individual statistics

---

## 🔑 Environment Variables

### **Backend** (`/app/backend/.env`)
```bash
MONGO_URL="mongodb://localhost:27017"
DB_NAME="scopedocs_db"
CORS_ORIGINS="*"
EMERGENT_LLM_KEY=sk-emergent-3604fA1AeB7EaC52e6
```

### **Frontend** (`/app/frontend/.env`)
```bash
REACT_APP_BACKEND_URL=https://your-preview-url.emergentagent.com
WDS_SOCKET_PORT=443
ENABLE_HEALTH_CHECK=false
```

---

## 🧪 Testing

### **Backend API Testing**
```bash
# Check if backend is running
curl http://localhost:8001/api/stats

# Test doc generation flow
curl -X POST http://localhost:8001/api/mock/generate-scenario
curl http://localhost:8001/api/projects
curl -X POST "http://localhost:8001/api/scopedocs/generate?project_id=proj-1&project_name=Test"
curl http://localhost:8001/api/scopedocs

# Test RAG flow
curl -X POST http://localhost:8001/api/embeddings/generate-all
curl -X POST http://localhost:8001/api/ask-scopey \
  -H "Content-Type: application/json" \
  -d '{"question": "What projects are we working on?"}'

# Test freshness
curl http://localhost:8001/api/freshness/check-all

# Test ownership
curl http://localhost:8001/api/ownership
```

### **Frontend Testing**
1. Open browser to frontend URL
2. Click "Generate Mock Data"
3. Navigate to Projects → Generate ScopeDoc
4. View generated doc with freshness indicator
5. Go to Ask Scopey → Generate Embeddings → Ask questions
6. Check Ownership page for component ownership

---

## 🔮 Future Enhancements

### **Database Migration**
- Switch to PostgreSQL + pgvector for production
- Implement proper graph DB (Neo4j) for complex queries
- Add full-text search with proper indexing

### **Real Integrations**
- Slack OAuth + Webhooks
- GitHub App with webhook subscriptions
- Linear OAuth + GraphQL API
- Real-time event streaming

### **Advanced Features**
- Automated doc regeneration on events
- Slack bot for drift alerts
- GitHub PR checks with doc coverage
- Linear sidebar widget
- Chrome extension for contextual help
- Decision extraction with NLP
- Impact analysis visualization
- Multi-tenant support with permissions

### **Performance**
- Caching layer (Redis)
- Batch embedding generation
- Incremental doc updates
- Background job processing (Celery)

---

## 📝 Development Notes

### **Mock Data Generator**
The `MockDataGenerator` class creates realistic scenarios:
- 8 team members across 5 teams
- 4 pre-defined projects
- Randomized work items with realistic titles
- PRs with file changes linked to work items
- Slack conversations with decision extraction
- Relationship graph connections

### **Freshness Calculation**
Freshness score formula:
```
score = 1.0
score -= min(days_since_verification * 0.05, 0.5)  # Time decay
score -= min(relevant_prs_merged * 0.1, 0.4)       # Event impact
freshness_level = fresh (>0.8) | stale (0.5-0.8) | outdated (<0.5)
```

### **RAG Pipeline**
1. Generate embeddings for all artifacts
2. Store vectors in database
3. On query: embed query → cosine similarity → top-k results
4. Build context from top results
5. Send to GPT-4 with system prompt
6. Return answer with source citations

### **Ownership Resolution**
- Primary: CODEOWNERS file
- Secondary: PR review patterns
- Tertiary: Linear assignee
- Confidence scoring based on evidence count

---

## 🛠️ Tech Details

### **Dependencies**
**Backend:**
- fastapi, uvicorn
- motor (async MongoDB)
- pydantic (validation)
- openai (LLM + embeddings)
- numpy (vector operations)
- emergentintegrations (Emergent LLM Key)

**Frontend:**
- react, react-router-dom
- axios (API calls)
- shadcn/ui + radix-ui (components)
- tailwind-css (styling)
- lucide-react (icons)

### **Database Collections**
- `artifact_events` - Event log
- `work_items` - Linear issues
- `pull_requests` - GitHub PRs
- `conversations` - Slack threads
- `scopedocs` - Generated docs
- `components` - Services/APIs
- `people` - Team members
- `relationships` - Graph edges
- `embeddings` - Vector embeddings
- `drift_alerts` - Freshness alerts

---

## 🎉 Summary

ScopeDocs successfully implements all 4 core features:

1. ✅ **ScopeDoc Generation** - Auto-create docs from Linear projects
2. ✅ **Doc Freshness Detection** - Track staleness with drift alerts
3. ✅ **Ask Scopey RAG** - AI-powered Q&A with source citations
4. ✅ **Ownership Tracking** - Component ownership resolution

The platform is ready for testing with mock data and can be extended with real integrations. The event-sourced architecture provides a solid foundation for scaling to production workloads.

---

## 📞 Support

For questions or issues, refer to the API documentation or check the logs:
```bash
# Backend logs
tail -f /var/log/supervisor/backend.err.log

# Frontend logs
tail -f /var/log/supervisor/frontend.out.log
```

**Built with ❤️ for engineering teams who value living documentation**
