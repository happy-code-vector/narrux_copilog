"""Orchestration layer — agent definition and LLM client adapter.

This is the ONLY module allowed to import pydantic_ai.
Keep this directory ≤ 400 LOC.
"""

from orchestration.llm_client import LLMClient, LLMResponse, Tool
from orchestration.agent import AiTrateAgent

__all__ = ["LLMClient", "LLMResponse", "Tool", "AiTrateAgent"]
