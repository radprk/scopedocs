import os
from typing import List, Dict, Any
from backend.models import EmbeddedArtifact, ArtifactType, ChatRequest, ChatResponse
from backend.database import db, COLLECTIONS
import numpy as np
import hashlib

class RAGService:
    """Service for RAG-powered Ask Scopey chatbot"""

    def __init__(self):
        self.api_key = os.getenv('EMERGENT_LLM_KEY')
        self.embedding_model = 'text-embedding-3-large'
        self.chat_model = 'gpt-4o'
        self.use_mock = False  # Will switch to True if API unavailable

    def _generate_mock_embedding(self, text: str, dimensions: int = 1536) -> List[float]:
        """Generate deterministic mock embedding from text hash"""
        # Use hash for deterministic results
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()

        # Convert to floats
        np.random.seed(int.from_bytes(hash_bytes[:4], 'big'))
        embedding = np.random.randn(dimensions).tolist()

        # Normalize
        norm = np.linalg.norm(embedding)
        return [x / norm for x in embedding]

    async def embed_text(self, text: str) -> List[float]:
        """Generate embeddings for text (with fallback to mock)"""
        if self.use_mock:
            return self._generate_mock_embedding(text)

        try:
            # Try real embeddings first
            import litellm
            from emergentintegrations.llm.chat import get_integration_proxy_url
            litellm.api_base = get_integration_proxy_url()

            response = await litellm.aembedding(
                model=self.embedding_model,
                input=text,
                api_key=self.api_key
            )
            return response.data[0]['embedding']
        except Exception as e:
            print(f"Embeddings API error, using mock: {str(e)[:100]}")
            self.use_mock = True
            return self._generate_mock_embedding(text)

    async def embed_artifact(self, artifact_id: str, artifact_type: ArtifactType, content: str, metadata: Dict = None) -> EmbeddedArtifact:
        """Embed an artifact and store it"""
        embedding = await self.embed_text(content)

        embedded = EmbeddedArtifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content=content,
            embedding=embedding,
            metadata=metadata or {}
        )

        return embedded

    async def embed_all_artifacts(self):
        """Embed all artifacts in the database"""
        embedded_count = 0

        # Embed work items
        cursor = await db[COLLECTIONS['work_items']].find({})
        work_items = await cursor.to_list(1000)
        for item in work_items:
            content = f"Linear Issue {item['external_id']}: {item['title']}. {item.get('description', '')}"
            embedded = await self.embed_artifact(
                artifact_id=item['id'],
                artifact_type=ArtifactType.LINEAR_ISSUE,
                content=content,
                metadata={'external_id': item['external_id'], 'project_id': item.get('project_id')}
            )
            await db[COLLECTIONS['embeddings']].insert_one(embedded.model_dump())
            embedded_count += 1

        # Embed PRs
        cursor = await db[COLLECTIONS['pull_requests']].find({})
        prs = await cursor.to_list(1000)
        for pr in prs:
            content = f"GitHub PR {pr['external_id']}: {pr['title']}. {pr.get('description', '')}. Files changed: {', '.join(pr.get('files_changed', []))}"
            embedded = await self.embed_artifact(
                artifact_id=pr['id'],
                artifact_type=ArtifactType.GITHUB_PR,
                content=content,
                metadata={'external_id': pr['external_id'], 'repo': pr['repo']}
            )
            await db[COLLECTIONS['embeddings']].insert_one(embedded.model_dump())
            embedded_count += 1

        # Embed conversations
        cursor = await db[COLLECTIONS['conversations']].find({})
        conversations = await cursor.to_list(1000)
        for conv in conversations:
            messages_text = ' '.join([msg.get('text', '') for msg in conv.get('messages', [])])
            content = f"Slack conversation in {conv['channel']}: {messages_text}"
            if conv.get('decision_extracted'):
                content += f" Decision: {conv['decision_extracted']}"

            embedded = await self.embed_artifact(
                artifact_id=conv['id'],
                artifact_type=ArtifactType.SLACK_THREAD,
                content=content,
                metadata={'external_id': conv['external_id'], 'channel': conv['channel']}
            )
            await db[COLLECTIONS['embeddings']].insert_one(embedded.model_dump())
            embedded_count += 1

        # Embed docs
        cursor = await db[COLLECTIONS['scopedocs']].find({})
        docs = await cursor.to_list(1000)
        for doc in docs:
            sections_text = '\n'.join([f"{k}: {v}" for k, v in doc.get('sections', {}).items()])
            content = f"ScopeDoc for {doc['project_name']}: {sections_text}"

            embedded = await self.embed_artifact(
                artifact_id=doc['id'],
                artifact_type=ArtifactType.SCOPEDOC,
                content=content,
                metadata={'project_id': doc['project_id'], 'project_name': doc['project_name']}
            )
            await db[COLLECTIONS['embeddings']].insert_one(embedded.model_dump())
            embedded_count += 1

        return {'embedded_count': embedded_count}

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        a_np = np.array(a)
        b_np = np.array(b)
        return float(np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np)))

    async def semantic_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for similar artifacts using semantic search"""
        # Get query embedding
        query_embedding = await self.embed_text(query)

        # Get all embeddings
        cursor = await db[COLLECTIONS['embeddings']].find({})
        all_embeddings = await cursor.to_list(10000)

        # Calculate similarities
        results = []
        for emb in all_embeddings:
            embedding_data = emb.get('embedding', [])
            if not embedding_data:
                continue
            similarity = self.cosine_similarity(query_embedding, embedding_data)
            results.append({
                'artifact_id': emb['artifact_id'],
                'artifact_type': emb['artifact_type'],
                'content': emb['content'],
                'metadata': emb.get('metadata', {}),
                'similarity': similarity
            })

        # Sort by similarity and return top k
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]

    async def ask_scopey(self, request: ChatRequest) -> ChatResponse:
        """Answer questions using RAG"""
        # Search for relevant context
        relevant_docs = await self.semantic_search(request.question, top_k=5)

        # Build context
        context = "Here are the most relevant documents:\n\n"
        sources = []
        for i, doc in enumerate(relevant_docs, 1):
            context += f"[{i}] {doc['content'][:500]}...\n\n"
            sources.append({
                'artifact_type': doc['artifact_type'],
                'metadata': doc['metadata'],
                'similarity': round(doc['similarity'], 3)
            })

        # Try to use real LLM, fallback to simple response
        try:
            if not self.use_mock:
                import litellm
                from emergentintegrations.llm.chat import get_integration_proxy_url
                litellm.api_base = get_integration_proxy_url()

                messages = [
                    {
                        'role': 'system',
                        'content': '''You are Scopey, an AI assistant for ScopeDocs. You help teams understand their
                        projects by answering questions based on their Slack conversations, GitHub PRs, Linear issues,
                        and documentation. Always cite your sources using [1], [2], etc. Be concise and helpful.'''
                    }
                ]

                for msg in request.history:
                    messages.append({'role': msg.role, 'content': msg.content})

                messages.append({
                    'role': 'user',
                    'content': f"{context}\n\nQuestion: {request.question}"
                })

                response = await litellm.acompletion(
                    model=self.chat_model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1000,
                    api_key=self.api_key
                )

                answer = response.choices[0].message.content
            else:
                raise Exception("Using mock mode")

        except Exception as e:
            print(f"Chat API error, using mock response: {str(e)[:100]}")
            self.use_mock = True
            # Generate simple response from context
            answer = f"Based on the available documents, here's what I found:\n\n"
            if relevant_docs:
                for i, doc in enumerate(relevant_docs[:3], 1):
                    artifact_type = doc['artifact_type'].replace('_', ' ').title()
                    snippet = doc['content'][:200]
                    answer += f"[{i}] {artifact_type}: {snippet}...\n\n"
                answer += f"I found {len(relevant_docs)} relevant artifacts related to your question about: {request.question}"
            else:
                answer = "I couldn't find any relevant information in the knowledge base. Please try rephrasing your question or generate more mock data first."

        return ChatResponse(
            answer=answer,
            sources=sources
        )
