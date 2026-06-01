"""pgvector-powered vector store — similarity search over KB chunks.

Uses asyncpg directly (no ORM).
"""

import structlog
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from retrieval.embeddings import EmbeddingClient

logger = structlog.get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result from the vector store."""

    id: UUID
    content: str
    citation_handle: str
    source_file: str
    doc_id: str
    doc_type: str
    section: str | None
    line_number: int | None
    similarity: float
    metadata: dict


SEARCH_SQL = """
SELECT
    id,
    content,
    citation_handle,
    source_file,
    doc_id,
    doc_type,
    section,
    line_number,
    1 - (embedding <=> $1::vector) as similarity,
    metadata
FROM knowledge_base_chunks
WHERE is_active = true
{extra_where}
ORDER BY embedding <=> $1::vector
LIMIT $2
"""


class VectorStore:
    """pgvector-powered vector store for knowledge base chunks.

    Usage:
        store = VectorStore(conn, embedding_client)
        results = await store.search("What does F19 do?", top_k=10)
    """

    def __init__(self, conn: asyncpg.Connection, embedding_client: EmbeddingClient):
        self._conn = conn
        self._embeddings = embedding_client

    async def search(
        self,
        query: str,
        top_k: int = 50,
        filter_doc_type: str | None = None,
        filter_doc_id: str | None = None,
    ) -> list[SearchResult]:
        """Search for similar chunks using cosine similarity."""
        logger.info(
            "searching_vector_store",
            query=query[:100],
            top_k=top_k,
            filter_doc_type=filter_doc_type,
        )

        # Generate query embedding
        query_embedding = await self._embeddings.embed_query(query)

        # Build query
        extra_where = ""
        params: list = [str(query_embedding), top_k]

        if filter_doc_type:
            extra_where = "AND doc_type = $3"
            params.append(filter_doc_type)

        sql = SEARCH_SQL.format(extra_where=extra_where)

        # Execute
        rows = await self._conn.fetch(sql, *params)

        # Convert to SearchResult
        results = [
            SearchResult(
                id=row["id"],
                content=row["content"],
                citation_handle=row["citation_handle"],
                source_file=row["source_file"],
                doc_id=row["doc_id"],
                doc_type=row["doc_type"],
                section=row["section"],
                line_number=row["line_number"],
                similarity=row["similarity"],
                metadata=row["metadata"] or {},
            )
            for row in rows
        ]

        logger.info(
            "search_complete",
            results=len(results),
            top_similarity=f"{results[0].similarity:.4f}" if results else "N/A",
        )

        return results

    async def get_by_id(self, chunk_id: UUID) -> SearchResult | None:
        """Retrieve a specific chunk by ID."""
        row = await self._conn.fetchrow(
            "SELECT * FROM knowledge_base_chunks WHERE id = $1",
            chunk_id,
        )

        if not row:
            return None

        return SearchResult(
            id=row["id"],
            content=row["content"],
            citation_handle=row["citation_handle"],
            source_file=row["source_file"],
            doc_id=row["doc_id"],
            doc_type=row["doc_type"],
            section=row["section"],
            line_number=row["line_number"],
            similarity=1.0,
            metadata=row["metadata"] or {},
        )

    async def count(self, only_active: bool = True) -> int:
        """Count total chunks in the vector store."""
        if only_active:
            row = await self._conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM knowledge_base_chunks WHERE is_active = true"
            )
        else:
            row = await self._conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM knowledge_base_chunks"
            )
        return row["cnt"] if row else 0
