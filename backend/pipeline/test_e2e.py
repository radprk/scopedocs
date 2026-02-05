#!/usr/bin/env python3
"""
End-to-end test script for the ScopeDocs pipeline.

This script tests the full pipeline:
1. Generate mock data (code, PRs, Slack messages, Linear issues)
2. Chunk the code using AST-aware chunking
3. Embed the chunks in pgvector
4. Generate documentation for 4 audiences
5. Create doc ↔ code links
6. Extract traceability (Linear tickets ↔ PRs ↔ Code)

Run with: python -m backend.pipeline.test_e2e

Requirements:
- PostgreSQL with pgvector extension
- TOGETHER_API_KEY environment variable (or run in mock mode)
"""

import asyncio
import os
import sys
import json
import hashlib
from datetime import datetime
from typing import Optional
from dataclasses import asdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def print_header(text: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_step(step: int, text: str):
    """Print a step indicator."""
    print(f"\n[Step {step}] {text}")
    print("-" * 50)


def print_progress(text: str):
    """Print progress message."""
    print(f"  → {text}")


def print_success(text: str):
    """Print success message."""
    print(f"  ✓ {text}")


def print_warning(text: str):
    """Print warning message."""
    print(f"  ⚠ {text}")


def print_error(text: str):
    """Print error message."""
    print(f"  ✗ {text}")


def print_data(label: str, data, indent: int = 4):
    """Print data with label."""
    prefix = " " * indent
    if isinstance(data, (dict, list)):
        print(f"{prefix}{label}:")
        for line in json.dumps(data, indent=2, default=str).split("\n"):
            print(f"{prefix}  {line}")
    else:
        print(f"{prefix}{label}: {data}")


class MockTogetherClient:
    """Mock client for testing without API calls."""

    async def embed(self, texts, model=None):
        """Return mock embeddings."""
        import random
        embeddings = []
        for text in texts:
            # Generate deterministic "embedding" based on text hash
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
            random.seed(seed)
            embedding = [random.uniform(-1, 1) for _ in range(1024)]
            embeddings.append(embedding)

        class Result:
            def __init__(self, embs):
                self.embeddings = embs

        return Result(embeddings)

    async def embed_single(self, text):
        """Return a single mock embedding."""
        result = await self.embed([text])
        return result.embeddings[0]

    async def generate(self, prompt, system_prompt=None, temperature=0.3, max_tokens=2000):
        """Return mock generated text."""
        class Result:
            text = f"""# Mock Generated Documentation

## Overview
This is mock documentation generated for testing purposes.

## Key Components
- Component A: Handles the primary functionality
- Component B: Manages data processing
- Component C: Provides API endpoints

## Architecture
The system uses a layered architecture with clear separation of concerns.

## Notes
Generated at {datetime.now().isoformat()}
Prompt length: {len(prompt)} characters
"""
        return Result()

    async def generate_code_doc(self, code, file_path, language, doc_type):
        """Return mock code documentation."""
        return f"""# {file_path.split('/')[-1]}

## Purpose
This file implements core functionality for the {file_path.split('/')[0] if '/' in file_path else 'main'} module.

## Functions
- Main entry points and handlers
- Helper utilities
- Data transformations

## Dependencies
Uses standard library and project modules.

## Usage Example
```{language}
# Import and use the module
from {file_path.replace('/', '.').replace('.py', '')} import main
result = main()
```
"""

    async def answer_question(self, question, context, chat_history=None):
        """Return mock answer."""
        return f"Based on the context provided, here's my answer to '{question}'..."


async def run_e2e_test(use_mock_ai: bool = True, db_url: Optional[str] = None):
    """Run the end-to-end pipeline test."""

    print_header("ScopeDocs E2E Pipeline Test")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Mock AI Mode: {use_mock_ai}")
    print(f"Database URL: {db_url or 'Using default from environment'}")

    # ==========================================================================
    # Step 1: Generate Mock Data
    # ==========================================================================
    print_step(1, "Generating Mock Data")

    from backend.pipeline.mock_data import MockDataGenerator

    generator = MockDataGenerator()
    mock_data = generator.generate_scopedocs_data()

    print_success(f"Generated {len(mock_data.files)} code files")
    for f in mock_data.files:
        print_progress(f"  {f.path} ({f.language}, {len(f.content)} bytes)")

    print_success(f"Generated {len(mock_data.prs)} pull requests")
    for pr in mock_data.prs:
        print_progress(f"  PR #{pr.number}: {pr.title}")

    print_success(f"Generated {len(mock_data.linear_issues)} Linear issues")
    for issue in mock_data.linear_issues:
        print_progress(f"  {issue.identifier}: {issue.title}")

    print_success(f"Generated {len(mock_data.slack_messages)} Slack messages")
    for msg in mock_data.slack_messages[:3]:
        print_progress(f"  #{msg.channel}: {msg.content[:50]}...")
    if len(mock_data.slack_messages) > 3:
        print_progress(f"  ... and {len(mock_data.slack_messages) - 3} more")

    print_success(f"Linear team key: {mock_data.team_key}")

    # ==========================================================================
    # Step 2: Initialize Services
    # ==========================================================================
    print_step(2, "Initializing Services")

    # Try to connect to database
    try:
        import asyncpg
        pool = await asyncpg.create_pool(
            db_url or os.environ.get("DATABASE_URL", "postgresql://localhost:5432/scopedocs"),
            min_size=1,
            max_size=5,
        )
        print_success("Connected to PostgreSQL database")

        # Check for pgvector extension
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            if result:
                print_success("pgvector extension is available")
            else:
                print_warning("pgvector extension not installed - embeddings will fail")

    except Exception as e:
        print_error(f"Database connection failed: {e}")
        print_warning("Running in database-less mode (limited testing)")
        pool = None

    # Initialize AI client
    if use_mock_ai:
        client = MockTogetherClient()
        print_success("Using mock AI client (no API calls)")
    else:
        if not os.environ.get("TOGETHER_API_KEY"):
            print_error("TOGETHER_API_KEY not set")
            print_warning("Falling back to mock AI client")
            client = MockTogetherClient()
        else:
            from backend.ai.client import TogetherClient
            client = TogetherClient()
            print_success("Using real Together.ai client")

    # ==========================================================================
    # Step 3: Test Code Chunking
    # ==========================================================================
    print_step(3, "Testing Code Chunking")

    # Try to use the real chunker
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "code-indexing", "src"
        ))
        from indexing.chunker import chunk_code
        print_success("Loaded AST-aware chunker from code-indexing module")
        use_real_chunker = True
    except ImportError as e:
        print_warning(f"Could not load real chunker: {e}")
        print_progress("Using simple line-based chunking fallback")
        use_real_chunker = False

    all_chunks = []
    for file in mock_data.files:
        print_progress(f"Chunking {file.path}...")

        if use_real_chunker:
            try:
                chunks = chunk_code(file.content, file.language, file.path)
                print_success(f"  → {len(chunks)} chunks (AST-aware)")
            except Exception as e:
                # Fallback to simple chunking
                chunks = simple_chunk(file.content, file.path)
                print_warning(f"  → {len(chunks)} chunks (fallback, error: {e})")
        else:
            chunks = simple_chunk(file.content, file.path)
            print_success(f"  → {len(chunks)} chunks (line-based)")

        all_chunks.extend(chunks)

    print_success(f"Total chunks: {len(all_chunks)}")

    # Show sample chunk
    if all_chunks:
        sample = all_chunks[0]
        print_data("Sample chunk", {
            "file_path": sample.get("file_path", "N/A"),
            "start_line": sample.get("start_line", 0),
            "end_line": sample.get("end_line", 0),
            "content_preview": sample.get("content", "")[:100] + "...",
        })

    # ==========================================================================
    # Step 4: Test Embeddings
    # ==========================================================================
    print_step(4, "Testing Embeddings")

    if pool:
        from backend.ai.embeddings import EmbeddingService, CodeChunk

        embed_service = EmbeddingService(pool, client)

        # Convert chunks to CodeChunk objects
        code_chunks = []
        for c in all_chunks[:10]:  # Limit for testing
            code_chunks.append(CodeChunk(
                file_path=c.get("file_path", "unknown"),
                content=c.get("content", ""),
                start_line=c.get("start_line", 0),
                end_line=c.get("end_line", 0),
                chunk_index=c.get("chunk_index", 0),
                language=c.get("language", "python"),
            ))

        workspace_id = "test-workspace-" + datetime.now().strftime("%Y%m%d%H%M%S")
        repo_name = "scopedocs/scopedocs"
        commit_sha = "abc123"

        try:
            result = await embed_service.embed_code_chunks(
                workspace_id=workspace_id,
                repo_full_name=repo_name,
                commit_sha=commit_sha,
                chunks=code_chunks,
            )

            print_success(f"Embedded {result['total_chunks']} chunks")
            print_data("Embedding result", result)
        except Exception as e:
            print_error(f"Embedding failed: {e}")
    else:
        print_warning("Skipping embeddings (no database)")
        workspace_id = "test-workspace"
        repo_name = "scopedocs/scopedocs"

    # ==========================================================================
    # Step 5: Test Documentation Generation (Multi-Audience)
    # ==========================================================================
    print_step(5, "Testing Multi-Audience Documentation Generation")

    if pool:
        from backend.ai.audiences import Audience, MultiAudienceDocService

        doc_service = MultiAudienceDocService(pool, client)

        # Generate docs for first file
        test_file = mock_data.files[0]

        print_progress(f"Generating docs for {test_file.path}...")

        for audience in Audience:
            print_progress(f"  Generating for {audience.value}...")

            try:
                doc = await doc_service.generate_for_audience(
                    audience=audience,
                    workspace_id=workspace_id,
                    repo_full_name=repo_name,
                    file_path=test_file.path,
                    code=test_file.content,
                    language=test_file.language,
                    commit_sha=commit_sha,
                )

                print_success(f"    → Generated '{doc.title}' ({len(doc.content)} chars)")
                print_data("Content preview", doc.content[:200] + "...", indent=6)
            except Exception as e:
                print_error(f"    → Failed: {e}")
    else:
        print_warning("Skipping documentation generation (no database)")

    # ==========================================================================
    # Step 6: Test Traceability Extraction
    # ==========================================================================
    print_step(6, "Testing Traceability Extraction")

    from backend.pipeline.traceability import TraceabilityExtractor

    if pool:
        extractor = TraceabilityExtractor(pool)
    else:
        extractor = TraceabilityExtractor(None)

    # Set team keys manually for testing
    extractor._team_keys_cache = {workspace_id: [mock_data.team_key]}

    all_links = []

    # Extract from PRs
    print_progress("Extracting traceability from PRs...")
    for pr in mock_data.prs:
        result = extractor.extract_from_pr(
            pr_number=pr.number,
            pr_title=pr.title,
            pr_body=pr.body or "",
            files_changed=[f.path for f in mock_data.files[:2]],
            repo_full_name=repo_name,
        )
        all_links.extend(result.links)

        if result.links:
            print_success(f"  PR #{pr.number}: Found {len(result.links)} links")
            for link in result.links:
                print_progress(f"    → {link.link_type}: {link.source_type}:{link.source_id} ↔ {link.target_type}:{link.target_id}")

    # Extract from Slack messages
    print_progress("Extracting traceability from Slack messages...")
    for msg in mock_data.slack_messages:
        result = extractor.extract_from_message(
            message_id=msg.external_id,
            content=msg.content,
            channel=msg.channel,
            source="slack",
            thread_context=msg.thread_context,
        )
        all_links.extend(result.links)

        if result.links:
            print_success(f"  Message {msg.external_id[:8]}: Found {len(result.links)} links")

    print_success(f"Total traceability links extracted: {len(all_links)}")

    # Store links if we have a database
    if pool and all_links:
        try:
            stored = await extractor.store_links(workspace_id, all_links)
            print_success(f"Stored {stored} links in database")
        except Exception as e:
            print_error(f"Failed to store links: {e}")

    # ==========================================================================
    # Step 7: Test Search (if database available)
    # ==========================================================================
    print_step(7, "Testing Semantic Search")

    if pool:
        from backend.ai.search import SearchService

        search_service = SearchService(pool, client)

        test_queries = [
            "How does the pipeline work?",
            "What is the embedding process?",
            "Find documentation generation code",
        ]

        for query in test_queries:
            print_progress(f"Searching: '{query}'")

            try:
                results = await search_service.search_code(
                    workspace_id=workspace_id,
                    query=query,
                    limit=3,
                )

                if results.results:
                    print_success(f"  → Found {results.total_found} results")
                    for r in results.results[:2]:
                        print_progress(f"    {r.file_path} (score: {r.score:.3f})")
                else:
                    print_warning("  → No results found")
            except Exception as e:
                print_error(f"  → Search failed: {e}")
    else:
        print_warning("Skipping search test (no database)")

    # ==========================================================================
    # Step 8: Summary
    # ==========================================================================
    print_step(8, "Test Summary")

    print("\nPipeline Components Tested:")
    print("  ✓ Mock Data Generation")
    print("  ✓ Code Chunking")
    print(f"  {'✓' if pool else '○'} Embeddings (pgvector)")
    print(f"  {'✓' if pool else '○'} Multi-Audience Doc Generation")
    print("  ✓ Traceability Extraction")
    print(f"  {'✓' if pool else '○'} Semantic Search")

    print("\nData Generated:")
    print(f"  • {len(mock_data.files)} code files")
    print(f"  • {len(all_chunks)} code chunks")
    print(f"  • {len(mock_data.prs)} pull requests")
    print(f"  • {len(mock_data.linear_issues)} Linear issues")
    print(f"  • {len(mock_data.slack_messages)} Slack messages")
    print(f"  • {len(all_links)} traceability links")

    print_header("E2E Test Complete!")

    # Cleanup
    if pool:
        await pool.close()


def simple_chunk(content: str, file_path: str, max_lines: int = 50) -> list:
    """Simple line-based chunking fallback."""
    lines = content.split("\n")
    chunks = []

    for i in range(0, len(lines), max_lines):
        chunk_lines = lines[i:i + max_lines]
        chunks.append({
            "file_path": file_path,
            "content": "\n".join(chunk_lines),
            "start_line": i + 1,
            "end_line": min(i + max_lines, len(lines)),
            "chunk_index": len(chunks),
            "language": file_path.split(".")[-1] if "." in file_path else "text",
        })

    return chunks


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run ScopeDocs E2E pipeline test")
    parser.add_argument(
        "--real-ai",
        action="store_true",
        help="Use real Together.ai API (requires TOGETHER_API_KEY)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        help="PostgreSQL connection URL",
    )

    args = parser.parse_args()

    asyncio.run(run_e2e_test(
        use_mock_ai=not args.real_ai,
        db_url=args.db_url,
    ))
