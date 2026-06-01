"""Voyage AI reranker — reranks retrieved chunks for better citation accuracy.

NO framework imports. Pure Python.
"""

import structlog
import voyageai

from config.settings import get_settings
from retrieval.vector_store import SearchResult

logger = structlog.get_logger(__name__)

settings = get_settings()


class Reranker:
    """Voyage AI reranker client.

    Takes top-K results from vector search and reranks to top-N
    using a cross-encoder model for better relevance.

    Usage:
        reranker = Reranker()
        reranked = await reranker.rerank(query, results, top_n=10)
    """

    def __init__(self):
        self._client = voyageai.Client(api_key=settings.voyage_api_key)
        self._model = settings.voyage_reranker_model

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int = 10,
    ) -> list[SearchResult]:
        """Rerank search results by relevance to query.

        Args:
            query: Original query string.
            results: Search results from vector store.
            top_n: Number of top results to return after reranking.

        Returns:
            Reranked results (may be fewer than input if top_n < len(results)).
        """
        if not results:
            return []

        if len(results) <= top_n:
            # No need to rerank if we have fewer results than requested
            return results

        logger.info(
            "reranking_results",
            input_count=len(results),
            top_n=top_n,
            model=self._model,
        )

        try:
            # Prepare documents for reranking
            documents = [r.content for r in results]

            # Call Voyage reranker
            rerank_result = self._client.rerank(
                query=query,
                documents=documents,
                model=self._model,
                top_k=top_n,
            )

            # Map reranked results back to SearchResult objects
            reranked = []
            for item in rerank_result.results:
                original = results[item.index]
                # Update similarity with reranker score
                reranked.append(
                    SearchResult(
                        id=original.id,
                        content=original.content,
                        citation_handle=original.citation_handle,
                        source_file=original.source_file,
                        doc_id=original.doc_id,
                        doc_type=original.doc_type,
                        section=original.section,
                        line_number=original.line_number,
                        similarity=item.relevance_score,
                        metadata=original.metadata,
                    )
                )

            logger.info(
                "reranking_complete",
                output_count=len(reranked),
                top_score=f"{reranked[0].similarity:.4f}" if reranked else "N/A",
            )

            return reranked

        except Exception as e:
            logger.error("reranking_error", error=str(e))
            # Fallback: return top-N from original results
            logger.info("reranking_fallback", returning=top_n)
            return results[:top_n]
