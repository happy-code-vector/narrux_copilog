"""Citation enforcement — the citations-or-silence gate.

NO pydantic_ai imports. Pure Python + Pydantic.
"""

import structlog

from retrieval.citation import citations_cover_claims, verify_citations
from tools.schemas import AgentResponse, ConfidenceLevel

logger = structlog.get_logger(__name__)

ABSTAIN_MESSAGE = (
    "I don't have a grounded citation for that in my current knowledge base. "
    "I cannot answer without a verified source — providing an ungrounded answer "
    "would risk inaccuracy on a financial strategy question."
)


async def enforce_citations(response: AgentResponse) -> AgentResponse:
    """Enforce the citations-or-silence rule on an agent response.

    Step 1: If citations exist, verify them. If any failed → abstain.
    Step 2: Check citations_cover_claims. If fails → abstain.
    Step 3: If min citation score < 0.3 → downgrade confidence to LOW.

    Returns:
        Modified response (possibly abstained).
    """
    # Step 1: Verify existing citations
    if response.citations:
        verified, failed = await verify_citations(response.citations)
        if failed:
            logger.warning("citation_verification_failed", failed=failed)
            return _make_abstain(response, reason=f"hallucinated_citations:{failed}")
        response = response.model_copy(update={"citations": verified})

    # Step 2: Check if citations cover claims
    if not citations_cover_claims(response.content, response.citations):
        logger.warning("claims_without_citations")
        return _make_abstain(response, reason="claims_without_citations")

    # Step 3: Check minimum citation score
    if response.citations:
        min_score = min(c.relevance_score for c in response.citations)
        if min_score < 0.3:
            logger.info("low_citation_score_downgrading", min_score=min_score)
            response = response.model_copy(update={"confidence": ConfidenceLevel.low})

    return response


def _make_abstain(response: AgentResponse, reason: str) -> AgentResponse:
    """Convert a response to an abstain response."""
    existing_results = response.validator_results or {}
    return response.model_copy(
        update={
            "content": ABSTAIN_MESSAGE,
            "citations": [],
            "confidence": ConfidenceLevel.abstain,
            "validator_results": {
                **existing_results,
                "citation_enforcer": {"passed": False, "reason": reason},
            },
        }
    )
