"""pgvector-powered vector store — similarity search over KB chunks.

NO framework imports. Pure Python + SQLAlchemy + pgvector.
"""

import structlog
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import KnowledgeBaseChunk
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


class VectorStore:
    """pgvector-powered vector store for knowledge base chunks.

    Usage:
        store = VectorStore(session, embedding_client)
        results = await store.search("What does F19 do?", top_k=10)
    """

    def __init__(self, session: AsyncSession, embedding_client: EmbeddingClient):
        self._session = session
        self._embeddings = embedding_client

    async def search(
        self,
        query: str,
        top_k: int = 50,
        filter_doc_type: str | None = None,
        filter_doc_id: str | None = None,
        only_active: bool = True,
    ) -> list[SearchResult]:
        """Search for similar chunks using cosine similarity.

        Args:
            query: Natural language query.
            top_k: Number of results to return.
            filter_doc_type: Optional filter by document type.
            filter_doc_id: Optional filter by document ID.
            only_active: Only return active (non-superseded) chunks.

        Returns:
            List of search results ordered by similarity (descending).
        """
        logger.info(
            "searching_vector_store",
            query=query[:100],
            top_k=top_k,
            filter_doc_type=filter_doc_type,
        )

        # Generate query embedding
        query_embedding = await self._embeddings.embed_query(query)

        # Build SQL query with pgvector cosine distance
        # Using <=> operator for cosine distance (1 - cosine_similarity)
        sql = """
            SELECT
                id,
                content,
                citation_handle,
                source_file,
                doc_id,
                doc_type,
                section,
                line_number,
                1 - (embedding <=> :query_embedding::vector) as similarity,
                metadata
            FROM knowledge_base_chunks
            WHERE 1=1
        """
        params: dict = {"query_embedding": str(query_embedding)}

        if only_active:
            sql += " AND is_active = true"

        if filter_doc_type:
            sql += " AND doc_type = :doc_type"
            params["doc_type"] = filter_doc_type

        if filter_doc_id:
            sql += " AND doc_id = :doc_id"
            params["doc_id"] = filter_doc_id

        sql += " ORDER BY embedding <=> :query_embedding::vector LIMIT :top_k"
        params["top_k"] = top_k

        # Execute
        result = await self._session.execute(text(sql), params)
        rows = result.fetchall()

        # Convert to SearchResult
        results = [
            SearchResult(
                id=row.id,
                content=row.content,
                citation_handle=row.citation_handle,
                source_file=row.source_file,
                doc_id=row.doc_id,
                doc_type=row.doc_type,
                section=row.section,
                line_number=row.line_number,
                similarity=row.similarity,
                metadata=row.metadata or {},
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
        """Retrieve a specific chunk by ID.

        Args:
            chunk_id: UUID of the chunk.

        Returns:
            SearchResult if found, None otherwise.
        """
        result = await self._session.execute(
            select(KnowledgeBaseChunk).where(KnowledgeBaseChunk.id == chunk_id)
        )
        chunk = result.scalar_one_or_none()

        if not chunk:
            return None

        return SearchResult(
            id=chunk.id,
            content=chunk.content,
            citation_handle=chunk.citation_handle,
            source_file=chunk.source_file,
            doc_id=chunk.doc_id,
            doc_type=chunk.doc_type,
            section=chunk.section,
            line_number=chunk.line_number,
            similarity=1.0,  # Exact match
            metadata=chunk.metadata_ or {},
        )

    async def count(self, only_active: bool = True) -> int:
        """Count total chunks in the vector store.

        Args:
            only_active: Only count active chunks.

        Returns:
            Total chunk count.
        """
        sql = "SELECT COUNT(*) FROM knowledge_base_chunks"
        if only_active:
            sql += " WHERE is_active = true"

        result = await self._session.execute(text(sql))
        return result.scalar() or 0
