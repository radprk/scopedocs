"""
Pipeline module for ScopeDocs.

This module orchestrates the flow from code ingestion to documentation generation:
1. Fetch code from GitHub (on-demand, not stored)
2. Chunk using AST-aware chunker (tree-sitter via Chonkie)
3. Generate embeddings (stored in pgvector)
4. Generate documentation (stored)
5. Create doc ↔ code links
6. Extract traceability links (Linear ↔ GitHub ↔ Code)
"""

from .orchestrator import PipelineOrchestrator, PipelineResult
from .traceability import TraceabilityExtractor
from .github_fetcher import GitHubFetcher
from .mock_data import MockDataGenerator

__all__ = [
    "PipelineOrchestrator",
    "PipelineResult",
    "TraceabilityExtractor",
    "GitHubFetcher",
    "MockDataGenerator",
]
