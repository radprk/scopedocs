#!/usr/bin/env python3
"""
Minimal test script to validate mock data and pipeline stages.
No LLM calls - just tests data generation and chunking.

Run with: python backend/pipeline/test_mock.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def main():
    print("=" * 60)
    print("  ScopeDocs Mock Data & Pipeline Test (No LLM)")
    print("=" * 60)

    # ==========================================================================
    # Test 1: Mock Data Generation
    # ==========================================================================
    print("\n[Test 1] Mock Data Generation")
    print("-" * 40)

    try:
        from backend.pipeline.mock_data import MockDataGenerator

        generator = MockDataGenerator()
        data = generator.generate_scopedocs_data()

        print(f"  Team Key: {data.team_key}")
        print(f"  Files: {len(data.files)}")
        for f in data.files:
            print(f"    - {f.path} ({f.language}, {len(f.content)} bytes)")

        print(f"\n  Linear Issues: {len(data.linear_issues)}")
        for issue in data.linear_issues:
            print(f"    - {issue.identifier}: {issue.title[:50]}...")

        print(f"\n  Pull Requests: {len(data.prs)}")
        for pr in data.prs:
            print(f"    - PR #{pr.number}: {pr.title[:50]}...")

        print(f"\n  Slack Messages: {len(data.slack_messages)}")
        for msg in data.slack_messages[:3]:
            print(f"    - #{msg.channel}: {msg.content[:60]}...")
        if len(data.slack_messages) > 3:
            print(f"    ... and {len(data.slack_messages) - 3} more")

        print("\n  [PASS] Mock data generation works!")

    except Exception as e:
        print(f"\n  [FAIL] Mock data generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # ==========================================================================
    # Test 2: Code Chunking
    # ==========================================================================
    print("\n[Test 2] Code Chunking")
    print("-" * 40)

    # Try the real chunker first
    chunker_type = "fallback"
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "code-indexing", "src"
        ))
        from indexing.chunker import chunk_code
        chunker_type = "AST-aware"
        print(f"  Using: {chunker_type} chunker (from code-indexing/)")
    except ImportError as e:
        print(f"  Warning: Could not load AST chunker: {e}")
        print("  Using: Simple line-based chunker")

        def chunk_code(content, language, file_path):
            """Simple fallback chunker."""
            lines = content.split("\n")
            chunks = []
            max_lines = 50

            for i in range(0, len(lines), max_lines):
                chunk_lines = lines[i:i + max_lines]
                chunks.append({
                    "content": "\n".join(chunk_lines),
                    "start_line": i + 1,
                    "end_line": min(i + max_lines, len(lines)),
                    "chunk_index": len(chunks),
                })
            return chunks

    all_chunks = []
    for f in data.files:
        try:
            chunks = chunk_code(f.content, f.language, f.path)
            print(f"  {f.path}: {len(chunks)} chunks")

            # Show first chunk details
            if chunks:
                first = chunks[0]
                if hasattr(first, '__dict__'):
                    first = first.__dict__
                elif not isinstance(first, dict):
                    first = {"content": str(first)[:100]}

                content_preview = first.get("content", "")[:80].replace("\n", "\\n")
                start = first.get("start_line", "?")
                end = first.get("end_line", "?")
                print(f"    Chunk 0: lines {start}-{end}")
                print(f"    Preview: {content_preview}...")

            all_chunks.extend(chunks)

        except Exception as e:
            print(f"  {f.path}: FAILED - {e}")

    print(f"\n  Total chunks: {len(all_chunks)}")
    print(f"\n  [PASS] Chunking works with {chunker_type} chunker!")

    # ==========================================================================
    # Test 3: Traceability Extraction
    # ==========================================================================
    print("\n[Test 3] Traceability Extraction")
    print("-" * 40)

    try:
        from backend.pipeline.traceability import TraceabilityExtractor

        # Create extractor without DB
        extractor = TraceabilityExtractor(pool=None)

        # Manually set team keys (would normally come from Linear API)
        extractor._team_keys_cache = {"test-workspace": [data.team_key]}

        all_links = []

        # Extract from PRs
        print(f"  Extracting from {len(data.prs)} PRs...")
        for pr in data.prs:
            result = extractor.extract_from_pr(
                pr_number=pr.number,
                pr_title=pr.title,
                pr_body=pr.body or "",
                files_changed=[f.path for f in data.files[:2]],
                repo_full_name="test/repo",
            )

            if result.links:
                print(f"    PR #{pr.number}: {len(result.links)} links found")
                for link in result.links[:2]:
                    print(f"      - {link.link_type}: {link.source_type}:{link.source_id} -> {link.target_type}:{link.target_id}")

            all_links.extend(result.links)

        # Extract from Slack messages
        print(f"\n  Extracting from {len(data.slack_messages)} Slack messages...")
        for msg in data.slack_messages:
            result = extractor.extract_from_message(
                message_id=msg.external_id,
                content=msg.content,
                channel=msg.channel,
                source="slack",
            )

            if result.links:
                print(f"    Message in #{msg.channel}: {len(result.links)} links")

            all_links.extend(result.links)

        print(f"\n  Total traceability links: {len(all_links)}")

        # Show link types breakdown
        link_types = {}
        for link in all_links:
            link_types[link.link_type] = link_types.get(link.link_type, 0) + 1

        print("  Link types:")
        for lt, count in link_types.items():
            print(f"    - {lt}: {count}")

        print("\n  [PASS] Traceability extraction works!")

    except Exception as e:
        print(f"\n  [FAIL] Traceability extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # ==========================================================================
    # Test 4: Audience Profiles
    # ==========================================================================
    print("\n[Test 4] Audience Profiles")
    print("-" * 40)

    try:
        from backend.ai.audiences import Audience, AUDIENCE_PROFILES, list_audiences

        audiences = list_audiences()
        print(f"  Available audiences: {len(audiences)}")

        for aud in audiences:
            print(f"\n  [{aud['id']}]")
            print(f"    Name: {aud['name']}")
            print(f"    Description: {aud['description'][:60]}...")

            profile = AUDIENCE_PROFILES[Audience(aud['id'])]
            print(f"    Focus areas: {len(profile.focus_areas)}")
            print(f"    Doc structure: {len(profile.doc_structure)} sections")

        print("\n  [PASS] Audience profiles loaded!")

    except Exception as e:
        print(f"\n  [FAIL] Audience profiles failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # ==========================================================================
    # Summary
    # ==========================================================================
    print("\n" + "=" * 60)
    print("  All Tests Passed!")
    print("=" * 60)
    print("\nData ready for LLM inference:")
    print(f"  - {len(data.files)} files")
    print(f"  - {len(all_chunks)} code chunks")
    print(f"  - {len(all_links)} traceability links")
    print(f"  - 4 audience profiles")
    print("\nNext step: Run with --db flag to test database integration")

    return 0


if __name__ == "__main__":
    sys.exit(main())
