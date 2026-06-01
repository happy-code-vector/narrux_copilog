"""Retrieval layer — embeddings, vector store, reranker, ingestion, citation.

All components are framework-agnostic (no Pydantic AI imports).
"""

from retrieval.embeddings import EmbeddingClient
from retrieval.vector_store import VectorStore, SearchResult
from retrieval.reranker import Reranker
from retrieval.citation import CitationEnforcer, Citation, CitedClaim
from retrieval.ingestion import ingest_document, ingest_directory

__all__ = [
    "EmbeddingClient",
    "VectorStore",
    "SearchResult",
    "Reranker",
    "CitationEnforcer",
    "Citation",
    "CitedClaim",
    "ingest_document",
    "ingest_directory",
]
