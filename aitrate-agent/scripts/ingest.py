"""KB ingestion CLI script.

Usage:
    python scripts/ingest.py --all --project-docs /path/to/project/docs
    python scripts/ingest.py --doc-id alpha_handbook_v15_9_1_vol_ab
    python scripts/ingest.py --stats
    python scripts/ingest.py --test-query "what does the CVD filter do"
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from retrieval.embeddings import embed_query
from retrieval.ingestion import _build_source_registry, ingest_all_project_documents, ingest_document
from retrieval.reranker import RankedChunk, ranked_chunks_to_citations, rerank
from retrieval.vector_store import (
    close_pool,
    get_stats,
    init_pool,
    similarity_search,
)


async def main():
    parser = argparse.ArgumentParser(
        description="NARRUX aiTrate Co-Pilot — KB Ingestion CLI"
    )
    parser.add_argument("--all", action="store_true", help="Ingest all project documents")
    parser.add_argument("--doc-id", type=str, help="Ingest one document by doc_id")
    parser.add_argument("--stats", action="store_true", help="Print KB statistics")
    parser.add_argument("--test-query", type=str, help="Run a test query against the KB")
    parser.add_argument(
        "--project-docs",
        type=str,
        default="/mnt/project",
        help="Path to project documents directory",
    )

    args = parser.parse_args()

    if not any([args.all, args.doc_id, args.stats, args.test_query]):
        parser.error("Specify one of: --all, --doc-id, --stats, --test-query")

    await init_pool()

    try:
        if args.all:
            await cmd_ingest_all(args.project_docs)
        elif args.doc_id:
            await cmd_ingest_one(args.doc_id, args.project_docs)
        elif args.stats:
            await cmd_stats()
        elif args.test_query:
            await cmd_test_query(args.test_query)
    finally:
        await close_pool()


async def cmd_ingest_all(project_docs_path: str):
    """Ingest all project documents."""
    kb_dir = Path(__file__).parent.parent / "kb_content"
    project_docs = Path(project_docs_path)

    # Create symlink if it doesn't exist
    symlink_target = kb_dir.parent / "project_docs"
    if not symlink_target.exists() and project_docs.exists():
        try:
            symlink_target.symlink_to(project_docs, target_is_directory=True)
            print(f"Created symlink: {symlink_target} → {project_docs}")
        except OSError as e:
            print(f"Warning: Could not create symlink: {e}")

    print(f"Ingesting all project documents from {kb_dir}...")
    results = await ingest_all_project_documents(kb_dir)

    print("\nIngestion results:")
    for doc_id, count in results.items():
        status = f"{count} chunks" if count >= 0 else "ERROR"
        print(f"  {doc_id}: {status}")

    total = sum(c for c in results.values() if c >= 0)
    errors = sum(1 for c in results.values() if c < 0)
    print(f"\nTotal: {total} chunks from {len(results)} documents ({errors} errors)")


async def cmd_ingest_one(doc_id: str, project_docs_path: str):
    """Ingest a single document by doc_id."""
    kb_dir = Path(__file__).parent.parent / "kb_content"
    sources = _build_source_registry(kb_dir)

    source = None
    for s in sources:
        if s.doc_id == doc_id:
            source = s
            break

    if source is None:
        print(f"Error: doc_id '{doc_id}' not found. Available:")
        for s in sources:
            print(f"  {s.doc_id}")
        return

    print(f"Ingesting {doc_id} from {source.path}...")
    count = await ingest_document(source)
    print(f"Done: {count} chunks created")


async def cmd_stats():
    """Print KB statistics."""
    stats = await get_stats()
    print("Knowledge Base Statistics:")
    print(f"  Active documents: {stats['active_documents']}")
    print(f"  Total chunks:     {stats['total_chunks']}")
    print(f"  Deprecated docs:  {stats['deprecated_documents']}")


async def cmd_test_query(query: str):
    """Run a test query against the KB."""
    settings = get_settings()

    print(f"Query: {query}")
    print(f"Retrieving top-{settings.retrieval_top_k} chunks...")

    query_embedding = await embed_query(query)
    chunks = await similarity_search(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
    )

    if not chunks:
        print("No results found.")
        return

    print(f"\nRetrieved {len(chunks)} chunks. Reranking to top-{settings.rerank_top_n}...")

    ranked = await rerank(query, chunks, top_n=settings.rerank_top_n)

    if not ranked:
        print("No chunks passed rerank threshold.")
        return

    citations = ranked_chunks_to_citations(ranked)

    print(f"\nTop {len(ranked)} results:")
    print("=" * 80)
    for i, (rc, cit) in enumerate(zip(ranked, citations), 1):
        print(f"\n[{i}] Score: {rc.score:.4f} | Rank: {rc.rank}")
        print(f"    Handle: {cit.citation_handle}")
        print(f"    Doc: {cit.doc_id} v{cit.doc_version}")
        print(f"    Content: {rc.chunk.content[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())
