"""Agent — the main RAG loop for the NARRUX aiTrate Co-Pilot.

Routes F-01 through F-05. Orchestrates:
retrieve → rerank → build prompt → LLM → validate → audit → respond

ONLY file (besides llm_client.py) that may import pydantic_ai.
LOC budget: ≤ 500 lines across orchestration/.
"""

from __future__ import annotations

import time
from pathlib import Path

import structlog

from audit.logger import write_audit_entry
from config import get_settings
from orchestration.llm_client import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    get_llm_client,
)
from retrieval.citation import verify_citations
from retrieval.embeddings import embed_query
from retrieval.reranker import RankedChunk, ranked_chunks_to_citations, rerank
from retrieval.vector_store import similarity_search
from tools.schemas import (
    AgentResponse,
    AuditEntry,
    Citation,
    ConfidenceLevel,
    FunctionID,
    TSIGrade,
)
from validation.citation_enforcer import enforce_citations
from validation.output_validator import validate_response

logger = structlog.get_logger(__name__)
settings = get_settings()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Resolve models based on LLM provider setting
def _get_models() -> dict[str, str]:
    """Return primary/secondary model names based on llm_provider setting."""
    if settings.llm_provider == "anthropic":
        return {
            "primary": settings.anthropic_model_primary,
            "secondary": settings.anthropic_model_secondary,
        }
    return {
        "primary": settings.gemini_model_primary,
        "secondary": settings.gemini_model_secondary,
    }


_models = _get_models()


# Function routing table
FUNCTION_CONFIG = {
    FunctionID.F01: {
        "model": _models["primary"],
        "prompt_file": "f01_strategy_explainer.md",
        "retrieval_scope": "strategy",
    },
    FunctionID.F02: {
        "model": _models["primary"],
        "prompt_file": "f02_backtest_interpreter.md",
        "retrieval_scope": "backtest_analysis",
    },
    FunctionID.F04: {
        "model": _models["primary"],
        "prompt_file": "f04_parameter_recommender.md",
        "retrieval_scope": "filter_glossary",
    },
    FunctionID.F05: {
        "model": _models["secondary"],
        "prompt_file": "f05_drift_monitor.md",
        "retrieval_scope": "drift_monitor",
    },
}


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts directory."""
    path = PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("prompt_not_found", filename=filename)
    return ""


def _build_full_prompt(function_id: FunctionID, user_message: str, structured_input: dict | None = None) -> str:
    """Build the full prompt from system prompt + function prompt + user message."""
    system = _load_prompt("system_v1_0.md")
    function_prompt = _load_prompt(FUNCTION_CONFIG[function_id]["prompt_file"])

    parts = [system, "\n\n---\n\n", function_prompt]

    if structured_input:
        parts.append(f"\n\n## Structured Input\n```json\n{structured_input}\n```")

    parts.append(f"\n\n## User Question\n{user_message}")

    return "\n".join(parts)


import re

# Patterns for specific entities that must appear in chunks if asked about
_ENTITY_PATTERNS = [
    # Filter IDs: F31, F35, F01, etc.
    (r"\b[Ff](\d{1,2})\b", lambda m: f"f{m.group(1)}"),
    # Stock/crypto tickers: AAPL, PLTR, XRP, BTC, etc.
    (r"\b([A-Z]{2,5})\b", lambda m: m.group(1).lower()),
    # Specific indicators: XYZ, etc.
    (r"\b([A-Z]{3})\b", lambda m: m.group(1).lower()),
]


def _check_entity_in_chunks(question: str, ranked: list) -> str | None:
    """Check if specific entities from the question appear in retrieved chunks.

    Returns the entity string if it's asked about but NOT found in any chunk,
    indicating the question is about something that doesn't exist in the KB.
    Returns None if all entities are found or no specific entities detected.
    """
    q_lower = question.lower()

    # Extract filter IDs from question
    filter_matches = re.findall(r"\b[Ff](\d{1,2})\b", question)
    if filter_matches:
        # Check if any chunk mentions these specific filter IDs
        all_content = " ".join(rc.chunk.content.lower() for rc in ranked)
        for fid in filter_matches:
            # Look for "F31", "filter 31", "filter31", etc.
            patterns = [
                rf"\bf{fid}\b",
                rf"\bfilter\s*{fid}\b",
                rf"\bfid\s*{fid}\b",
            ]
            if not any(re.search(p, all_content) for p in patterns):
                return f"F{fid}"

    # Extract ticker symbols (3-5 uppercase letters) for score/performance questions
    if any(kw in q_lower for kw in ["score", "tsi", "performance", "backtest"]):
        tickers = re.findall(r"\b([A-Z]{3,5})\b", question)
        _STOP = {"THE", "AND", "FOR", "NOT", "WHAT", "HOW", "WHEN", "CAN",
                 "TSI", "DQ", "MDD", "PF", "ADX", "MACD", "BB", "RSI",
                 "CVD", "CMF", "MFI", "ATR", "EMA", "SMA", "RTF",
                 "BE1", "BE2", "SR", "RT", "CA"}
        tickers = [t for t in tickers if t not in _STOP]
        if tickers:
            all_content = " ".join(rc.chunk.content.lower() for rc in ranked)
            for ticker in tickers:
                if ticker.lower() not in all_content:
                    return ticker

    # Extract indicator/filter names for questions about specific indicators
    # e.g., "What does the XYZ indicator do?" → check if "xyz" is in chunks
    indicator_match = re.search(r"\b(?:the\s+)?([A-Z]{3,5})\s+(?:indicator|filter|signal|strategy)\b", question)
    if indicator_match:
        name = indicator_match.group(1).lower()
        _STOP_NAMES = {"tsi", "adx", "macd", "rsi", "cvd", "cmf", "mfi", "atr", "ema", "sma"}
        if name not in _STOP_NAMES:
            all_content = " ".join(rc.chunk.content.lower() for rc in ranked)
            if name not in all_content:
                return indicator_match.group(1)

    return None


async def run(
    function_id: FunctionID,
    user_message: str,
    user_id: str,
    structured_input: dict | None = None,
    metadata_filter: dict | None = None,
    adapter: str = "gemini",
) -> AgentResponse:
    """Full RAG pipeline.

    1. Load system prompt + function prompt
    2. Build retrieval query
    3. embed_query → similarity_search → rerank
    4. If nothing clears rerank threshold → return ABSTAIN immediately
    5. Build LLMRequest with context chunks
    6. LLMClient.complete()
    7. Parse response into AgentResponse
    8. validate_response() → output_validator
    9. enforce_citations() → citation_enforcer
    10. write_audit_entry() — BEFORE returning to caller
    11. Return AgentResponse
    """
    start_time = time.monotonic()
    config = FUNCTION_CONFIG[function_id]

    logger.info(
        "agent_run_start",
        function_id=function_id.value,
        user_id=user_id,
        message=user_message[:100],
    )

    # Step 1: Build prompts
    full_prompt = _build_full_prompt(function_id, user_message, structured_input)
    system_prompt_hash = get_llm_client(adapter).system_prompt_hash(full_prompt)

    # Step 2: Build retrieval query
    retrieval_query = user_message
    if structured_input and "query" in structured_input:
        retrieval_query = structured_input["query"]

    # Step 3: Retrieve → rerank
    query_embedding = await embed_query(retrieval_query)
    chunks = await similarity_search(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        metadata_filter=metadata_filter,
    )

    if not chunks:
        logger.warning("no_chunks_retrieved", query=retrieval_query[:100])
        return _make_abstain(function_id, "no_retrieval_results")

    ranked = await rerank(retrieval_query, chunks, top_n=settings.rerank_top_n)

    # Step 4: If nothing clears rerank threshold → abstain
    if not ranked:
        logger.warning("nothing_passed_rerank_threshold")
        return _make_abstain(function_id, "rerank_threshold_not_met")

    # Step 4b: Entity relevance check — if the question asks about a specific
    # entity (filter ID, indicator name, ticker, etc.) and NONE of the retrieved
    # chunks mention it, force abstain. This catches hallucination on questions
    # about nonexistent things (e.g., "What does filter F31 do?" when F31 doesn't exist).
    entity_check = _check_entity_in_chunks(user_message, ranked)
    if entity_check is not None:
        logger.warning("entity_not_in_chunks", entity=entity_check)
        return _make_abstain(function_id, f"entity_not_found:{entity_check}")

    # Step 5: Build LLMRequest
    context_chunks = [rc.chunk.content for rc in ranked]
    citations = ranked_chunks_to_citations(ranked)
    rerank_scores = [rc.score for rc in ranked]

    llm_client = get_llm_client(adapter)
    request = LLMRequest(
        system_prompt=full_prompt,
        user_message=user_message,
        context_chunks=context_chunks,
        model=config["model"],
        max_tokens=settings.max_tokens_per_response,
    )

    # Step 6: LLM complete
    try:
        llm_response = await llm_client.complete(request)
    except Exception as e:
        logger.error("llm_error", error=str(e))
        return _make_abstain(function_id, f"llm_error:{e}")

    # Step 7: Parse into AgentResponse
    response = AgentResponse(
        function_id=function_id,
        content=llm_response.content,
        citations=citations,
        confidence=ConfidenceLevel.high,
    )

    # Step 8: Validate
    response = validate_response(response)

    # Step 9: Enforce citations
    response = await enforce_citations(response)

    # Step 9b: If LLM self-abstained (output the abstain message), set confidence
    from validation.citation_enforcer import ABSTAIN_MESSAGE
    if response.confidence != ConfidenceLevel.abstain:
        # Check if LLM output matches abstain pattern
        abstain_patterns = [
            r"I don.t have a grounded citation",
            r"I cannot find",
            r"no citation",
            r"not in my knowledge base",
        ]
        if any(re.search(p, response.content, re.IGNORECASE) for p in abstain_patterns):
            response = response.model_copy(update={"confidence": ConfidenceLevel.abstain})

    # Step 10: Audit — MUST succeed before returning
    duration_ms = int((time.monotonic() - start_time) * 1000)
    audit_entry = AuditEntry(
        response_id=response.response_id,
        user_id=user_id,
        function_id=function_id.value,
        prompt_template_version="1.0",
        system_prompt_hash=system_prompt_hash,
        user_message=user_message,
        retrieval_query=retrieval_query,
        retrieval_results=citations,
        rerank_scores=rerank_scores,
        llm_model=llm_response.model,
        llm_input_tokens=llm_response.input_tokens,
        llm_output_tokens=llm_response.output_tokens,
        llm_cost_usd=llm_response.cost_usd,
        raw_llm_response=llm_response.raw,
        parsed_response=response,
        duration_ms=duration_ms,
    )

    try:
        await write_audit_entry(audit_entry)
    except Exception as e:
        logger.error("audit_write_failed", error=str(e))
        raise  # Do not return unaudited response

    logger.info(
        "agent_run_complete",
        function_id=function_id.value,
        confidence=response.confidence.value,
        citations=len(response.citations),
        duration_ms=duration_ms,
    )

    return response


def _make_abstain(function_id: FunctionID, reason: str) -> AgentResponse:
    """Create an abstain response."""
    from validation.citation_enforcer import ABSTAIN_MESSAGE

    return AgentResponse(
        function_id=function_id,
        content=ABSTAIN_MESSAGE,
        citations=[],
        confidence=ConfidenceLevel.abstain,
        validator_results={"abstain_reason": reason},
    )
