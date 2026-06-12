"""Audit logger — append-only log of every agent output.

Uses structlog + JSONL file. NO pydantic_ai imports.
CRITICAL: This function must raise on failure.
The caller must not return a response if audit fails.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from tools.schemas import AuditEntry

logger = structlog.get_logger(__name__)

# Audit log file — append-only JSONL
_AUDIT_DIR = Path(__file__).parent.parent / "audit_data"
_AUDIT_FILE = _AUDIT_DIR / "audit_log.jsonl"


def _ensure_audit_dir() -> None:
    """Create audit directory if it doesn't exist."""
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)


async def write_audit_entry(entry: AuditEntry) -> None:
    """Write an audit entry to the append-only JSONL audit log.

    Raises on failure — the caller must not return a response if audit fails.
    """
    _ensure_audit_dir()

    logger.info(
        "writing_audit_entry",
        entry_id=str(entry.entry_id),
        response_id=str(entry.response_id),
        function_id=entry.function_id,
        user_id=entry.user_id,
        duration_ms=entry.duration_ms,
        confidence=entry.confidence if hasattr(entry, "confidence") else "unknown",
    )

    # Build audit record
    record = {
        "entry_id": str(entry.entry_id),
        "response_id": str(entry.response_id),
        "user_id": entry.user_id,
        "function_id": entry.function_id,
        "prompt_template_version": entry.prompt_template_version,
        "system_prompt_hash": entry.system_prompt_hash,
        "user_message": entry.user_message,
        "retrieval_query": entry.retrieval_query,
        "retrieval_results": [c.model_dump() for c in entry.retrieval_results],
        "rerank_scores": entry.rerank_scores,
        "llm_model": entry.llm_model,
        "llm_input_tokens": entry.llm_input_tokens,
        "llm_output_tokens": entry.llm_output_tokens,
        "llm_cost_usd": entry.llm_cost_usd,
        "raw_llm_response": entry.raw_llm_response,
        "parsed_response": json.loads(entry.parsed_response.model_dump_json()),
        "validator_log": entry.validator_log,
        "duration_ms": entry.duration_ms,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else datetime.now(timezone.utc).isoformat(),
    }

    # Append to JSONL file — atomic per line
    with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("audit_entry_written", entry_id=str(entry.entry_id))
