"""Voyage AI async embedding wrapper.

Model: voyage-3-large (1024 dimensions).
NO pydantic_ai imports. Pure Python.
"""

from collections.abc import Sequence
from functools import lru_cache

import structlog
import voyageai
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings

logger = structlog.get_logger(__name__)

VOYAGE_BATCH_LIMIT = 128


@lru_cache(maxsize=1)
def _get_client() -> voyageai.AsyncClient:
    """Cached Voyage AI async client."""
    settings = get_settings()
    return voyageai.AsyncClient(api_key=settings.voyage_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    """Embed a list of documents using Voyage AI.

    Batches at 128 per Voyage limit. input_type="document".
    Retries 3 attempts with exponential backoff.

    Args:
        texts: Document texts to embed.

    Returns:
        List of embedding vectors (each is a list of floats).
    """
    if not texts:
        return []

    settings = get_settings()
    client = _get_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), VOYAGE_BATCH_LIMIT):
        batch = texts[i : i + VOYAGE_BATCH_LIMIT]
        logger.info(
            "embedding_batch",
            batch_start=i,
            batch_size=len(batch),
            model=settings.voyage_embedding_model,
        )
        result = await client.embed(
            texts=batch,
            model=settings.voyage_embedding_model,
            input_type="document",
        )
        all_embeddings.extend(result.embeddings)

    logger.info("embeddings_complete", total=len(all_embeddings))
    return all_embeddings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def embed_query(query: str) -> list[float]:
    """Embed a single query string.

    input_type="query" for retrieval-optimized embeddings.
    Retries 3 attempts with exponential backoff.

    Args:
        query: Query text to embed.

    Returns:
        Embedding vector.
    """
    settings = get_settings()
    client = _get_client()
    result = await client.embed(
        texts=[query],
        model=settings.voyage_embedding_model,
        input_type="query",
    )
    return result.embeddings[0]


async def embed_queries(queries: Sequence[str]) -> list[list[float]]:
    """Embed multiple queries concurrently.

    Args:
        queries: Query texts to embed.

    Returns:
        List of embedding vectors.
    """
    import asyncio

    results = await asyncio.gather(*[embed_query(q) for q in queries])
    return list(results)
