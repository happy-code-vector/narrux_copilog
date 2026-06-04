"""Unit tests for retrieval/ingestion.py — no DB, no Voyage API needed."""

import io
import zipfile
import tempfile
from pathlib import Path

import pytest

from retrieval.ingestion import (
    _is_zip_archive,
    _strip_page_header_footer,
    chunk_by_module_boundaries,
    chunk_sliding_window,
    make_chunk_id,
)


class TestStripPageHeaderFooter:
    """Test header/footer stripping."""

    def test_strip_narrux_header(self):
        """NARRUX header lines are stripped."""
        text = """Strictly Confidential — NARRUX Group
This is actual content.
NARRUX Alpha v15.9.1 Handbook
More content here.
Page 1 of 10"""
        result = _strip_page_header_footer(text)
        assert "Strictly Confidential" not in result
        assert "NARRUX Alpha" not in result
        assert "Page 1 of 10" not in result
        assert "actual content" in result
        assert "More content" in result


class TestIsZipArchive:
    """Test ZIP archive detection via magic bytes."""

    def test_is_zip_archive_true(self):
        """A real ZIP file returns True."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("1.txt", "page content")
        buf.seek(0)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(buf.read())
            tmp_path = Path(f.name)

        assert _is_zip_archive(tmp_path) is True
        tmp_path.unlink()

    def test_is_zip_archive_false(self):
        """A non-ZIP file returns False."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("This is not a zip file")
            tmp_path = Path(f.name)

        assert _is_zip_archive(tmp_path) is False
        tmp_path.unlink()


class TestChunkSlidingWindow:
    """Test sliding window chunking."""

    def test_chunk_sliding_window(self):
        """Chunk a ~1000-token text and verify chunk count."""
        # Create text that's roughly 1000 tokens
        text = "word " * 1200  # ~1200 tokens

        from tools.schemas import DocumentScope

        class FakeSource:
            doc_id = "test_doc"
            doc_version = "1.0"
            scope = DocumentScope.process
            strategy = None
            volume = None

        source = FakeSource()
        chunks = chunk_sliding_window(text, source)

        # Should produce multiple chunks
        assert len(chunks) >= 2
        # Each chunk should have metadata
        for chunk in chunks:
            assert "chunk_index" in chunk.metadata
            assert "doc_id" in chunk.metadata


class TestModuleBoundaryDetection:
    """Test module boundary chunking."""

    def test_module_boundary_detection(self):
        """Text with module headers → correct RawChunks."""
        text = """D1 · CVD Filter [C]
The CVD filter measures cumulative volume delta.
It is regime-coupled and non-stationary.

D2 · Supertrend Signal [A]
The Supertrend signal is a trend-following indicator.
It is Class A — set and forget."""

        # Create a minimal page list
        pages = [(1, text)]

        from tools.schemas import DocumentScope

        class FakeSource:
            doc_id = "test_handbook"
            doc_version = "15.9.1"
            scope = DocumentScope.strategy
            strategy = "alpha"
            volume = "D"

        source = FakeSource()
        chunks = chunk_by_module_boundaries(pages, source)

        assert len(chunks) == 2
        assert chunks[0].metadata["module_id"] == "D1"
        assert chunks[0].metadata["module_name"] == "CVD Filter"
        assert chunks[0].metadata["param_class"] == "C"
        assert chunks[0].metadata["regime_coupled"] is True

        assert chunks[1].metadata["module_id"] == "D2"
        assert chunks[1].metadata["module_name"] == "Supertrend Signal"
        assert chunks[1].metadata["param_class"] == "A"
        assert chunks[1].metadata["regime_coupled"] is False


class TestMakeChunkId:
    """Test chunk ID generation."""

    def test_make_chunk_id_deterministic(self):
        """Same inputs → same ID always."""
        id1 = make_chunk_id("doc_1", "some content here", 0)
        id2 = make_chunk_id("doc_1", "some content here", 0)
        assert id1 == id2

    def test_make_chunk_id_different_content(self):
        """Different content → different ID."""
        id1 = make_chunk_id("doc_1", "content A", 0)
        id2 = make_chunk_id("doc_1", "content B", 0)
        assert id1 != id2

    def test_make_chunk_id_format(self):
        """ID has correct format: doc_id::hash."""
        chunk_id = make_chunk_id("my_doc", "text", 0)
        assert chunk_id.startswith("my_doc::")
        assert len(chunk_id) == len("my_doc::") + 16
