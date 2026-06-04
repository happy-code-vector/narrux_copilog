"""Health check routes."""

import structlog
from fastapi import APIRouter

from retrieval.vector_store import get_stats, get_conn

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/kb-stats")
async def kb_stats():
    """Return knowledge base statistics."""
    stats = await get_stats()
    return stats


@router.get("/ready")
async def ready():
    """Readiness check — verifies DB connectivity."""
    try:
        stats = await get_stats()
        return {"status": "ready", "kb_stats": stats}
    except Exception as e:
        logger.error("readiness_check_failed", error=str(e))
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": str(e)},
        )
