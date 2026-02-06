"""Together.ai client wrapper for embeddings and generation."""

import os
import logging
import asyncio
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

# Configuration
TOGETHER_API_BASE = "https://api.together.xyz/v1"

# Model configurations
# BGE-large is reliable but has 512 token limit
# We'll use aggressive truncation to fit
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIMS = 1024
EMBEDDING_MAX_TOKENS = 512


def truncate_for_embedding(text: str, max_chars: int = 1000) -> str:
    """
    Truncate text to fit within BGE's 512 token limit.
    
    Code averages ~0.5 tokens per char, so 1000 chars ≈ 500 tokens.
    This leaves some buffer for safety.
    """
    if not text:
        return text
    
    if len(text) <= max_chars:
        return text
    
    return text[:max_chars] + "..."

# Generation models (serverless - no dedicated endpoint needed)
CODE_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"  # Great for code, available serverless
GENERAL_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"


@dataclass
class EmbeddingResult:
    """Result from embedding request."""
    embeddings: List[List[float]]
    model: str
    usage: Dict[str, int]


@dataclass
class GenerationResult:
    """Result from generation request."""
    text: str
    model: str
    usage: Dict[str, int]
    finish_reason: str


class TogetherClient:
    """Async client for Together.ai API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TOGETHER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "TOGETHER_API_KEY environment variable is required. "
                "Get your key at https://api.together.xyz/settings/api-keys"
            )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=TOGETHER_API_BASE,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def embed(
        self,
        texts: List[str],
        model: str = EMBEDDING_MODEL,
    ) -> EmbeddingResult:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed
            model: Embedding model to use

        Returns:
            EmbeddingResult with embeddings and metadata
        """
        client = await self._get_client()

        # Truncate texts to fit within model's token limit
        truncated_texts = [truncate_for_embedding(t) for t in texts]

        # Together.ai has a limit of ~100 texts per request
        # Batch if needed
        batch_size = 50
        all_embeddings = []

        for i in range(0, len(truncated_texts), batch_size):
            batch = truncated_texts[i : i + batch_size]

            response = await client.post(
                "/embeddings",
                json={
                    "model": model,
                    "input": batch,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Sort by index to maintain order
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            all_embeddings.extend([item["embedding"] for item in sorted_data])

        return EmbeddingResult(
            embeddings=all_embeddings,
            model=model,
            usage={"total_tokens": sum(len(t.split()) for t in texts)},  # Approximate
        )

    async def embed_single(
        self,
        text: str,
        model: str = EMBEDDING_MODEL,
    ) -> List[float]:
        """Embed a single text and return the embedding vector."""
        result = await self.embed([text], model=model)
        return result.embeddings[0]

    async def generate(
        self,
        prompt: str,
        model: str = CODE_MODEL,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
        stop: Optional[List[str]] = None,
    ) -> GenerationResult:
        """
        Generate text completion.

        Args:
            prompt: The user prompt
            model: Model to use for generation
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            system_prompt: Optional system prompt
            stop: Optional stop sequences

        Returns:
            GenerationResult with generated text and metadata
        """
        client = await self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            payload["stop"] = stop
            
        response = await client.post("/chat/completions", json=payload)
        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Together.ai error ({response.status_code}): {error_text}")
            raise Exception(f"Together.ai error: {error_text}")
        data = response.json()

        choice = data["choices"][0]
        return GenerationResult(
            text=choice["message"]["content"],
            model=model,
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "unknown"),
        )

    async def generate_code_doc(
        self,
        code: str,
        file_path: str,
        language: str,
        doc_type: str = "file",
    ) -> str:
        """
        Generate documentation for code.

        Args:
            code: The source code
            file_path: Path to the file
            language: Programming language
            doc_type: Type of doc to generate ('file', 'function', 'overview')

        Returns:
            Generated markdown documentation
        """
        system_prompt = """You are a technical documentation expert. Generate clear,
concise documentation that helps developers understand code quickly.

Guidelines:
- Start with a one-line summary
- Explain WHAT the code does and WHY it exists
- Highlight key functions, classes, or exports
- Note any important dependencies or side effects
- Use markdown formatting
- Keep it scannable with headers and bullet points
- Don't repeat the code verbatim, explain it"""

        if doc_type == "file":
            prompt = f"""Generate documentation for this {language} file.

File: {file_path}

```{language}
{code}
```

Generate markdown documentation with:
1. A one-line summary
2. ## Overview - what this file does
3. ## Key Components - main functions/classes with brief descriptions
4. ## Usage - how to use this code (if applicable)
5. ## Dependencies - what this depends on"""

        elif doc_type == "function":
            prompt = f"""Generate documentation for this {language} function/method.

File: {file_path}

```{language}
{code}
```

Generate concise documentation explaining:
- What it does
- Parameters and return value
- Any side effects or important notes"""

        else:  # overview
            prompt = f"""Generate a high-level overview for this codebase component.

File: {file_path}

```{language}
{code}
```

Generate a brief overview suitable for onboarding documentation."""

        result = await self.generate(
            prompt=prompt,
            model=CODE_MODEL,
            system_prompt=system_prompt,
            temperature=0.1,
        )
        return result.text

    async def summarize_for_embedding(
        self,
        content: str,
        content_type: str = "code",
    ) -> str:
        """
        Generate a summary optimized for embedding/retrieval.

        This creates a dense text representation that captures
        the semantic meaning for better search results.
        """
        if content_type == "code":
            prompt = f"""Summarize this code in 2-3 sentences for search indexing.
Focus on: what it does, key functions/classes, purpose.

```
{content}
```

Summary:"""
        else:
            prompt = f"""Summarize this text in 2-3 sentences for search indexing.
Capture the key points and topics.

{content}

Summary:"""

        result = await self.generate(
            prompt=prompt,
            model=GENERAL_MODEL,
            max_tokens=200,
            temperature=0.0,
        )
        return result.text.strip()

    async def answer_question(
        self,
        question: str,
        context: List[Dict[str, str]],
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Answer a question given retrieved context (RAG).

        Args:
            question: The user's question
            context: List of relevant context items with 'content' and 'source'
            chat_history: Optional previous messages

        Returns:
            Answer string
        """
        system_prompt = """You are a helpful assistant that answers questions about code.
Use the provided context to answer accurately. If the context doesn't contain
enough information, say so. Always cite your sources by mentioning file names."""

        # Format context
        context_text = "\n\n".join(
            f"### {item.get('source', 'Source')}\n{item['content']}"
            for item in context
        )

        prompt = f"""Context:
{context_text}

Question: {question}

Answer the question based on the context above. Cite specific files when relevant."""

        # Include chat history if provided
        messages = []
        if chat_history:
            for msg in chat_history[-10:]:  # Last 10 messages
                messages.append(msg)

        result = await self.generate(
            prompt=prompt,
            model=CODE_MODEL,
            system_prompt=system_prompt,
            temperature=0.2,
        )
        return result.text


# Singleton client instance
_client: Optional[TogetherClient] = None


def get_client() -> TogetherClient:
    """Get or create the global Together client."""
    global _client
    if _client is None:
        _client = TogetherClient()
    return _client


async def close_client():
    """Close the global client."""
    global _client
    if _client:
        await _client.close()
        _client = None
