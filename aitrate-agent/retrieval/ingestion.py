"""Document ingestion pipeline — parse, chunk, embed, and store documents in pgvector.

Uses asyncpg directly (no ORM).
"""

import structlog
from pathlib import Path
from uuid import uuid4

import asyncpg

from retrieval.embeddings import EmbeddingClient
from config.settings import get_settings

logger = structlog.get_logger(__name__)

settings = get_settings()

SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".pine", ".yaml", ".yml", ".json", ".md", ".txt"}

INSERT_CHUNK_SQL = """
INSERT INTO knowledge_base_chunks (
    id, doc_id, doc_version, doc_type, source_file, section, page_number,
    line_number, content, chunk_index, embedding, owner, is_active,
    supersedes_id, citation_handle, metadata
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
"""


def _read_file(file_path: Path) -> str:
    """Read file content based on extension."""
    ext = file_path.suffix.lower()

    if ext in (".md", ".txt", ".pine", ".yaml", ".yml", ".json"):
        return file_path.read_text(encoding="utf-8")
    elif ext == ".docx":
        from docx import Document
        doc = Document(str(file_path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif ext == ".pdf":
        import PyPDF2
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            return "\n\n".join(
                page.extract_text() for page in reader.pages if page.extract_text()
            )
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            last_break = text.rfind("\n\n", start + chunk_size // 2, end)
            if last_break > start:
                end = last_break + 2

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - chunk_overlap

    return chunks


def _detect_doc_type(file_path: Path, content: str) -> str:
    """Detect document type from filename and content."""
    name = file_path.stem.lower()

    if "master" in name or "alpha" in name or "strategy" in name:
        return "strategy_spec"
    elif "tsi" in name:
        return "tsi_spec"
    elif "age" in name or "ape" in name or "pme" in name or "governance" in name:
        return "governance_doc"
    elif "param" in name and "class" in name:
        return "parameter_class"
    elif "filter" in name or "glossary" in name:
        return "filter_glossary"
    elif file_path.suffix == ".pine":
        return "pine_source"
    else:
        return "other"


async def ingest_document(
    file_path: Path,
    conn: asyncpg.Connection,
    embedding_client: EmbeddingClient,
    owner: str,
    doc_version: str = "1.0",
    supersedes_id: str | None = None,
) -> int:
    """Ingest a single document into the knowledge base."""
    logger.info("ingesting_document", file_path=str(file_path), owner=owner, version=doc_version)

    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")

    content = _read_file(file_path)
    chunks = _chunk_text(
        content,
        chunk_size=settings.retrieval_chunk_size,
        chunk_overlap=settings.retrieval_chunk_overlap,
    )

    logger.info("document_chunked", total_chunks=len(chunks))

    doc_type = _detect_doc_type(file_path, content)
    doc_id = f"{file_path.stem}_{doc_version}"

    embeddings = await embedding_client.embed(chunks)

    created_count = 0
    for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        await conn.execute(
            INSERT_CHUNK_SQL,
            uuid4(),                    # id
            doc_id,                     # doc_id
            doc_version,                # doc_version
            doc_type,                   # doc_type
            str(file_path),             # source_file
            None,                       # section
            None,                       # page_number
            None,                       # line_number
            chunk_text,                 # content
            i,                          # chunk_index
            str(embedding),             # embedding (pgvector format)
            owner,                      # owner
            True,                       # is_active
            supersedes_id,              # supersedes_id
            f"{file_path.stem} v{doc_version}, chunk {i}",  # citation_handle
            None,                       # metadata
        )
        created_count += 1

    logger.info("document_ingested", doc_id=doc_id, chunks_created=created_count, doc_type=doc_type)

    return created_count


async def ingest_directory(
    directory: Path,
    conn: asyncpg.Connection,
    embedding_client: EmbeddingClient,
    owner: str,
    doc_version: str = "1.0",
    recursive: bool = True,
) -> dict[str, int]:
    """Ingest all supported documents in a directory."""
    logger.info("ingesting_directory", directory=str(directory), recursive=recursive)

    pattern = "**/*" if recursive else "*"
    results: dict[str, int] = {}

    for file_path in directory.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                count = await ingest_document(
                    file_path=file_path,
                    conn=conn,
                    embedding_client=embedding_client,
                    owner=owner,
                    doc_version=doc_version,
                )
                results[str(file_path)] = count
            except Exception as e:
                logger.error("ingestion_error", file=str(file_path), error=str(e))
                results[str(file_path)] = 0

    logger.info(
        "directory_ingestion_complete",
        files_processed=len(results),
        total_chunks=sum(results.values()),
    )

    return results
