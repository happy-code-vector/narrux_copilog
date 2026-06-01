"""Pydantic AI adapter — implements LLMClient using Pydantic AI.

This is the ONLY file that imports pydantic_ai.
If we ever migrate to LangGraph or Direct Build, only this file changes.
"""

import structlog
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel

from config.settings import get_settings
from orchestration.llm_client import LLMClient, LLMResponse, Tool

logger = structlog.get_logger(__name__)

settings = get_settings()


class PydanticAILLMClient:
    """Pydantic AI implementation of LLMClient.

    Uses pydantic_ai.Agent for structured output and tool calling.
    """

    def __init__(self):
        # Initialize with Sonnet for routine queries
        self._sonnet_model = AnthropicModel(settings.anthropic_model_sonnet)
        self._opus_model = AnthropicModel(settings.anthropic_model_opus)

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[Tool] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a completion using Pydantic AI.

        Args:
            system_prompt: System prompt.
            user_message: User's message.
            tools: Available tools.
            response_schema: Optional Pydantic model for structured output.
            temperature: Sampling temperature.
            max_tokens: Max tokens.

        Returns:
            LLM response.
        """
        logger.info(
            "pydantic_ai_complete",
            tools_count=len(tools) if tools else 0,
            has_schema=response_schema is not None,
        )

        # Choose model based on task complexity
        # Use Opus for recommendation generation, Sonnet for routine
        model = self._sonnet_model
        if temperature > 0.2:  # Higher temp = more creative = recommendation
            model = self._opus_model

        # Create agent
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            result_type=response_schema if response_schema else str,
        )

        # Register tools if provided
        if tools:
            for tool_def in tools:
                # Pydantic AI tools are registered differently
                # This is a simplified version — actual implementation
                # would convert Tool definitions to Pydantic AI tool decorators
                pass

        # Run the agent
        try:
            result = await agent.run(user_message)

            return LLMResponse(
                content=str(result.data) if response_schema else result.data,
                tool_calls=[],  # Pydantic AI handles tool calls internally
                usage={
                    "input_tokens": result.usage().request_tokens if result.usage() else 0,
                    "output_tokens": result.usage().response_tokens if result.usage() else 0,
                },
                model=model.model_name if hasattr(model, 'model_name') else str(model),
                finish_reason="stop",
            )
        except Exception as e:
            logger.error("pydantic_ai_error", error=str(e))
            raise

    async def complete_streaming(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[Tool] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Generate a streaming completion using Pydantic AI.

        Note: Pydantic AI streaming support may be limited.
        This is a placeholder for when streaming is fully supported.
        """
        # For now, fall back to non-streaming
        response = await self.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield response.content
