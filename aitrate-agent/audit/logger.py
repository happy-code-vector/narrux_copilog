"""Audit logger — append-only log of every agent output.

Uses asyncpg directly (no ORM).
"""

import structlog
from uuid import UUID, uuid4

import asyncpg

logger = structlog.get_logger(__name__)


INSERT_AUDIT_SQL = """
INSERT INTO audit_log (id, user_id, function_id, query, response, citations, tools_called, model_used, latency_ms, token_usage, metadata)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""


class AuditLogger:
    """Append-only audit log for agent outputs.

    Usage:
        audit = AuditLogger(conn)
        await audit.log(user_id="analyst-001", function_id="F-01", ...)
    """

    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    async def log(
        self,
        user_id: str,
        function_id: str,
        query: str,
        response: str,
        citations: dict | None = None,
        tools_called: dict | None = None,
        model_used: str = "unknown",
        latency_ms: int = 0,
        token_usage: dict | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        """Log an agent output to the audit trail."""
        entry_id = uuid4()

        logger.info(
            "audit_log_entry",
            entry_id=str(entry_id),
            user_id=user_id,
            function_id=function_id,
            latency_ms=latency_ms,
        )

        await self._conn.execute(
            INSERT_AUDIT_SQL,
            entry_id,
            user_id,
            function_id,
            query,
            response,
            citations,      # asyncpg handles dict → JSONB
            tools_called,
            model_used,
            latency_ms,
            token_usage,
            metadata,
        )

        return entry_id
