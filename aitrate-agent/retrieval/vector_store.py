"""Qdrant vector store operations — supports server (Docker) and embedded modes.

NO pydantic_ai imports. Pure Python + qdrant-client.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from config import get_settings
from tools.schemas import KBChunk, KBDocument

logger = structlog.get_logger(__name__)

# Global client — initialized at startup
_client: QdrantClient | None = None


def init_client() -> None:
    """Initialize Qdrant client. Call at startup.

    Mode is determined by settings.qdrant_mode:
    - 'server': connects to Qdrant server (Docker) at settings.qdrant_url
    - 'embedded': uses local storage at settings.qdrant_path
    """
    global _client
    settings = get_settings()

    if settings.qdrant_mode == "server":
        _client = QdrantClient(url=settings.qdrant_url)
        logger.info("qdrant_initialized", mode="server", url=settings.qdrant_url)
    else:
        _client = QdrantClient(path=settings.qdrant_path)
        logger.info("qdrant_initialized", mode="embedded", path=settings.qdrant_path)

    _ensure_collection()


def close_client() -> None:
    """Close Qdrant client. Call at shutdown."""
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("qdrant_closed")


def _get_client() -> QdrantClient:
    """Get the Qdrant client. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("Qdrant not initialized — call init_client() first")
    return _client


def _ensure_collection() -> None:
    """Create the KB collection if it doesn't exist."""
    client = _get_client()
    settings = get_settings()
    collection = settings.qdrant_collection

    collections = [c.name for c in client.get_collections().collections]
    if collection not in collections:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=settings.embedding_dims,
                distance=Distance.COSINE,
            ),
        )
        logger.info("collection_created", collection=collection)
    else:
        logger.info("collection_exists", collection=collection)


def _chunk_to_point(chunk: KBChunk) -> PointStruct:
    """Convert a KBChunk to a Qdrant PointStruct."""
    # Use deterministic UUID from chunk_id
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id))

    payload: dict[str, Any] = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_version": chunk.doc_version,
        "content": chunk.content,
        "token_count": chunk.token_count,
    }
    # Merge all metadata into payload
    if chunk.metadata:
        payload.update(chunk.metadata)

    return PointStruct(
        id=point_id,
        vector=chunk.embedding,
        payload=payload,
    )


def _point_to_chunk(point: Any, similarity: float = 0.0) -> KBChunk:
    """Convert a Qdrant point to a KBChunk."""
    payload = point.payload or {}
    metadata = {
        k: v for k, v in payload.items()
        if k not in ("chunk_id", "doc_id", "doc_version", "content", "token_count")
    }
    metadata["_similarity"] = similarity

    return KBChunk(
        chunk_id=payload.get("chunk_id", point.id),
        doc_id=payload.get("doc_id", ""),
        doc_version=payload.get("doc_version", ""),
        content=payload.get("content", ""),
        token_count=payload.get("token_count"),
        embedding=None,  # Don't return embedding in search results
        metadata=metadata,
    )


async def upsert_document(doc: KBDocument) -> None:
    """Store document metadata.

    In Qdrant, document metadata is stored in chunk payloads.
    This is a no-op — metadata is set when chunks are upserted.
    """
    logger.info("document_registered", doc_id=doc.doc_id)


async def mark_document_deprecated(doc_id: str) -> None:
    """Mark all chunks for a document as deprecated."""
    client = _get_client()
    settings = get_settings()

    # Find all chunks for this document
    results, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
        ),
        limit=10000,
        with_payload=False,
        with_vectors=False,
    )

    if not results:
        logger.warning("no_chunks_to_deprecate", doc_id=doc_id)
        return

    # Update each chunk's payload to set deprecated=True
    point_ids = [point.id for point in results]
    client.set_payload(
        collection_name=settings.qdrant_collection,
        payload={"deprecated": True},
        points=PointIdsList(points=point_ids),
    )
    logger.info("document_deprecated", doc_id=doc_id, chunks=len(point_ids))


async def upsert_chunks(chunks: list[KBChunk]) -> int:
    """Upsert chunks into Qdrant. Skip chunks with no embedding. Return count."""
    client = _get_client()
    settings = get_settings()

    points = []
    for chunk in chunks:
        if chunk.embedding is None:
            continue
        points.append(_chunk_to_point(chunk))

    if not points:
        return 0

    # Batch upsert (Qdrant handles batching internally)
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )

    logger.info("chunks_upserted", count=len(points))
    return len(points)


async def delete_chunks_for_document(doc_id: str) -> int:
    """Delete all chunks for a document. Return count."""
    client = _get_client()
    settings = get_settings()

    # Find all chunks for this document
    results, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
        ),
        limit=10000,
        with_payload=False,
        with_vectors=False,
    )

    if not results:
        return 0

    point_ids = [point.id for point in results]
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=PointIdsList(points=point_ids),
    )

    logger.info("chunks_deleted", doc_id=doc_id, count=len(point_ids))
    return len(point_ids)


async def similarity_search(
    query_embedding: list[float],
    top_k: int = 20,
    metadata_filter: dict | None = None,
    exclude_deprecated: bool = True,
) -> list[KBChunk]:
    """Search for similar chunks using cosine similarity.

    Args:
        query_embedding: Query embedding vector.
        top_k: Number of results to return.
        metadata_filter: Optional key-value filter on payload fields.
        exclude_deprecated: Exclude chunks marked as deprecated.

    Returns:
        List of KBChunk with similarity in metadata["_similarity"].
    """
    client = _get_client()
    settings = get_settings()

    # Build Qdrant filter
    conditions = []

    if exclude_deprecated:
        # Exclude deprecated documents — match deprecated != True
        conditions.append(
            FieldCondition(
                key="deprecated",
                match=MatchValue(value=True),
            )
        )

    if metadata_filter:
        for key, value in metadata_filter.items():
            conditions.append(
                FieldCondition(key=key, match=MatchValue(value=value))
            )

    # Build filter: deprecated chunks are excluded with must_not
    search_filter = None
    if exclude_deprecated and metadata_filter:
        search_filter = Filter(
            must_not=[
                FieldCondition(key="deprecated", match=MatchValue(value=True))
            ],
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in metadata_filter.items()
            ],
        )
    elif exclude_deprecated:
        search_filter = Filter(
            must_not=[
                FieldCondition(key="deprecated", match=MatchValue(value=True))
            ]
        )
    elif metadata_filter:
        search_filter = Filter(
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in metadata_filter.items()
            ]
        )

    # Execute search
    results = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_embedding,
        limit=top_k,
        query_filter=search_filter,
        with_payload=True,
        with_vectors=False,
    )

    chunks = []
    for result in results.points:
        chunk = _point_to_chunk(result, similarity=result.score)
        chunks.append(chunk)

    logger.info("similarity_search", results=len(chunks), top_k=top_k)
    return chunks


async def get_chunk_by_id(chunk_id: str) -> KBChunk | None:
    """Retrieve a single chunk by its chunk_id."""
    client = _get_client()
    settings = get_settings()

    # Search by chunk_id in payload
    results, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="chunk_id", match=MatchValue(value=chunk_id))]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )

    if not results:
        return None

    return _point_to_chunk(results[0])


async def get_stats() -> dict[str, int]:
    """Return knowledge base statistics."""
    client = _get_client()
    settings = get_settings()

    # Total chunks
    total = client.count(collection_name=settings.qdrant_collection).count

    # Active documents (unique doc_ids where deprecated != True)
    # Qdrant doesn't have DISTINCT, so we scroll and count unique doc_ids
    active_docs: set[str] = set()
    deprecated_docs: set[str] = set()

    offset = None
    while True:
        results, next_offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=1000,
            offset=offset,
            with_payload=["doc_id", "deprecated"],
            with_vectors=False,
        )
        for point in results:
            payload = point.payload or {}
            doc_id = payload.get("doc_id", "")
            if payload.get("deprecated", False):
                deprecated_docs.add(doc_id)
            else:
                active_docs.add(doc_id)
        if next_offset is None:
            break
        offset = next_offset

    return {
        "active_documents": len(active_docs),
        "total_chunks": total,
        "deprecated_documents": len(deprecated_docs),
    }
