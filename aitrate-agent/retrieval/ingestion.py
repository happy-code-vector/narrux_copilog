"""KB document ingestion pipeline.

CRITICAL FACT: All project documents are ZIP archives with .pdf extensions.
Magic bytes: PK\\x03\\x04. They contain N.txt files (one per page) and N.jpeg files.
The pipeline must detect this with _is_zip_archive() checking file magic bytes,
NOT file extension.

NO pydantic_ai imports. Pure Python.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import tiktoken

from config import get_settings
from retrieval.embeddings import embed_documents
from retrieval.vector_store import (
    delete_chunks_for_document,
    upsert_chunks,
    upsert_document,
)
from tools.schemas import DocumentScope, KBChunk, KBDocument

logger = structlog.get_logger(__name__)

# ─── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class IngestionSource:
    """Definition of a document to ingest."""

    path: Path
    doc_id: str
    doc_version: str
    title: str
    scope: DocumentScope
    owner: str = "NARRUX"
    strategy: str | None = None
    volume: str | None = None
    module_id: str | None = None
    supersedes: str | None = None
    module_markers: dict[str, str] = field(default_factory=dict)


@dataclass
class RawChunk:
    """A raw chunk before embedding."""

    content: str
    metadata: dict


# ─── Text Extraction ─────────────────────────────────────────────────────────


def _is_zip_archive(path: Path) -> bool:
    """Check if a file is a ZIP archive by reading magic bytes.

    Checks for PK\\x03\\x04, NOT file extension.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        return magic == b"PK\x03\x04"
    except Exception:
        return False


def extract_text_from_zip(path: Path) -> list[tuple[int, str]]:
    """Extract text from a ZIP archive containing .txt files (one per page).

    Returns list of (page_number, text) sorted by page number.
    """
    pages: list[tuple[int, str]] = []
    with zipfile.ZipFile(path, "r") as zf:
        txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
        for txt_name in txt_files:
            # Parse page number from filename (e.g., "1.txt" → 1)
            try:
                page_num = int(txt_name.replace(".txt", "").split("/")[-1])
            except ValueError:
                page_num = 0

            raw = zf.read(txt_name)
            text = raw.decode("utf-8", errors="replace")
            text = _strip_page_header_footer(text)
            pages.append((page_num, text))

    pages.sort(key=lambda x: x[0])
    return pages


def _strip_page_header_footer(text: str) -> str:
    """Remove NARRUX header/footer patterns from page text."""
    patterns = [
        r"^Strictly Confidential.*$",
        r"^NARRUX.*(?:Strictly Confidential|Handbook|Specification).*$",
        r"^Confidential — internal use only.*$",
        r"^Page \d+ of \d+$",
    ]
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        skip = False
        for pattern in patterns:
            if re.match(pattern, line.strip(), re.IGNORECASE):
                skip = True
                break
        if not skip:
            cleaned.append(line)
    return "\n".join(cleaned)


def extract_text_from_md(path: Path) -> str:
    """Extract text from a markdown file."""
    return path.read_text(encoding="utf-8", errors="replace")


def extract_text_from_txt(path: Path) -> str:
    """Extract text from a plain text file."""
    return path.read_text(encoding="utf-8", errors="replace")


def extract_text_from_docx(path: Path) -> str:
    """Extract text from a .docx file."""
    from docx import Document

    doc = Document(str(path))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


# ─── Chunking ────────────────────────────────────────────────────────────────


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def make_chunk_id(doc_id: str, content: str, index: int) -> str:
    """Generate a deterministic chunk ID."""
    hash_input = f"{doc_id}::{index}::{content[:200]}"
    hash_hex = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    return f"{doc_id}::{hash_hex}"


def chunk_by_module_boundaries(
    pages: list[tuple[int, str]], source: IngestionSource
) -> list[RawChunk]:
    """Chunk by module boundaries (e.g., D1 · CVD Filter [C]).

    Falls back to chunk_sliding_window if no module headers found.
    """
    settings = get_settings()
    full_text = "\n\n".join(text for _, text in pages)

    # Module header pattern: A1 · Module Name [A]
    pattern = re.compile(
        r"^([A-L]\d{1,2})\s*[·•]\s*(.+?)(?:\s*\[([ABC])\])?$",
        re.MULTILINE,
    )

    matches = list(pattern.finditer(full_text))
    if not matches:
        logger.info("no_module_headers_found", doc_id=source.doc_id, fallback="sliding_window")
        return chunk_sliding_window(full_text, source)

    logger.info("module_headers_found", doc_id=source.doc_id, count=len(matches))

    chunks: list[RawChunk] = []

    for i, match in enumerate(matches):
        module_id = match.group(1)
        module_name = match.group(2).strip()
        param_class = match.group(3)

        # Extract section text (from this match to next match or end)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        section_text = full_text[start:end].strip()

        meta: dict = {
            "source_type": "handbook",
            "strategy": source.strategy,
            "volume": source.volume,
            "module_id": module_id,
            "module_name": module_name,
            "doc_id": source.doc_id,
            "doc_version": source.doc_version,
        }
        if param_class:
            meta["param_class"] = param_class
            meta["regime_coupled"] = param_class == "C"

        section_tokens = _count_tokens(section_text)

        if section_tokens > settings.chunk_size_tokens * 2:
            # Subdivide large sections with sliding window
            sub_chunks = chunk_sliding_window(section_text, source, extra_meta=meta)
            chunks.extend(sub_chunks)
        else:
            chunks.append(RawChunk(content=section_text, metadata=meta))

    logger.info("module_chunking_complete", doc_id=source.doc_id, chunks=len(chunks))
    return chunks


def chunk_sliding_window(
    text: str,
    source: IngestionSource,
    extra_meta: dict | None = None,
) -> list[RawChunk]:
    """Sliding window chunking with tiktoken."""
    settings = get_settings()
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)

    chunk_size = settings.chunk_size_tokens
    overlap = settings.chunk_overlap_tokens

    chunks: list[RawChunk] = []
    start = 0
    index = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = enc.decode(chunk_tokens)

        meta: dict = {"doc_id": source.doc_id, "doc_version": source.doc_version, "chunk_index": index}
        if extra_meta:
            meta.update(extra_meta)

        chunks.append(RawChunk(content=chunk_text, metadata=meta))

        start = end - overlap
        index += 1
        if end >= len(tokens):
            break

    return chunks


def chunk_pages_with_context(
    pages: list[tuple[int, str]], source: IngestionSource
) -> list[RawChunk]:
    """One chunk per page if fits in chunk_size. Subdivide if too long."""
    settings = get_settings()
    chunks: list[RawChunk] = []

    for page_num, text in pages:
        if not text.strip():
            continue

        token_count = _count_tokens(text)

        if token_count <= settings.chunk_size_tokens:
            meta = {
                "doc_id": source.doc_id,
                "doc_version": source.doc_version,
                "page_number": page_num,
            }
            chunks.append(RawChunk(content=text, metadata=meta))
        else:
            # Subdivide with sliding window
            sub_chunks = chunk_sliding_window(
                text, source, extra_meta={"page_number": page_num}
            )
            chunks.extend(sub_chunks)

    return chunks


# ─── Ingestion Pipeline ──────────────────────────────────────────────────────


async def ingest_document(source: IngestionSource, force_reingest: bool = False) -> int:
    """Ingest a single document into the knowledge base.

    Steps:
    1. Detect file type with _is_zip_archive() first.
    2. Choose chunking strategy.
    3. Register document via upsert_document.
    4. Delete old chunks (always, to handle version upgrades).
    5. Embed with embed_documents.
    6. Build KBChunk objects with make_chunk_id.
    7. Upsert chunks. Return count.
    """
    path = source.path
    if not path.exists():
        logger.warning("file_not_found", path=str(path))
        return 0

    logger.info("ingesting", doc_id=source.doc_id, path=str(path))

    # Step 1: Extract text
    if _is_zip_archive(path):
        pages = extract_text_from_zip(path)
        text = "\n\n".join(t for _, t in pages)
        use_pages = True
    else:
        suffix = path.suffix.lower()
        if suffix == ".md":
            text = extract_text_from_md(path)
        elif suffix == ".txt":
            text = extract_text_from_txt(path)
        elif suffix == ".docx":
            text = extract_text_from_docx(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        pages = [(1, text)]
        use_pages = True

    if not text.strip():
        logger.warning("empty_document", doc_id=source.doc_id)
        return 0

    # Step 2: Choose chunking strategy
    if source.strategy and source.volume:
        # Handbook → chunk by module boundaries
        raw_chunks = chunk_by_module_boundaries(pages, source)
    elif source.scope in (DocumentScope.governance, DocumentScope.process):
        # Spec/process → chunk pages with context
        raw_chunks = chunk_pages_with_context(pages, source)
    else:
        # Default → sliding window
        raw_chunks = chunk_sliding_window(text, source)

    if not raw_chunks:
        logger.warning("no_chunks_generated", doc_id=source.doc_id)
        return 0

    # Step 3: Register document
    doc = KBDocument(
        doc_id=source.doc_id,
        doc_version=source.doc_version,
        title=source.title,
        scope=source.scope,
        strategy=source.strategy,
        volume=source.volume,
        module_id=source.module_id,
        owner=source.owner,
        supersedes=source.supersedes,
    )
    await upsert_document(doc)

    # Step 4: Delete old chunks
    await delete_chunks_for_document(source.doc_id)

    # Step 5: Embed
    texts = [c.content for c in raw_chunks]
    embeddings = await embed_documents(texts)

    # Step 6: Build KBChunk objects
    kb_chunks: list[KBChunk] = []
    for i, (raw, embedding) in enumerate(zip(raw_chunks, embeddings)):
        chunk_id = make_chunk_id(source.doc_id, raw.content, i)
        kb_chunks.append(
            KBChunk(
                chunk_id=chunk_id,
                doc_id=source.doc_id,
                doc_version=source.doc_version,
                content=raw.content,
                token_count=_count_tokens(raw.content),
                embedding=embedding,
                metadata=raw.metadata,
            )
        )

    # Step 7: Upsert
    count = await upsert_chunks(kb_chunks)
    logger.info("ingestion_complete", doc_id=source.doc_id, chunks=count)
    return count


async def ingest_all_project_documents(kb_dir: Path) -> dict[str, int]:
    """Ingest all project documents defined in the source registry.

    Args:
        kb_dir: Path to kb_content/ directory.

    Returns:
        Dict of {doc_id: chunk_count} for each document.
    """
    sources = _build_source_registry(kb_dir)
    results: dict[str, int] = {}

    for source in sources:
        if not source.path.exists():
            logger.warning("source_not_found", doc_id=source.doc_id, path=str(source.path))
            results[source.doc_id] = -1
            continue

        try:
            count = await ingest_document(source)
            results[source.doc_id] = count
        except Exception as e:
            logger.error("ingestion_error", doc_id=source.doc_id, error=str(e))
            results[source.doc_id] = -1

    return results


def _build_source_registry(kb_dir: Path) -> list[IngestionSource]:
    """Build the registry of all documents to ingest.

    Project documents are in the sibling project_docs/ directory.
    KB content is in kb_dir (filters, parameters, playbook).
    """
    project_dir = kb_dir.parent / "project_docs"
    sources: list[IngestionSource] = []

    # Project documents (ZIP archives with .pdf extensions)
    project_docs = [
        ("aitrate_agent_spec_v1_0", "1.0", "aiTrate AI Agent Functional Spec v1.0", DocumentScope.governance, "aiTrate_AI_Agent_Functional_Spec_v1_0.pdf"),
        ("alpha_handbook_v15_9_1_vol_ab", "15.9.1", "NARRUX Alpha v15.9.1 Handbook Vol A-B", DocumentScope.strategy, "NARRUX_Alpha_v15_9_1_Handbook_Vol_AB.pdf", "alpha", "AB"),
        ("alpha_handbook_v15_9_1_vol_c", "15.9.1", "NARRUX Alpha v15.9.1 Handbook Vol C", DocumentScope.strategy, "NARRUX_Alpha_v15_9_1_Handbook_Vol_C.pdf", "alpha", "C"),
        ("alpha_handbook_v15_9_1_vol_d", "15.9.1", "NARRUX Alpha v15.9.1 Handbook Vol D", DocumentScope.strategy, "NARRUX_Alpha_v15_9_1_Handbook_Vol_D.pdf", "alpha", "D"),
        ("alpha_handbook_v15_9_1_vol_ef", "15.9.1", "NARRUX Alpha v15.9.1 Handbook Vol E-F", DocumentScope.strategy, "NARRUX_Alpha_v15_9_1_Handbook_Vol_EF.pdf", "alpha", "EF"),
        ("alpha_handbook_v15_9_1_vol_hl", "15.9.1", "NARRUX Alpha v15.9.1 Handbook Vol H-L", DocumentScope.strategy, "NARRUX_Alpha_v15_9_1_Handbook_Vol_HL.pdf", "alpha", "HL"),
        ("sentinel_handbook_v1_9", "1.9", "NARRUX Sentinel v1.9 Handbook", DocumentScope.strategy, "NARRUX_Sentinel_v1_9_Handbook.pdf", "sentinel", None),
        ("backtest_analysis_approach_v1_0", "1.0", "NARRUX Backtest Analysis Approach v1.0", DocumentScope.process, "NARRUX_Backtest_Analysis_Approach_v1_0.pdf"),
        ("copilot_report_template_v1_0", "1.0", "NARRUX CoPilot Report Template v1.0", DocumentScope.process, "NARRUX_CoPilot_Report_Template_v1_0.pdf"),
    ]

    # NOTE: Do NOT register NARRUX_Alpha_v15_9_1_fulldepth_sample.pdf —
    # its content is already in vol_ef.

    for doc in project_docs:
        doc_id, version, title, scope = doc[0], doc[1], doc[2], doc[3]
        filename = doc[4]
        strategy = doc[5] if len(doc) > 5 else None
        volume = doc[6] if len(doc) > 6 else None

        sources.append(
            IngestionSource(
                path=project_dir / filename,
                doc_id=doc_id,
                doc_version=version,
                title=title,
                scope=scope,
                strategy=strategy,
                volume=volume,
            )
        )

    # KB content — filter glossary
    filters_dir = kb_dir / "filters"
    if filters_dir.exists():
        for md_file in sorted(filters_dir.glob("*.md")):
            sources.append(
                IngestionSource(
                    path=md_file,
                    doc_id=f"filter_glossary_{md_file.stem}",
                    doc_version="1.0",
                    title=f"Filter Glossary: {md_file.stem}",
                    scope=DocumentScope.filter_glossary,
                )
            )

    # KB content — parameter master
    param_file = kb_dir / "parameters" / "param_class_master.yaml"
    if param_file.exists():
        sources.append(
            IngestionSource(
                path=param_file,
                doc_id="param_class_master",
                doc_version="1.0",
                title="Parameter Class Master",
                scope=DocumentScope.parameter_master,
            )
        )

    # KB content — playbook
    playbook_dir = kb_dir / "playbook"
    if playbook_dir.exists():
        for md_file in sorted(playbook_dir.glob("*.md")):
            sources.append(
                IngestionSource(
                    path=md_file,
                    doc_id=f"playbook_{md_file.stem}",
                    doc_version="1.0",
                    title=f"Playbook: {md_file.stem}",
                    scope=DocumentScope.playbook,
                )
            )

    return sources
