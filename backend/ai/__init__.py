"""AI services for ScopeDocs with multi-provider support."""

from .client import (
    TogetherClient,
    get_client,
    truncate_for_embedding,
    EMBEDDING_MAX_TOKENS,
    EMBEDDING_DIMS,
    TOGETHER_EMBEDDING_MODEL,
    OPENAI_EMBEDDING_MODEL,
)
from .embeddings import EmbeddingService
from .search import RAGSearchService, ask_codebase

__all__ = [
    "TogetherClient",
    "get_client",
    "truncate_for_embedding",
    "EMBEDDING_MAX_TOKENS",
    "EMBEDDING_DIMS",
    "TOGETHER_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_MODEL",
    "EmbeddingService",
    "RAGSearchService",
    "ask_codebase",
]
