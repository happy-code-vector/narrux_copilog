"""Voyage AI rerank-2 wrapper.

NO pydantic_ai imports. Pure Python.
"""

from dataclasses import dataclass

import structlog
import voyageai

from config import get_settings
from tools.schemas import Citation

logger = structlog.get_logger(__name__)


@dataclass
class RankedChunk:
    """A chunk with its reranker score and rank."""

    chunk: "KBChunk"  # forward reference
    score: float
    rank: int


async def rerank(
    query: str,
    chunks: list,
    top_n: int | None = None,
) -> list[RankedChunk]:
    """Rerank chunks by relevance to query using Voyage rerank-2.

    Filters by min_rerank_score from settings.
    If nothing passes the threshold, returns empty list (citations-or-silence gate).

    Args:
        query: Query string.
        chunks: KBChunk objects from similarity search.
        top_n: Number of top results to return. Defaults to settings.rerank_top_n.

    Returns:
        List of RankedChunk objects, filtered by min_rerank_score.
    """
    if not chunks:
        return []

    settings = get_settings()
    if top_n is None:
        top_n = settings.rerank_top_n

    client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    documents = [c.content for c in chunks]

    logger.info(
        "reranking",
        query=query[:100],
        input_count=len(chunks),
        top_n=top_n,
        model=settings.voyage_rerank_model,
    )

    result = await client.rerank(
        query=query,
        documents=documents,
        model=settings.voyage_rerank_model,
        top_k=top_n,
    )

    ranked: list[RankedChunk] = []
    dropped = 0
    for i, item in enumerate(result.results):
        if item.relevance_score < settings.min_rerank_score:
            dropped += 1
            continue
        ranked.append(
            RankedChunk(
                chunk=chunks[item.index],
                score=item.relevance_score,
                rank=i + 1,
            )
        )

    if dropped > 0:
        logger.info(
            "rerank_dropped_by_threshold",
            dropped=dropped,
            min_score=settings.min_rerank_score,
        )

    if not ranked:
        logger.warning("rerank_nothing_passed_threshold — agent must abstain")

    logger.info("reranking_complete", output_count=len(ranked))
    return ranked


def ranked_chunks_to_citations(ranked: list[RankedChunk]) -> list[Citation]:
    """Convert ranked chunks to Citation objects.

    Builds citation_handle from chunk metadata:
    - If module_id → "Alpha Handbook §D1 — CVD Filter"
    - If pine_line → "file.pine:L437"
    - If section → "doc §3.2"
    - Else fallback to doc_id
    """
    citations: list[Citation] = []
    for rc in ranked:
        meta = rc.chunk.metadata
        handle = _build_citation_handle(meta, rc.chunk.doc_id)

        citations.append(
            Citation(
                doc_id=rc.chunk.doc_id,
                doc_version=rc.chunk.doc_version,
                chunk_id=rc.chunk.chunk_id,
                source_type=meta.get("source_type", "handbook"),
                citation_handle=handle,
                relevance_score=rc.score,
                excerpt=rc.chunk.content[:300],
            )
        )
    return citations


def _build_citation_handle(metadata: dict, doc_id: str) -> str:
    """Build a human-readable citation handle from chunk metadata."""
    module_id = metadata.get("module_id")
    module_name = metadata.get("module_name")
    if module_id and module_name:
        return f"§{module_id} — {module_name}"

    pine_line = metadata.get("pine_line")
    if pine_line:
        return f"{metadata.get('source_file', 'unknown')}:{pine_line}"

    section = metadata.get("section")
    if section:
        return f"{doc_id} §{section}"

    return doc_id
