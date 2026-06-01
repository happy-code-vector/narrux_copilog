"""Voyage AI embedding client — generates embeddings for KB chunks and queries.

NO framework imports. Pure Python.
"""

import structlog
import voyageai

from config.settings import get_settings

logger = structlog.get_logger(__name__)

settings = get_settings()


class EmbeddingClient:
    """Voyage AI embedding client.

    Usage:
        client = EmbeddingClient()
        embeddings = await client.embed(["text1", "text2"])
    """

    def __init__(self):
        self._client = voyageai.Client(api_key=settings.voyage_api_key)
        self._model = settings.voyage_embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of floats).
        """
        if not texts:
            return []

        logger.info("generating_embeddings", count=len(texts), model=self._model)

        try:
            result = self._client.embed(
                texts,
                model=self._model,
                input_type="document",
            )
            logger.info("embeddings_generated", count=len(result.embeddings))
            return result.embeddings
        except Exception as e:
            logger.error("embedding_error", error=str(e))
            raise

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query string.

        Uses "query" input type for retrieval-optimized embeddings.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        logger.info("generating_query_embedding", model=self._model)

        try:
            result = self._client.embed(
                [query],
                model=self._model,
                input_type="query",
            )
            return result.embeddings[0]
        except Exception as e:
            logger.error("query_embedding_error", error=str(e))
            raise
