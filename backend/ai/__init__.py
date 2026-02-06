"""AI services for ScopeDocs using Together.ai"""

from .client import (
    TogetherClient,
    get_client,
    truncate_for_embedding,
    EMBEDDING_MAX_TOKENS,
    EMBEDDING_MODEL,
    EMBEDDING_DIMS,
)
from .embeddings import EmbeddingService
from .search import RAGSearchService, ask_codebase

__all__ = [
    "TogetherClient",
    "get_client",
    "truncate_for_embedding",
    "EMBEDDING_MAX_TOKENS",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMS",
    "EmbeddingService",
    "RAGSearchService",
    "ask_codebase",
]
