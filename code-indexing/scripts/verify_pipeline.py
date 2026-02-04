#!/usr/bin/env python3
"""
🔍 Pipeline Verification Script

This script tests each step of the code indexing pipeline:
1. AST parsing (tree-sitter)
2. Chunking (Chonkie)
3. Embedding generation
4. pgvector upload

Run from: /Users/radprk/scopedocs/code-indexing
Command: python scripts/verify_pipeline.py
"""

import os
import sys
import hashlib
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

def header(text):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

def success(text):
    print(f"{GREEN}✅ {text}{RESET}")

def fail(text):
    print(f"{RED}❌ {text}{RESET}")

def info(text):
    print(f"{YELLOW}ℹ️  {text}{RESET}")

def step(num, text):
    print(f"\n{BOLD}Step {num}: {text}{RESET}")
    print("-" * 40)


# =============================================================================
# STEP 1: Verify tree-sitter AST parsing
# =============================================================================
def test_ast_parsing():
    step(1, "Tree-sitter AST Parsing")
    
    try:
        from tree_sitter_language_pack import get_parser
        success("tree_sitter_language_pack imported")
    except ImportError as e:
        fail(f"tree_sitter_language_pack not installed: {e}")
        info("Run: pip install tree-sitter-language-pack")
        return False
    
    # Parse a sample file
    parser = get_parser('python')
    
    sample_code = '''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

class User:
    def __init__(self, id: int):
        self.id = id
'''
    
    tree = parser.parse(sample_code.encode())
    root = tree.root_node
    
    print(f"\nParsed sample code. Root node: {root.type}")
    print(f"Children: {len(root.children)}")
    
    # Find functions and classes
    nodes = []
    def walk(node):
        if node.type in ('function_definition', 'class_definition'):
            name_node = next((c for c in node.children if c.type == 'identifier'), None)
            name = name_node.text.decode() if name_node else "?"
            nodes.append((node.type, name, node.start_point[0]+1, node.end_point[0]+1))
        for child in node.children:
            walk(child)
    
    walk(root)
    
    print("\nFound AST nodes:")
    for node_type, name, start, end in nodes:
        print(f"  {node_type}: {name} [lines {start}-{end}]")
    
    if len(nodes) >= 2:  # At least function + class
        success("AST parsing works correctly")
        return True
    else:
        fail("AST parsing didn't find expected nodes")
        return False


# =============================================================================
# STEP 2: Verify chunking
# =============================================================================
def test_chunking():
    step(2, "Code Chunking (Chonkie)")
    
    try:
        from indexing.chunker import chunk_code_file, CodeChunk
        success("Chunker module imported")
    except ImportError as e:
        fail(f"Chunker import failed: {e}")
        return False, []
    
    # Read a dummy file
    dummy_file = Path(__file__).parent.parent / "dummy_repo" / "auth.py"
    
    if not dummy_file.exists():
        fail(f"Dummy file not found: {dummy_file}")
        return False, []
    
    content = dummy_file.read_text()
    info(f"Read {len(content)} chars from {dummy_file.name}")
    
    # Chunk it
    chunks = chunk_code_file(content, str(dummy_file), max_tokens=512)
    
    print(f"\nChunked into {len(chunks)} chunks:")
    for chunk in chunks:
        preview = chunk.content[:50].replace('\n', '\\n')
        print(f"  Chunk {chunk.chunk_index}: lines {chunk.start_line}-{chunk.end_line}")
        print(f"    Hash: {chunk.chunk_hash[:16]}...")
        print(f"    Preview: {preview}...")
    
    if len(chunks) > 0:
        success(f"Chunking produced {len(chunks)} chunks")
        return True, chunks
    else:
        fail("Chunking produced no chunks")
        return False, []


# =============================================================================
# STEP 3: Verify embedding generation
# =============================================================================
def test_embeddings(chunks):
    step(3, "Embedding Generation")
    
    # Check for OpenAI key
    openai_key = os.environ.get('OPENAI_API_KEY')
    
    if not openai_key:
        info("OPENAI_API_KEY not set - skipping embedding test")
        info("To test embeddings, set: export OPENAI_API_KEY=sk-...")
        return None
    
    try:
        import openai
        success("openai package imported")
    except ImportError:
        fail("openai package not installed")
        info("Run: pip install openai")
        return None
    
    # Generate embedding for first chunk
    if not chunks:
        fail("No chunks to embed")
        return None
    
    client = openai.OpenAI(api_key=openai_key)
    
    test_text = chunks[0].content[:500]  # First 500 chars
    info(f"Generating embedding for {len(test_text)} chars...")
    
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=test_text,
        )
        
        embedding = response.data[0].embedding
        print(f"\nEmbedding generated:")
        print(f"  Dimensions: {len(embedding)}")
        print(f"  First 5 values: {embedding[:5]}")
        
        success(f"Embedding generated ({len(embedding)} dimensions)")
        return embedding
        
    except Exception as e:
        fail(f"Embedding generation failed: {e}")
        return None


# =============================================================================
# STEP 4: Verify pgvector upload
# =============================================================================
def test_pgvector(embedding, chunks):
    step(4, "pgvector Upload")
    
    # Check for Supabase connection
    dsn = os.environ.get('POSTGRES_DSN') or os.environ.get('DATABASE_URL')
    
    if not dsn:
        info("POSTGRES_DSN not set - skipping database test")
        info("Set in backend/.env or export directly")
        return False
    
    try:
        import asyncpg
        success("asyncpg imported")
    except ImportError:
        fail("asyncpg not installed")
        info("Run: pip install asyncpg")
        return False
    
    import asyncio
    
    async def check_pgvector():
        try:
            conn = await asyncpg.connect(dsn)
            success("Connected to Supabase")
            
            # Check if pgvector is enabled
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            
            if result:
                success("pgvector extension is enabled")
            else:
                fail("pgvector extension NOT enabled")
                info("Run in Supabase SQL editor: CREATE EXTENSION IF NOT EXISTS vector;")
                await conn.close()
                return False
            
            # Check if code_chunks table exists
            result = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'code_chunks'
                )
            """)
            
            if result:
                success("code_chunks table exists")
                
                # Count rows
                count = await conn.fetchval("SELECT COUNT(*) FROM code_chunks")
                info(f"Current rows in code_chunks: {count}")
            else:
                info("code_chunks table doesn't exist yet")
                info("Run migration: supabase/migrations/001_code_chunks.sql")
            
            # Test insert (if we have an embedding)
            if embedding and chunks:
                info("Testing insert with sample data...")
                
                chunk = chunks[0]
                test_repo_id = "00000000-0000-0000-0000-000000000000"
                file_path_hash = hashlib.sha256("test/file.py".encode()).hexdigest()
                
                # Insert test row
                await conn.execute("""
                    INSERT INTO code_chunks 
                    (repo_id, file_path_hash, chunk_hash, chunk_index, start_line, end_line, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (repo_id, file_path_hash, chunk_index) 
                    DO UPDATE SET embedding = EXCLUDED.embedding
                """,
                    test_repo_id,
                    file_path_hash,
                    chunk.chunk_hash,
                    chunk.chunk_index,
                    chunk.start_line,
                    chunk.end_line,
                    str(embedding),  # Convert list to string for pgvector
                )
                
                success("Test row inserted/updated")
                
                # Verify it's there
                row = await conn.fetchrow("""
                    SELECT id, chunk_index, start_line, end_line 
                    FROM code_chunks 
                    WHERE repo_id = $1 AND file_path_hash = $2
                """, test_repo_id, file_path_hash)
                
                if row:
                    success(f"Verified: chunk exists with id={row['id'][:8]}...")
                
                # Clean up test row
                await conn.execute("""
                    DELETE FROM code_chunks 
                    WHERE repo_id = $1 AND file_path_hash = $2
                """, test_repo_id, file_path_hash)
                info("Cleaned up test row")
            
            await conn.close()
            return True
            
        except Exception as e:
            fail(f"Database error: {e}")
            return False
    
    return asyncio.run(check_pgvector())


# =============================================================================
# MAIN
# =============================================================================
def main():
    header("🔍 Code Indexing Pipeline Verification")
    
    results = {}
    
    # Step 1: AST
    results['ast'] = test_ast_parsing()
    
    # Step 2: Chunking
    chunking_ok, chunks = test_chunking()
    results['chunking'] = chunking_ok
    
    # Step 3: Embeddings
    embedding = test_embeddings(chunks)
    results['embeddings'] = embedding is not None
    
    # Step 4: pgvector
    results['pgvector'] = test_pgvector(embedding, chunks)
    
    # Summary
    header("📊 Summary")
    
    for step_name, passed in results.items():
        if passed:
            success(f"{step_name}")
        elif passed is None:
            info(f"{step_name} (skipped)")
        else:
            fail(f"{step_name}")
    
    all_passed = all(v for v in results.values() if v is not None)
    
    if all_passed:
        print(f"\n{GREEN}{BOLD}🎉 All tests passed!{RESET}")
    else:
        print(f"\n{YELLOW}⚠️  Some tests need attention{RESET}")


if __name__ == "__main__":
    main()
