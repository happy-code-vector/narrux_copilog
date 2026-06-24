"""LLM client — Protocol + adapters (Gemini, Anthropic, Pydantic AI).

Adapters:
- 'gemini': Google Gemini API (default for development)
- 'anthropic': Direct Anthropic SDK
- 'pydantic_ai': Pydantic AI with Anthropic (production)

LOC budget: ≤ 500 lines across orchestration/.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import structlog

from config import get_settings

logger = structlog.get_logger(__name__)


# ─── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class LLMRequest:
    """Request to the LLM."""

    system_prompt: str
    user_message: str
    context_chunks: list[str] = field(default_factory=list)
    model: str | None = None
    max_tokens: int | None = None
    temperature: float = 0.1


@dataclass
class LLMResponse:
    """Response from the LLM."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    raw: str  # full serialised for audit


# ─── Protocol ────────────────────────────────────────────────────────────────


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM client implementations."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion."""
        ...

    def system_prompt_hash(self, prompt: str) -> str:
        """Compute a hash of the system prompt."""
        ...


# ─── Helpers ─────────────────────────────────────────────────────────────────


def compute_prompt_hash(prompt: str) -> str:
    """Compute a SHA-256 hash of the system prompt (truncated to 16 chars)."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


_COST_PER_1K: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    "gemini-2.5-flash": {"input": 0.00015, "output": 0.0006},
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.005},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the cost of an LLM call in USD."""
    costs = _COST_PER_1K.get(model, {"input": 0.001, "output": 0.002})
    return (input_tokens / 1000 * costs["input"]) + (output_tokens / 1000 * costs["output"])


def _build_context_block(chunks: list[str]) -> str:
    """Build a context block from retrieved chunks."""
    if not chunks:
        return ""
    lines = ["<retrieved_context>"]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"--- Chunk {i} ---\n{chunk}")
    lines.append("</retrieved_context>")
    return "\n".join(lines)


# ─── Gemini Adapter ──────────────────────────────────────────────────────────


class GeminiAdapter:
    """Google Gemini API adapter.

    Uses google.genai. Import happens inside __init__.
    """

    def __init__(self) -> None:
        from google import genai

        settings = get_settings()
        self._client = genai.Client(api_key=settings.google_api_key)
        self._settings = settings

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using Gemini API."""
        from google.genai.types import (
            GenerateContentConfig,
            HarmBlockThreshold,
            HarmCategory,
            SafetySetting,
            ThinkingConfig,
        )

        model = request.model or "gemini-2.5-flash"
        max_tokens = request.max_tokens or self._settings.max_tokens_per_response

        # Build context block
        context_block = _build_context_block(request.context_chunks)
        full_message = request.user_message
        if context_block:
            full_message = f"{context_block}\n\n{request.user_message}"

        logger.info("gemini_complete", model=model)

        # Disable thinking for Gemini 2.5 models (thinking consumes output tokens)
        config_kwargs = {
            "system_instruction": request.system_prompt,
            "max_output_tokens": max_tokens,
            "temperature": request.temperature,
            "safety_settings": [
                SafetySetting(
                    category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=HarmBlockThreshold.BLOCK_NONE,
                ),
                SafetySetting(
                    category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=HarmBlockThreshold.BLOCK_NONE,
                ),
                SafetySetting(
                    category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=HarmBlockThreshold.BLOCK_NONE,
                ),
                SafetySetting(
                    category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=HarmBlockThreshold.BLOCK_NONE,
                ),
            ],
        }
        if "2.5" in model:
            config_kwargs["thinking_config"] = ThinkingConfig(thinking_budget=0)

        response = self._client.models.generate_content(
            model=model,
            contents=full_message,
            config=GenerateContentConfig(**config_kwargs),
        )

        content = response.text or ""
        # Gemini doesn't always provide token counts in the same way
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0
        cost = estimate_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            raw=str(response),
        )

    def system_prompt_hash(self, prompt: str) -> str:
        return compute_prompt_hash(prompt)


# ─── Direct Anthropic Adapter ────────────────────────────────────────────────


class DirectAnthropicAdapter:
    """Direct Anthropic SDK adapter — no pydantic_ai dependency.

    Uses anthropic.AsyncAnthropic. Import happens inside __init__.
    """

    def __init__(self) -> None:
        import anthropic

        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._settings = settings

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using the Anthropic SDK directly."""
        model = request.model or self._settings.anthropic_model_primary
        max_tokens = request.max_tokens or self._settings.max_tokens_per_response

        # Build context block
        context_block = _build_context_block(request.context_chunks)
        full_message = request.user_message
        if context_block:
            full_message = f"{context_block}\n\n{request.user_message}"

        logger.info("direct_anthropic_complete", model=model)

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=request.temperature,
            system=request.system_prompt,
            messages=[{"role": "user", "content": full_message}],
        )

        content = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            raw=response.model_dump_json(),
        )

    def system_prompt_hash(self, prompt: str) -> str:
        return compute_prompt_hash(prompt)


# ─── Pydantic AI Adapter ─────────────────────────────────────────────────────


class PydanticAIAdapter:
    """Pydantic AI adapter.

    Imports pydantic_ai inside __init__ ONLY.
    Import at module level is FORBIDDEN.
    """

    def __init__(self) -> None:
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModel

        settings = get_settings()
        self._primary_model = AnthropicModel(settings.anthropic_model_primary)
        self._secondary_model = AnthropicModel(settings.anthropic_model_secondary)
        self._settings = settings
        self._Agent = Agent
        self._AnthropicModel = AnthropicModel

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using Pydantic AI."""
        model_name = request.model or self._settings.anthropic_model_primary
        model = self._AnthropicModel(model_name)
        max_tokens = request.max_tokens or self._settings.max_tokens_per_response

        context_block = _build_context_block(request.context_chunks)
        full_message = request.user_message
        if context_block:
            full_message = f"{context_block}\n\n{request.user_message}"

        logger.info("pydantic_ai_complete", model=model_name)

        agent = self._Agent(
            model=model,
            system_prompt=request.system_prompt,
        )

        result = await agent.run(full_message)

        content = str(result.data) if hasattr(result, "data") else str(result)
        usage = result.usage() if hasattr(result, "usage") else None
        input_tokens = usage.request_tokens if usage else 0
        output_tokens = usage.response_tokens if usage else 0
        cost = estimate_cost(model_name, input_tokens, output_tokens)

        return LLMResponse(
            content=content,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            raw=str(result),
        )

    def system_prompt_hash(self, prompt: str) -> str:
        return compute_prompt_hash(prompt)


# ─── Factory ─────────────────────────────────────────────────────────────────


def get_llm_client(adapter: str = "gemini") -> LLMClient:
    """Get an LLM client implementation.

    Args:
        adapter: "gemini" → GeminiAdapter, "anthropic" → DirectAnthropicAdapter,
                 "pydantic_ai" → PydanticAIAdapter
    """
    if adapter == "anthropic":
        return DirectAnthropicAdapter()
    if adapter == "pydantic_ai":
        return PydanticAIAdapter()
    return GeminiAdapter()
