"""Chat endpoint — stub.

TODO: Wire to orchestration/agent.py once retrieval quality is validated.
"""

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Chat request."""

    message: str


class ChatResponse(BaseModel):
    """Chat response."""

    error: str
    status: int


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat endpoint — not yet implemented.

    Returns 501 Not Implemented.
    This will be wired to orchestration/agent.py in the next session.
    """
    logger.info("chat_request_received", message=request.message[:100])
    return ChatResponse(
        error="Chat endpoint not yet implemented",
        status=501,
    )
