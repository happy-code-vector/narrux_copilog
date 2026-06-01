"""Agent definition — the core of the aiTrate Co-Pilot.

This module defines the agent's behavior, tools, and prompt routing.
It uses the LLMClient protocol (not Pydantic AI directly).

Framework-coupled code is isolated to pydantic_ai_adapter.py.
"""

import time
import structlog
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from audit.logger import AuditLogger
from config.settings import get_settings
from retrieval.citation import CitationEnforcer
from retrieval.embeddings import EmbeddingClient
from retrieval.reranker import Reranker
from retrieval.vector_store import VectorStore
from orchestration.llm_client import LLMClient, LLMResponse, Tool
from tools.schemas import (
    FilterInfoRequest,
    ParameterClassRequest,
    BacktestParseRequest,
    TSIScoreRequest,
    TradeDBQueryRequest,
    DriftAnalysisRequest,
    ParameterRecommendationRequest,
)
from validation.output_validator import OutputValidator

logger = structlog.get_logger(__name__)

settings = get_settings()

# Load prompt templates
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_file = PROMPTS_DIR / name
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    return ""


class AiTrateAgent:
    """The aiTrate Co-Pilot agent.

    Orchestrates: retrieval → tool calls → validation → audit logging.

    Usage:
        agent = AiTrateAgent(llm_client, session)
        response = await agent.chat("What does F19 do?", user_id="analyst-001")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        session: AsyncSession,
    ):
        self._llm = llm_client
        self._session = session
        self._embeddings = EmbeddingClient()
        self._vector_store = VectorStore(session, self._embeddings)
        self._reranker = Reranker()
        self._citation_enforcer = CitationEnforcer()
        self._output_validator = OutputValidator()
        self._audit_logger = AuditLogger(session)

        # Load system prompt
        self._system_prompt = _load_prompt("system_v1.0.md") or self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """Default system prompt if template file doesn't exist."""
        return """You are the aiTrate Co-Pilot, an AI assistant for the NARRUX trading platform.

Your role is to help analysts, portfolio managers, and developers understand and optimize trading strategies.

CORE RULES:
1. CITATIONS-OR-SILENCE: Every factual claim must cite a source. If you cannot find a source, say "I don't have enough information to answer that."
2. SHADOW MODE: You are in read-only mode. No recommendations trigger live actions without explicit human confirmation.
3. ACCURACY FIRST: It is better to say "I don't know" than to guess.

You understand:
- NARRUX strategy architecture (Alpha, Master Long, Master Short)
- Parameter governance framework (Class A/B/C)
- TSI v2.0 CA scoring engine
- The live execution stack (TradingView → webhook → Python)
- The leverage methodology
- AGE / APE / PME governance roadmap

When answering:
- Be precise and technical
- Cite your sources (document name, section, line number)
- Flag uncertainty explicitly
- Use the tools available to you for calculations and lookups"""

    async def chat(
        self,
        message: str,
        user_id: str,
        conversation_id: str | None = None,
    ) -> dict:
        """Process a user message and return a response.

        Args:
            message: User's message.
            user_id: ID of the user.
            conversation_id: Optional conversation ID for context.

        Returns:
            Dict with response, citations, tools_called, etc.
        """
        start_time = time.monotonic()

        logger.info("agent_chat", user_id=user_id, message=message[:100])

        # Step 1: Retrieve relevant KB chunks
        search_results = await self._vector_store.search(
            query=message,
            top_k=settings.retrieval_top_k,
        )

        # Step 2: Rerank for better relevance
        reranked_results = await self._reranker.rerank(
            query=message,
            results=search_results,
            top_n=settings.retrieval_top_n,
        )

        # Step 3: Build context from retrieved chunks
        context = self._build_context(reranked_results)

        # Step 4: Generate response with LLM
        user_message_with_context = f"""Context from knowledge base:
{context}

User question: {message}

Answer the question using the context above. Cite your sources."""

        response = await self._llm.complete(
            system_prompt=self._system_prompt,
            user_message=user_message_with_context,
            temperature=settings.agent_temperature_routine,
            max_tokens=settings.agent_max_tokens,
        )

        # Step 5: Validate citations
        is_valid, uncited = self._citation_enforcer.validate_citations(
            response.content,
            reranked_results,
        )

        if not is_valid:
            logger.warning("uncited_claims_detected", uncited_count=len(uncited))
            # Add disclaimer
            response.content += "\n\n⚠️ Some claims could not be verified against the knowledge base."

        # Step 6: Format with citations
        formatted_response = self._citation_enforcer.format_with_citations(
            response.content,
            reranked_results,
        )

        # Step 7: Audit log
        latency_ms = int((time.monotonic() - start_time) * 1000)
        await self._audit_logger.log(
            user_id=user_id,
            function_id="F-01",  # Default to strategy explainer
            query=message,
            response=formatted_response,
            citations={
                "sources": [
                    {
                        "handle": r.citation_handle,
                        "source": r.source_file,
                        "similarity": r.similarity,
                    }
                    for r in reranked_results[:5]
                ]
            },
            model_used=response.model,
            latency_ms=latency_ms,
            token_usage=response.usage,
        )

        logger.info(
            "agent_chat_complete",
            latency_ms=latency_ms,
            citations_count=len(reranked_results),
        )

        return {
            "response": formatted_response,
            "citations": [
                {
                    "handle": r.citation_handle,
                    "source": r.source_file,
                    "similarity": r.similarity,
                }
                for r in reranked_results[:5]
            ],
            "latency_ms": latency_ms,
        }

    def _build_context(self, results: list) -> str:
        """Build context string from search results."""
        if not results:
            return "No relevant context found in the knowledge base."

        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[{i}] Source: {result.citation_handle}\n"
                f"File: {result.source_file}\n"
                f"Content: {result.content}\n"
            )

        return "\n---\n".join(context_parts)
