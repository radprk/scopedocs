#!/usr/bin/env python3
"""
Tree-sitter Setup Script

This script verifies that tree-sitter-python is properly installed and
working with Chonkie. Chonkie handles most of the tree-sitter setup
automatically, but this script can help diagnose issues.

When to run this:
    - After installing dependencies for the first time
    - If you encounter "tree-sitter" related errors
    - To verify your environment is correctly configured

Usage:
    python scripts/setup_tree_sitter.py
"""

import sys


def check_chonkie():
    """Check if Chonkie is installed and working."""
    print("Checking Chonkie installation...")

    try:
        import chonkie
        print(f"  Chonkie version: {chonkie.__version__ if hasattr(chonkie, '__version__') else 'unknown'}")
        print("  Chonkie is installed.")
        return True
    except ImportError as e:
        print(f"  ERROR: Chonkie is not installed: {e}")
        print("  Run: pip install chonkie")
        return False


def check_code_chunker():
    """Check if CodeChunker can be instantiated."""
    print("\nChecking CodeChunker...")

    try:
        from chonkie import CodeChunker

        # Try to create a chunker
        chunker = CodeChunker(language="python", chunk_size=512)
        print("  CodeChunker instantiated successfully.")
        return chunker
    except Exception as e:
        print(f"  ERROR: Failed to create CodeChunker: {e}")
        return None


def test_chunking(chunker):
    """Test that chunking actually works."""
    print("\nTesting code chunking...")

    test_code = '''"""Test module."""

def hello_world():
    """Say hello."""
    print("Hello, World!")
    return True

def goodbye_world():
    """Say goodbye."""
    print("Goodbye, World!")
    return False

class Greeter:
    """A greeter class."""

    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Hello, {self.name}!"
'''

    try:
        chunks = chunker.chunk(test_code)
        print(f"  Successfully chunked test code into {len(chunks)} chunks:")

        for i, chunk in enumerate(chunks):
            preview = chunk.text[:50].replace("\n", "\\n")
            print(f"    Chunk {i}: {preview}...")

        return True
    except Exception as e:
        print(f"  ERROR: Chunking failed: {e}")
        return False


def main():
    """Run all setup checks."""
    print("=" * 60)
    print("Tree-sitter Setup Verification")
    print("=" * 60)

    all_passed = True

    # Check Chonkie
    if not check_chonkie():
        all_passed = False

    # Check CodeChunker
    chunker = check_code_chunker()
    if chunker is None:
        all_passed = False
    else:
        # Test chunking
        if not test_chunking(chunker):
            all_passed = False

    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: All checks passed!")
        print("Tree-sitter-python is ready to use with Chonkie.")
        print("=" * 60)
        return 0
    else:
        print("FAILED: Some checks did not pass.")
        print("Please review the errors above and install missing dependencies.")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
