"""KB ingestion script — ingest documents into the vector store.

Usage:
    python scripts/ingest_kb.py --dir /path/to/docs --owner "Frank Zielkowski"
    python scripts/ingest_kb.py --file /path/to/doc.pdf --owner "Frank Zielkowski" --version "v14"
"""

import asyncio
import argparse
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.session import async_session_factory
from retrieval.embeddings import EmbeddingClient
from retrieval.ingestion import ingest_document, ingest_directory


async def main():
    parser = argparse.ArgumentParser(description="Ingest documents into the aiTrate knowledge base")
    parser.add_argument("--dir", type=str, help="Directory to ingest (all supported files)")
    parser.add_argument("--file", type=str, help="Single file to ingest")
    parser.add_argument("--owner", type=str, required=True, help="Document owner")
    parser.add_argument("--version", type=str, default="1.0", help="Document version")
    parser.add_argument("--recursive", action="store_true", default=True, help="Scan subdirectories")

    args = parser.parse_args()

    if not args.dir and not args.file:
        parser.error("Either --dir or --file must be specified")

    settings = get_settings()
    embedding_client = EmbeddingClient()

    async with async_session_factory() as session:
        if args.dir:
            directory = Path(args.dir)
            if not directory.exists():
                print(f"Error: Directory not found: {args.dir}")
                return

            print(f"Ingesting directory: {directory}")
            results = await ingest_directory(
                directory=directory,
                session=session,
                embedding_client=embedding_client,
                owner=args.owner,
                doc_version=args.version,
                recursive=args.recursive,
            )

            print(f"\nIngestion complete:")
            for file_path, count in results.items():
                print(f"  {file_path}: {count} chunks")
            print(f"\nTotal: {sum(results.values())} chunks from {len(results)} files")

        elif args.file:
            file_path = Path(args.file)
            if not file_path.exists():
                print(f"Error: File not found: {args.file}")
                return

            print(f"Ingesting file: {file_path}")
            count = await ingest_document(
                file_path=file_path,
                session=session,
                embedding_client=embedding_client,
                owner=args.owner,
                doc_version=args.version,
            )

            print(f"\nIngestion complete: {count} chunks created")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
