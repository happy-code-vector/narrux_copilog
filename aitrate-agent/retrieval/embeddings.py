"""Embedding wrapper — supports local, Gemini, and Voyage AI.

Provider is selected by settings.embedding_provider:
- 'local': uses sentence-transformers
- 'gemini': uses Google Gemini API (text-embedding-004)
- 'voyage': uses Voyage AI API (voyage-3-large)

NO pydantic_ai imports. Pure Python.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings

logger = structlog.get_logger(__name__)

# ─── Local Model (sentence-transformers) ────────────────────────────────────

_local_model = None


def _get_local_model():
    """Lazy-load the local sentence-transformers model."""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        logger.info("loading_local_model", model=settings.embedding_model)
        _local_model = SentenceTransformer(settings.embedding_model)
        logger.info("local_model_loaded", model=settings.embedding_model)
    return _local_model


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Embed texts using local sentence-transformers model."""
    model = _get_local_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def _embed_query_local(query: str) -> list[float]:
    """Embed a single query using local model."""
    model = _get_local_model()
    embedding = model.encode([query], show_progress_bar=False, normalize_embeddings=True)
    return embedding[0].tolist()


# ─── Google Gemini ──────────────────────────────────────────────────────────

_gemini_client = None


def _get_gemini_client():
    """Lazy-load the Google Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        settings = get_settings()
        _gemini_client = genai.Client(api_key=settings.google_api_key)
    return _gemini_client


GEMINI_BATCH_LIMIT = 100


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def _embed_gemini(texts: Sequence[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Embed texts using Google Gemini API.

    Note: google-genai v2.x requires one call per text (batch not supported).
    """
    from google.genai.types import EmbedContentConfig

    client = _get_gemini_client()
    settings = get_settings()
    all_embeddings: list[list[float]] = []

    logger.info(
        "embedding_batch",
        count=len(texts),
        model=settings.embedding_model,
    )

    # google-genai v2.x: one call per text
    for text in texts:
        result = client.models.embed_content(
            model=settings.embedding_model,
            contents=text,
            config=EmbedContentConfig(task_type=task_type),
        )
        all_embeddings.append(result.embeddings[0].values)

    return all_embeddings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def _embed_query_gemini(query: str) -> list[float]:
    """Embed a single query using Google Gemini API."""
    from google.genai.types import EmbedContentConfig

    client = _get_gemini_client()
    settings = get_settings()
    result = client.models.embed_content(
        model=settings.embedding_model,
        contents=query,
        config=EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return result.embeddings[0].values


# ─── Voyage AI (API) ────────────────────────────────────────────────────────

_voyage_client = None


def _get_voyage_client():
    """Lazy-load the Voyage AI async client."""
    global _voyage_client
    if _voyage_client is None:
        import voyageai

        settings = get_settings()
        _voyage_client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    return _voyage_client


VOYAGE_BATCH_LIMIT = 128


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def _embed_voyage(texts: Sequence[str], input_type: str = "document") -> list[list[float]]:
    """Embed texts using Voyage AI API."""
    settings = get_settings()
    client = _get_voyage_client()
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
            input_type=input_type,
        )
        all_embeddings.extend(result.embeddings)

    return all_embeddings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def _embed_query_voyage(query: str) -> list[float]:
    """Embed a single query using Voyage AI API."""
    settings = get_settings()
    client = _get_voyage_client()
    result = await client.embed(
        texts=[query],
        model=settings.voyage_embedding_model,
        input_type="query",
    )
    return result.embeddings[0]


# ─── Public API ─────────────────────────────────────────────────────────────

async def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    """Embed a list of documents.

    Uses provider based on settings.embedding_provider.
    """
    if not texts:
        return []

    settings = get_settings()
    provider = settings.embedding_provider

    if provider == "local":
        logger.info("embedding_documents", provider="local", count=len(texts))
        return _embed_local(list(texts))
    elif provider == "gemini":
        logger.info("embedding_documents", provider="gemini", count=len(texts))
        return await _embed_gemini(texts, task_type="RETRIEVAL_DOCUMENT")
    else:
        logger.info("embedding_documents", provider="voyage", count=len(texts))
        return await _embed_voyage(texts, input_type="document")


async def embed_query(query: str) -> list[float]:
    """Embed a single query string.

    Uses provider based on settings.embedding_provider.
    """
    settings = get_settings()
    provider = settings.embedding_provider

    if provider == "local":
        logger.info("embedding_query", provider="local")
        return _embed_query_local(query)
    elif provider == "gemini":
        logger.info("embedding_query", provider="gemini")
        return await _embed_query_gemini(query)
    else:
        logger.info("embedding_query", provider="voyage")
        return await _embed_query_voyage(query)


async def embed_queries(queries: Sequence[str]) -> list[list[float]]:
    """Embed multiple queries."""
    if not queries:
        return []

    settings = get_settings()
    provider = settings.embedding_provider

    if provider == "local":
        logger.info("embedding_queries", provider="local", count=len(queries))
        return _embed_local(list(queries))
    elif provider == "gemini":
        logger.info("embedding_queries", provider="gemini", count=len(queries))
        return await _embed_gemini(queries, task_type="RETRIEVAL_QUERY")
    else:
        logger.info("embedding_queries", provider="voyage", count=len(queries))
        return await _embed_voyage(queries, input_type="query")


def get_embedding_dims() -> int:
    """Return the embedding dimensions for the current model."""
    settings = get_settings()
    return settings.embedding_dims
