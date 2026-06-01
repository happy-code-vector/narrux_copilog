"""LLMClient protocol — the interface between agent core and LLM framework.

This is the abstraction layer that makes the framework replaceable.
The agent core calls this protocol; Pydantic AI (or any other framework) implements it.

NO framework imports in this file.
"""

from typing import Protocol, Any
from pydantic import BaseModel


class Tool(BaseModel):
    """Tool definition for the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]


class LLMResponse(BaseModel):
    """Response from the LLM."""

    content: str
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int] = {}
    model: str = ""
    finish_reason: str = ""


class LLMClient(Protocol):
    """Protocol for LLM client implementations.

    Any framework adapter (Pydantic AI, Direct Build, LangGraph)
    must implement this protocol.
    """

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[Tool] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a completion.

        Args:
            system_prompt: System prompt for the conversation.
            user_message: User's message.
            tools: Available tools the LLM can call.
            response_schema: Optional Pydantic model for structured output.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            LLM response with content and optional tool calls.
        """
        ...

    async def complete_streaming(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[Tool] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Generate a streaming completion.

        Yields:
            Partial response tokens.
        """
        ...
        yield ""  # Make this an async generator
