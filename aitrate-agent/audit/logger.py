"""Audit logger — append-only log of every agent output.

Uses structlog. NO pydantic_ai imports.
CRITICAL: This function must raise on failure.
The caller must not return a response if audit fails.
"""

import json

import structlog

from retrieval.vector_store import get_conn
from tools.schemas import AuditEntry

logger = structlog.get_logger(__name__)


async def write_audit_entry(entry: AuditEntry) -> None:
    """Write an audit entry to the append-only audit_log table.

    Raises on failure — the caller must not return a response if audit fails.
    """
    logger.info(
        "writing_audit_entry",
        entry_id=str(entry.entry_id),
        response_id=str(entry.response_id),
        function_id=entry.function_id,
        user_id=entry.user_id,
        duration_ms=entry.duration_ms,
        confidence=entry.confidence if hasattr(entry, "confidence") else "unknown",
    )

    retrieval_results_json = json.dumps(
        [c.model_dump() for c in entry.retrieval_results]
    )
    rerank_scores_json = json.dumps(entry.rerank_scores)
    parsed_response_json = entry.parsed_response.model_dump_json()
    validator_log_json = json.dumps(entry.validator_log)

    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO audit_log (
                entry_id, response_id, user_id, function_id,
                prompt_template_version, system_prompt_hash,
                user_message, retrieval_query,
                retrieval_results, rerank_scores,
                llm_model, llm_input_tokens, llm_output_tokens,
                llm_cost_usd, raw_llm_response, parsed_response,
                validator_log, duration_ms, timestamp
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                str(entry.entry_id),
                str(entry.response_id),
                entry.user_id,
                entry.function_id,
                entry.prompt_template_version,
                entry.system_prompt_hash,
                entry.user_message,
                entry.retrieval_query,
                retrieval_results_json,
                rerank_scores_json,
                entry.llm_model,
                entry.llm_input_tokens,
                entry.llm_output_tokens,
                entry.llm_cost_usd,
                entry.raw_llm_response,
                parsed_response_json,
                validator_log_json,
                entry.duration_ms,
                entry.timestamp,
            ),
        )
        await conn.commit()

    logger.info("audit_entry_written", entry_id=str(entry.entry_id))
