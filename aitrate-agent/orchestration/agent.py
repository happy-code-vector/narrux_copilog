"""Agent definition — the core of the aiTrate Co-Pilot.

This is the main RAG loop: retrieve → rerank → build prompt → LLM → validate → audit → respond.

NOT IN SCOPE for this build session. Built in next session after retrieval quality is validated.
The orchestration/llm_client.py provides the LLMClient protocol and adapters.
"""

# TODO: Implement AiTrateAgent with:
# - retrieve from vector_store
# - rerank with reranker
# - build prompt from context + system prompt
# - call LLM via LLMClient protocol
# - validate with citation_enforcer + output_validator
# - audit via write_audit_entry
# - return AgentResponse
