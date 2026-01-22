import os
from typing import List, Dict, Any
from models import EmbeddedArtifact, ArtifactType, ChatRequest, ChatResponse
from database import db, COLLECTIONS
import numpy as np
import litellm
from emergentintegrations.llm.chat import get_integration_proxy_url

class RAGService:
    """Service for RAG-powered Ask Scopey chatbot"""
    
    def __init__(self):
        self.api_key = os.getenv('EMERGENT_LLM_KEY')
        # Set up litellm for Emergent proxy
        litellm.api_base = get_integration_proxy_url()
        self.embedding_model = 'text-embedding-3-large'
        self.chat_model = 'gpt-4o'
    
    async def embed_text(self, text: str) -> List[float]:
        """Generate embeddings for text"""
        response = await litellm.aembedding(
            model=self.embedding_model,
            input=text,
            api_key=self.api_key
        )
        return response.data[0]['embedding']
    
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
        work_items = await db[COLLECTIONS['work_items']].find({}).to_list(1000)
        for item in work_items:
            content = f"Linear Issue {item['external_id']}: {item['title']}. {item['description']}"
            embedded = await self.embed_artifact(
                artifact_id=item['id'],
                artifact_type=ArtifactType.LINEAR_ISSUE,
                content=content,
                metadata={'external_id': item['external_id'], 'project_id': item.get('project_id')}
            )
            await db[COLLECTIONS['embeddings']].insert_one(embedded.model_dump())
            embedded_count += 1
        
        # Embed PRs
        prs = await db[COLLECTIONS['pull_requests']].find({}).to_list(1000)
        for pr in prs:
            content = f"GitHub PR {pr['external_id']}: {pr['title']}. {pr['description']}. Files changed: {', '.join(pr.get('files_changed', []))}"
            embedded = await self.embed_artifact(
                artifact_id=pr['id'],
                artifact_type=ArtifactType.GITHUB_PR,
                content=content,
                metadata={'external_id': pr['external_id'], 'repo': pr['repo']}
            )
            await db[COLLECTIONS['embeddings']].insert_one(embedded.model_dump())
            embedded_count += 1
        
        # Embed conversations
        conversations = await db[COLLECTIONS['conversations']].find({}).to_list(1000)
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
        docs = await db[COLLECTIONS['scopedocs']].find({}).to_list(1000)
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
        all_embeddings = await db[COLLECTIONS['embeddings']].find({}).to_list(10000)
        
        # Calculate similarities
        results = []
        for emb in all_embeddings:
            similarity = self.cosine_similarity(query_embedding, emb['embedding'])
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
        
        # Build messages
        messages = [
            {
                'role': 'system',
                'content': '''You are Scopey, an AI assistant for ScopeDocs. You help teams understand their 
                projects by answering questions based on their Slack conversations, GitHub PRs, Linear issues, 
                and documentation. Always cite your sources using [1], [2], etc. Be concise and helpful.'''
            }
        ]
        
        # Add history
        for msg in request.history:
            messages.append({'role': msg.role, 'content': msg.content})
        
        # Add current question with context
        messages.append({
            'role': 'user',
            'content': f"{context}\n\nQuestion: {request.question}"
        })
        
        # Get response from GPT-4 via litellm
        response = await litellm.acompletion(
            model=self.chat_model,
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
            api_key=self.api_key
        )
        
        answer = response.choices[0].message.content
        
        return ChatResponse(
            answer=answer,
            sources=sources
        )