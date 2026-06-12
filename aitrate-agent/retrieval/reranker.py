"""Reranker wrapper — supports Voyage AI and local cross-encoder.

Provider is selected by settings.reranker_provider:
- 'voyage': uses Voyage AI rerank-2 (API)
- 'local': uses sentence-transformers cross-encoder (offline)
- 'none': skip reranking, return top chunks by vector similarity

NO pydantic_ai imports. Pure Python.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from config import get_settings
from tools.schemas import Citation

logger = structlog.get_logger(__name__)


@dataclass
class RankedChunk:
    """A chunk with its reranker score and rank."""

    chunk: "KBChunk"  # forward reference
    score: float
    rank: int


# ─── Local Cross-Encoder ────────────────────────────────────────────────────

_local_reranker = None


def _get_local_reranker():
    """Lazy-load the local cross-encoder model."""
    global _local_reranker
    if _local_reranker is None:
        from sentence_transformers import CrossEncoder

        logger.info("loading_local_reranker")
        _local_reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("local_reranker_loaded")
    return _local_reranker


def _rerank_local(query: str, chunks: list, top_n: int) -> list[RankedChunk]:
    """Rerank using local cross-encoder model."""
    model = _get_local_reranker()
    settings = get_settings()

    # Build query-document pairs
    pairs = [[query, c.content] for c in chunks]
    scores = model.predict(pairs)

    # Sort by score descending
    scored = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)

    ranked = []
    for i, (chunk, score) in enumerate(scored[:top_n]):
        if float(score) < settings.min_rerank_score:
            continue
        ranked.append(RankedChunk(chunk=chunk, score=float(score), rank=i + 1))

    return ranked


# ─── Voyage AI Reranker ─────────────────────────────────────────────────────

async def _rerank_voyage(query: str, chunks: list, top_n: int) -> list[RankedChunk]:
    """Rerank using Voyage AI rerank-2."""
    import voyageai

    settings = get_settings()
    client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    documents = [c.content for c in chunks]

    result = await client.rerank(
        query=query,
        documents=documents,
        model=settings.voyage_rerank_model,
        top_k=top_n,
    )

    ranked = []
    for i, item in enumerate(result.results):
        if item.relevance_score < settings.min_rerank_score:
            continue
        ranked.append(
            RankedChunk(
                chunk=chunks[item.index],
                score=item.relevance_score,
                rank=i + 1,
            )
        )

    return ranked


# ─── Public API ─────────────────────────────────────────────────────────────

async def rerank(
    query: str,
    chunks: list,
    top_n: int | None = None,
) -> list[RankedChunk]:
    """Rerank chunks by relevance to query.

    Uses provider based on settings.reranker_provider:
    - 'voyage': Voyage AI rerank-2
    - 'local': sentence-transformers cross-encoder
    - 'none': skip reranking, return top chunks by vector similarity score

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

    provider = settings.reranker_provider

    logger.info(
        "reranking",
        query=query[:100],
        input_count=len(chunks),
        top_n=top_n,
        provider=provider,
    )

    if provider == "none":
        # Skip reranking — use vector similarity scores
        ranked = []
        for i, chunk in enumerate(chunks[:top_n]):
            score = chunk.metadata.get("_similarity", 0.0)
            if score < settings.min_rerank_score:
                continue
            ranked.append(RankedChunk(chunk=chunk, score=score, rank=i + 1))
    elif provider == "local":
        ranked = _rerank_local(query, chunks, top_n)
    else:
        ranked = await _rerank_voyage(query, chunks, top_n)

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
