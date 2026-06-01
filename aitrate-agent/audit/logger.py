"""Audit logger — append-only log of every agent output.

All agent outputs are logged with:
- User ID
- Query
- Response
- Citations used
- Tools called
- Model used
- Latency
- Token usage

This is a compliance requirement from the functional spec (§10, F-F1).
"""

import structlog
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog as AuditLogDB

logger = structlog.get_logger(__name__)


class AuditLogger:
    """Append-only audit log for agent outputs.

    Usage:
        audit = AuditLogger(session)
        await audit.log(
            user_id="analyst-001",
            function_id="F-01",
            query="What does F19 do?",
            response="F19 is the multi-day S/R proximity filter...",
            citations=[...],
            tools_called=[...],
            model_used="claude-sonnet-4-6",
            latency_ms=1234,
        )
    """

    def __init__(self, session: AsyncSession):
        self._session = session

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
        conversation_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        """Log an agent output to the audit trail.

        Args:
            user_id: ID of the user who made the query.
            function_id: Function identifier (e.g., "F-01", "F-02").
            query: User's original query.
            response: Agent's response.
            citations: Citations used in the response.
            tools_called: Tools invoked during response generation.
            model_used: LLM model used.
            latency_ms: Response latency in milliseconds.
            token_usage: Token usage breakdown.
            conversation_id: Optional conversation ID.
            metadata: Additional metadata.

        Returns:
            UUID of the created audit log entry.
        """
        entry_id = uuid4()

        logger.info(
            "audit_log_entry",
            entry_id=str(entry_id),
            user_id=user_id,
            function_id=function_id,
            latency_ms=latency_ms,
        )

        entry = AuditLogDB(
            id=entry_id,
            user_id=user_id,
            conversation_id=conversation_id,
            function_id=function_id,
            query=query,
            response=response,
            citations=citations,
            tools_called=tools_called,
            model_used=model_used,
            latency_ms=latency_ms,
            token_usage=token_usage,
            metadata_=metadata,
        )

        self._session.add(entry)
        await self._session.flush()

        return entry_id
