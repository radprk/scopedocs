"""AI services for ScopeDocs using Together.ai"""

from .client import TogetherClient, get_client
from .embeddings import EmbeddingService
from .search import RAGSearchService, ask_codebase

__all__ = [
    "TogetherClient",
    "get_client",
    "EmbeddingService",
    "RAGSearchService",
    "ask_codebase",
]
