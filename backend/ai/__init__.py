"""AI services for ScopeDocs using Together.ai"""

from .client import TogetherClient, get_client
from .embeddings import EmbeddingService
from .generation import DocGenerationService
from .search import SearchService
from .audiences import (
    Audience,
    AudienceProfile,
    MultiAudienceDocService,
    get_audience_profile,
    list_audiences,
    AUDIENCE_PROFILES,
)

__all__ = [
    "TogetherClient",
    "get_client",
    "EmbeddingService",
    "DocGenerationService",
    "SearchService",
    "Audience",
    "AudienceProfile",
    "MultiAudienceDocService",
    "get_audience_profile",
    "list_audiences",
    "AUDIENCE_PROFILES",
]
