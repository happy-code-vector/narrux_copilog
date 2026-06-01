"""API routes — chat, file upload, health endpoints."""

import structlog
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from db.session import get_pool

logger = structlog.get_logger(__name__)

router = APIRouter()


# ─── Request/Response Models ─────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Chat request."""
    message: str


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
async def chat(request: ChatRequest):
    """Chat endpoint — ask questions about strategies, parameters, etc."""
    logger.info("chat_request", message=request.message[:100])

    try:
        from orchestration.pydantic_ai_adapter import PydanticAILLMClient
        from orchestration.agent import AiTrateAgent

        pool = await get_pool()
        async with pool.acquire() as conn:
            llm_client = PydanticAILLMClient()
            agent = AiTrateAgent(llm_client, conn)

            result = await agent.chat(
                message=request.message,
                user_id="api-user",  # TODO: Get from auth
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
):
    """Upload a backtest xlsx file for analysis."""
    logger.info("backtest_upload", filename=file.filename, strategy_id=strategy_id)

    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")

    try:
        import tempfile
        from pathlib import Path
        from tools.backtest_parser import parse_backtest
        from tools.schemas import BacktestParseRequest

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

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
