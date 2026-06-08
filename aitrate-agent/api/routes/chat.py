"""Chat endpoint — wired to orchestration/agent.py.

POST /chat — main RAG pipeline for F-01 through F-05.
POST /chat/backtest — upload xlsx → TSI + F-02 + F-03.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from tools.schemas import FunctionID

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Chat request."""

    function_id: str = "F-01"
    message: str
    user_id: str = "api-user"
    metadata_filter: dict | None = None
    adapter: str = "pydantic_ai"


class CitationResponse(BaseModel):
    """Citation in response."""

    doc_id: str
    citation_handle: str
    relevance_score: float


class ChatResponse(BaseModel):
    """Chat response."""

    response_id: str
    function_id: str
    content: str
    citations: list[CitationResponse]
    confidence: str
    validator_results: dict


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat endpoint — runs the full RAG pipeline.

    Routes to F-01 through F-05 based on function_id.
    """
    logger.info("chat_request", function_id=request.function_id, message=request.message[:100])

    try:
        fid = FunctionID(request.function_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid function_id: {request.function_id}. Must be F-01 through F-05.",
        )

    try:
        from orchestration.agent import run

        result = await run(
            function_id=fid,
            user_message=request.message,
            user_id=request.user_id,
            metadata_filter=request.metadata_filter,
            adapter=request.adapter,
        )

        return ChatResponse(
            response_id=str(result.response_id),
            function_id=result.function_id.value,
            content=result.content,
            citations=[
                CitationResponse(
                    doc_id=c.doc_id,
                    citation_handle=c.citation_handle,
                    relevance_score=c.relevance_score,
                )
                for c in result.citations
            ],
            confidence=result.confidence.value,
            validator_results=result.validator_results,
        )

    except Exception as e:
        logger.error("chat_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/backtest")
async def chat_backtest(
    file: UploadFile = File(...),
    strategy_id: str = Form("unknown"),
    asset: str = Form("unknown"),
    capital_basis: float = Form(100000.0),
):
    """Upload a backtest xlsx → parse → TSI score → F-02 + F-03 responses."""
    import tempfile
    from pathlib import Path
    from tools.backtest_parser import parse_backtest_xlsx
    from tools.tsi_engine import tsi_score

    logger.info("backtest_upload", filename=file.filename, strategy_id=strategy_id)

    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Parse xlsx
        raw_trades, summary = parse_backtest_xlsx(
            tmp_path, capital_basis=capital_basis,
            strategy_id=strategy_id, asset=asset,
        )

        # Compute TSI
        tsi_result = tsi_score(
            raw_trades, capital_basis=capital_basis,
            strategy_id=strategy_id, asset=asset,
        )

        # Cleanup
        tmp_path.unlink(missing_ok=True)

        return {
            "summary": {
                "total_trades": summary.total_trades,
                "win_rate": summary.win_rate,
                "profit_factor": summary.profit_factor,
                "net_pnl": summary.net_pnl,
                "max_drawdown_pct": summary.max_drawdown_pct,
                "stop_loss_ratio": summary.stop_loss_ratio,
            },
            "tsi": {
                "final_tsi": tsi_result.final_tsi,
                "grade": tsi_result.grade.value,
                "leverage_cap": tsi_result.leverage_cap,
                "stability": tsi_result.stability,
                "catastrophic_floor": tsi_result.catastrophic_floor,
                "dq_triggers": tsi_result.dq_triggers,
                "period_metrics": [
                    {
                        "period": pm.period,
                        "n": pm.n,
                        "win_rate": pm.win_rate,
                        "profit_factor": pm.profit_factor,
                        "mdd_pct": pm.mdd_pct,
                        "composite": pm.composite,
                        "insufficient_sample": pm.insufficient_sample,
                    }
                    for pm in tsi_result.period_metrics
                ],
            },
            "trades_parsed": len(raw_trades),
        }

    except Exception as e:
        logger.error("backtest_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
