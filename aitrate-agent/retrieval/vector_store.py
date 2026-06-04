"""pgvector async operations using psycopg (v3) with AsyncConnectionPool.

NO pydantic_ai imports. Pure Python.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from config import get_settings
from tools.schemas import KBChunk, KBDocument

logger = structlog.get_logger(__name__)

# Global pool — initialized at startup, closed at shutdown
_pool: AsyncConnectionPool | None = None


async def init_pool() -> None:
    """Initialize the psycopg AsyncConnectionPool. Call at startup."""
    global _pool
    settings = get_settings()
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row},
    )
    await _pool.open()
    logger.info("db_pool_initialized")


async def close_pool() -> None:
    """Close the pool. Call at shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("db_pool_closed")


@asynccontextmanager
async def get_conn() -> AsyncGenerator[AsyncConnection, None]:
    """Yield an AsyncConnection from the pool."""
    if _pool is None:
        raise RuntimeError("Pool not initialized — call init_pool() first")
    async with _pool.connection() as conn:
        yield conn


async def upsert_document(doc: KBDocument) -> None:
    """Insert or update a document in kb_documents."""
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO kb_documents (doc_id, doc_version, title, scope, strategy,
                volume, module_id, owner, last_updated, supersedes, deprecated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (doc_id) DO UPDATE SET
                doc_version = EXCLUDED.doc_version,
                title = EXCLUDED.title,
                scope = EXCLUDED.scope,
                strategy = EXCLUDED.strategy,
                volume = EXCLUDED.volume,
                module_id = EXCLUDED.module_id,
                owner = EXCLUDED.owner,
                last_updated = EXCLUDED.last_updated,
                supersedes = EXCLUDED.supersedes,
                deprecated = EXCLUDED.deprecated
            """,
            (
                doc.doc_id, doc.doc_version, doc.title, doc.scope.value,
                doc.strategy, doc.volume, doc.module_id, doc.owner,
                doc.last_updated, doc.supersedes, doc.deprecated,
            ),
        )
        await conn.commit()
    logger.info("document_upserted", doc_id=doc.doc_id)


async def mark_document_deprecated(doc_id: str) -> None:
    """Mark a document as deprecated."""
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE kb_documents SET deprecated = TRUE WHERE doc_id = %s",
            (doc_id,),
        )
        await conn.commit()
    logger.info("document_deprecated", doc_id=doc_id)


async def upsert_chunks(chunks: list[KBChunk]) -> int:
    """Insert or update chunks. Skip chunks with no embedding. Return count."""
    count = 0
    async with get_conn() as conn:
        for chunk in chunks:
            if chunk.embedding is None:
                continue
            embedding_str = "[" + ",".join(str(f) for f in chunk.embedding) + "]"
            await conn.execute(
                """
                INSERT INTO kb_chunks (chunk_id, doc_id, doc_version, content,
                    token_count, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    doc_id = EXCLUDED.doc_id,
                    doc_version = EXCLUDED.doc_version,
                    content = EXCLUDED.content,
                    token_count = EXCLUDED.token_count,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata
                """,
                (
                    chunk.chunk_id, chunk.doc_id, chunk.doc_version,
                    chunk.content, chunk.token_count, embedding_str,
                    json.dumps(chunk.metadata),
                ),
            )
            count += 1
        await conn.commit()
    logger.info("chunks_upserted", count=count)
    return count


async def delete_chunks_for_document(doc_id: str) -> int:
    """Delete all chunks for a document. Return rowcount."""
    async with get_conn() as conn:
        result = await conn.execute(
            "DELETE FROM kb_chunks WHERE doc_id = %s", (doc_id,)
        )
        await conn.commit()
        rowcount = result.rowcount
    logger.info("chunks_deleted", doc_id=doc_id, count=rowcount)
    return rowcount


async def similarity_search(
    query_embedding: list[float],
    top_k: int = 20,
    metadata_filter: dict | None = None,
    exclude_deprecated: bool = True,
) -> list[KBChunk]:
    """Search for similar chunks using cosine distance.

    Args:
        query_embedding: Query embedding vector.
        top_k: Number of results to return.
        metadata_filter: Optional JSONB filter (key-value pairs).
        exclude_deprecated: Exclude deprecated documents.

    Returns:
        List of KBChunk with similarity in metadata["_similarity"].
    """
    embedding_str = "[" + ",".join(str(f) for f in query_embedding) + "]"

    where_clauses: list[str] = []
    params: list = [embedding_str]

    if exclude_deprecated:
        where_clauses.append(
            "NOT EXISTS (SELECT 1 FROM kb_documents d WHERE d.doc_id = c.doc_id AND d.deprecated = TRUE)"
        )

    if metadata_filter:
        for key, value in metadata_filter.items():
            params.append(key)
            params.append(value)
            where_clauses.append(f"c.metadata ->> %s = %s")

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
    params.append(top_k)

    sql = f"""
        SELECT c.chunk_id, c.doc_id, c.doc_version, c.content,
               c.token_count, c.embedding, c.metadata,
               1 - (c.embedding <=> %s::vector) AS similarity
        FROM kb_chunks c
        WHERE {where_sql}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    # Fix params order: embedding for distance, then where params, then embedding for order, then limit
    # Rebuild with correct param order
    distance_params = [embedding_str]
    where_params: list = []

    if exclude_deprecated:
        pass  # no params needed

    if metadata_filter:
        for key, value in metadata_filter.items():
            where_params.append(key)
            where_params.append(value)

    all_params = distance_params + where_params + distance_params + [top_k]

    sql = f"""
        SELECT c.chunk_id, c.doc_id, c.doc_version, c.content,
               c.token_count, c.metadata,
               1 - (c.embedding <=> %s::vector) AS similarity
        FROM kb_chunks c
        {("WHERE " + where_sql) if where_clauses else ""}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """

    # Simpler approach: build the full SQL with proper param ordering
    query_params: list = [embedding_str]

    where_parts: list[str] = []
    if exclude_deprecated:
        where_parts.append(
            "NOT EXISTS (SELECT 1 FROM kb_documents d WHERE d.doc_id = c.doc_id AND d.deprecated = TRUE)"
        )
    if metadata_filter:
        for key, value in metadata_filter.items():
            where_parts.append(f"c.metadata ->> %s = %s")
            query_params.extend([key, value])

    where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""

    final_sql = f"""
        SELECT c.chunk_id, c.doc_id, c.doc_version, c.content,
               c.token_count, c.metadata,
               1 - (c.embedding <=> %s::vector) AS similarity
        FROM kb_chunks c
        {where_clause}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    query_params.extend([embedding_str, top_k])

    async with get_conn() as conn:
        rows = await conn.execute(final_sql, query_params)
        results = []
        for row in rows:
            chunk = KBChunk(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                doc_version=row["doc_version"],
                content=row["content"],
                token_count=row["token_count"],
                metadata={**(row["metadata"] or {}), "_similarity": row["similarity"]},
            )
            results.append(chunk)

    logger.info("similarity_search", results=len(results), top_k=top_k)
    return results


async def get_chunk_by_id(chunk_id: str) -> KBChunk | None:
    """Retrieve a single chunk by ID."""
    async with get_conn() as conn:
        rows = await conn.execute(
            "SELECT chunk_id, doc_id, doc_version, content, token_count, metadata FROM kb_chunks WHERE chunk_id = %s",
            (chunk_id,),
        )
        row = rows.fetchone() if hasattr(rows, "fetchone") else None
        # psycopg v3 returns cursor-like results
        async with get_conn() as conn2:
            cur = await conn2.execute(
                "SELECT chunk_id, doc_id, doc_version, content, token_count, metadata FROM kb_chunks WHERE chunk_id = %s",
                (chunk_id,),
            )
            row = await cur.fetchone()

    if not row:
        return None

    return KBChunk(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        doc_version=row["doc_version"],
        content=row["content"],
        token_count=row["token_count"],
        metadata=row["metadata"] or {},
    )


async def get_stats() -> dict[str, int]:
    """Return knowledge base statistics."""
    async with get_conn() as conn:
        cur = await conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM kb_documents WHERE NOT deprecated) AS active_documents,
                (SELECT COUNT(*) FROM kb_chunks) AS total_chunks,
                (SELECT COUNT(*) FROM kb_documents WHERE deprecated) AS deprecated_documents
            """
        )
        row = await cur.fetchone()

    return {
        "active_documents": row["active_documents"],
        "total_chunks": row["total_chunks"],
        "deprecated_documents": row["deprecated_documents"],
    }
