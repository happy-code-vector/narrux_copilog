"""Citation extraction and validation — enforces citations-or-silence rule.

NO framework imports. Pure Python + Pydantic.
"""

import re
import structlog
from dataclasses import dataclass

from retrieval.vector_store import SearchResult

logger = structlog.get_logger(__name__)


@dataclass
class Citation:
    """A validated citation."""

    handle: str  # e.g., "Master Long v14, §3.2, F19"
    source_file: str
    doc_id: str
    section: str | None
    line_number: int | None
    relevance_score: float


@dataclass
class CitedClaim:
    """A claim with its supporting citation."""

    claim: str
    citation: Citation


class CitationEnforcer:
    """Enforces the citations-or-silence rule.

    Every factual claim in the agent's output must have a citation.
    If no citation can be found, the claim is suppressed.
    """

    def __init__(self):
        # Patterns that indicate factual claims requiring citations
        self._factual_patterns = [
            r"(?:is|are|was|were)\s+(?:a|an|the)?\s*Class\s+[ABC]",
            r"filter\s+F\d+",
            r"baseline\s+(?:is|of|=)\s+\d+",
            r"range\s+(?:is|of|=)\s+[\d\-]+",
            r"parameter\s+\w+\s+(?:is|has|set\s+to)",
            r"(?:Master|Alpha)\s+(?:Long|Short|Unified)\s+v\d+",
            r"BE2|RT-BE-SR|trailing stop",
            r"TSI\s+(?:grade|score)\s+[SABCD]",
        ]
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self._factual_patterns]

    def extract_claims(self, text: str) -> list[str]:
        """Extract factual claims from agent output that require citations.

        Args:
            text: Agent output text.

        Returns:
            List of claims that need citations.
        """
        claims = []
        sentences = re.split(r'[.!?]+', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Check if sentence contains factual patterns
            for pattern in self._compiled_patterns:
                if pattern.search(sentence):
                    claims.append(sentence)
                    break

        return claims

    def validate_citations(
        self,
        text: str,
        search_results: list[SearchResult],
    ) -> tuple[bool, list[str]]:
        """Validate that claims in text are supported by search results.

        Args:
            text: Agent output text.
            search_results: Retrieved chunks that could support claims.

        Returns:
            Tuple of (is_valid, list_of_uncited_claims).
        """
        claims = self.extract_claims(text)
        if not claims:
            return True, []

        uncited_claims = []
        for claim in claims:
            # Check if any search result supports this claim
            is_supported = self._is_claim_supported(claim, search_results)
            if not is_supported:
                uncited_claims.append(claim)

        is_valid = len(uncited_claims) == 0

        if not is_valid:
            logger.warning(
                "citations_missing",
                total_claims=len(claims),
                uncited=len(uncited_claims),
            )

        return is_valid, uncited_claims

    def _is_claim_supported(
        self,
        claim: str,
        search_results: list[SearchResult],
    ) -> bool:
        """Check if a claim is supported by any search result.

        Uses keyword overlap as a simple heuristic.
        Could be enhanced with semantic similarity.
        """
        claim_words = set(claim.lower().split())

        for result in search_results:
            result_words = set(result.content.lower().split())
            overlap = claim_words & result_words

            # If >30% of claim words appear in the result, consider it supported
            if len(overlap) / len(claim_words) > 0.3:
                return True

        return False

    def format_with_citations(
        self,
        text: str,
        search_results: list[SearchResult],
    ) -> str:
        """Format text with inline citations.

        Args:
            text: Agent output text.
            search_results: Retrieved chunks with citation handles.

        Returns:
            Text with citations added.
        """
        if not search_results:
            return text

        # Add citation references at the end
        citations = []
        for i, result in enumerate(search_results[:5], 1):  # Top 5 citations
            citations.append(f"[{i}] {result.citation_handle}")

        if citations:
            text += "\n\n**Sources:**\n" + "\n".join(citations)

        return text
