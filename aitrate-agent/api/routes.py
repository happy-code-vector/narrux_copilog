"""API routes — chat, file upload, health endpoints."""

import structlog
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_async_session
from config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter()


# ─── Request/Response Models ─────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Chat request."""

    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    """Chat response."""

    response: str
    citations: list[dict]
    latency_ms: int


class BacktestUploadResponse(BaseModel):
    """Backtest upload response."""

    message: str
    strategy_id: str
    asset: str
    total_trades: int
    anomalies: list[dict]


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Chat endpoint — ask questions about strategies, parameters, etc.

    This is the main entry point for the aiTrate Co-Pilot.
    Supports F-01 (strategy explainer) queries.
    """
    logger.info("chat_request", message=request.message[:100])

    try:
        # Import here to avoid circular imports
        from orchestration.pydantic_ai_adapter import PydanticAILLMClient
        from orchestration.agent import AiTrateAgent

        llm_client = PydanticAILLMClient()
        agent = AiTrateAgent(llm_client, session)

        result = await agent.chat(
            message=request.message,
            user_id="api-user",  # TODO: Get from auth
            conversation_id=request.conversation_id,
        )

        return ChatResponse(
            response=result["response"],
            citations=result["citations"],
            latency_ms=result["latency_ms"],
        )
    except Exception as e:
        logger.error("chat_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest/upload", response_model=BacktestUploadResponse)
async def upload_backtest(
    file: UploadFile = File(...),
    strategy_id: str = "unknown",
    asset: str = "unknown",
    session: AsyncSession = Depends(get_async_session),
):
    """Upload a backtest xlsx file for analysis.

    Supports F-02 (backtest interpreter) functionality.
    """
    logger.info("backtest_upload", filename=file.filename, strategy_id=strategy_id)

    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")

    try:
        # Save uploaded file temporarily
        import tempfile
        from pathlib import Path
        from tools.backtest_parser import parse_backtest
        from tools.schemas import BacktestParseRequest

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Parse backtest
        request = BacktestParseRequest(
            file_path=str(tmp_path),
            strategy_id=strategy_id,
            asset=asset,
        )
        result = await parse_backtest(request)

        return BacktestUploadResponse(
            message=f"Backtest parsed successfully. {result.total_trades} trades found.",
            strategy_id=result.strategy_id,
            asset=result.asset,
            total_trades=result.total_trades,
            anomalies=[a.model_dump() for a in result.anomalies],
        )
    except Exception as e:
        logger.error("backtest_upload_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies/{strategy_id}/info")
async def get_strategy_info(
    strategy_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Get strategy information from the knowledge base.

    Supports F-01 (strategy explainer) queries.
    """
    logger.info("strategy_info_request", strategy_id=strategy_id)

    try:
        from retrieval.embeddings import EmbeddingClient
        from retrieval.vector_store import VectorStore
        from tools.knowledge_base import lookup_strategy_spec
        from tools.schemas import StrategySpecRequest

        embeddings = EmbeddingClient()
        vector_store = VectorStore(session, embeddings)

        request = StrategySpecRequest(strategy_name=strategy_id)
        result = await lookup_strategy_spec(request, vector_store)

        return result.model_dump()
    except Exception as e:
        logger.error("strategy_info_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
