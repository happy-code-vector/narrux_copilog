"""Citation verification and extraction.

NO pydantic_ai imports. Pure Python + Pydantic.
"""

from __future__ import annotations

import re

import structlog

from tools.schemas import Citation

logger = structlog.get_logger(__name__)


async def verify_citations(
    citations: list[Citation],
) -> tuple[list[Citation], list[str]]:
    """Verify that citations point to real chunks in the KB.

    For each citation, call get_chunk_by_id. If None → hallucinated.
    If doc_id mismatch → failed.

    Returns:
        (verified_citations, failed_citation_ids)
    """
    from retrieval.vector_store import get_chunk_by_id

    verified: list[Citation] = []
    failed: list[str] = []

    for citation in citations:
        chunk = await get_chunk_by_id(citation.chunk_id)
        if chunk is None:
            logger.warning("hallucinated_citation", chunk_id=citation.chunk_id)
            failed.append(citation.chunk_id)
            continue
        if chunk.doc_id != citation.doc_id:
            logger.warning(
                "citation_doc_id_mismatch",
                chunk_id=citation.chunk_id,
                expected=citation.doc_id,
                actual=chunk.doc_id,
            )
            failed.append(citation.chunk_id)
            continue
        verified.append(citation)

    return verified, failed


def extract_citation_handles_from_text(text: str) -> list[str]:
    """Extract citation references from agent output text.

    Finds bracketed references like [Alpha Handbook §D1 — CVD Filter]
    or [file.pine:L437].
    """
    pattern = r"[\[\(]([^\]\)]+§[^\]\)]+|[^\]\)]+\.pine:L\d+)[\]\)]"
    return re.findall(pattern, text)


def citations_cover_claims(response_text: str, citations: list[Citation]) -> bool:
    """Check whether citations cover the substantive claims in the response.

    Returns True if coverage is adequate (or if the agent is abstaining).
    Returns False if there are claims without citations.
    """
    # Abstain patterns — silence is correct
    abstain_patterns = [
        r"I don.t have",
        r"I cannot find",
        r"no citation",
        r"not in my knowledge base",
    ]
    for pattern in abstain_patterns:
        if re.search(pattern, response_text, re.IGNORECASE):
            return True

    # Patterns that indicate substantive claims requiring citation
    claim_patterns = [
        r"\bF\d{1,2}\b",  # filter references
        r"\bClass [ABC]\b",
        r"\bTSI\b.{0,20}\b\d+\.?\d*\b",
        r"\bdefault\b.{0,30}\b[\d.]+\b",
        r"\b(blocks?|requires?|fires?|activates?)\b",
        r"\b(Bollinger|Supertrend|MACD|RSI|CVD|ATR|ADX|MFI)\b",
        r"\b(BE1|BE2|RT-BE|trailing stop|stop.loss)\b",
    ]

    has_claims = any(re.search(p, response_text, re.IGNORECASE) for p in claim_patterns)

    if has_claims and not citations:
        return False

    return True
