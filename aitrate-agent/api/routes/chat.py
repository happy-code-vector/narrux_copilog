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
    adapter: str = "gemini"


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

        # Compute robustness analysis
        from tools.tsi_engine import aggregate_logical
        from tools.robustness_engine import analyze_robustness
        from tools.drift_analyzer import analyze_exit_drift

        logical_trades = aggregate_logical(raw_trades)

        # Get 12mo Sharpe for DSR
        sharpe_12mo = 0.0
        for pm in tsi_result.period_metrics:
            if pm.period == "12mo":
                sharpe_12mo = pm.sharpe_ann
                break

        robustness = analyze_robustness(
            trades=logical_trades,
            capital_basis=capital_basis,
            tsi_final=tsi_result.final_tsi,
            period_metrics=tsi_result.period_metrics,
            sharpe_ann=sharpe_12mo,
        )

        drift = analyze_exit_drift(raw_trades, logical_trades)

        # Cleanup
        tmp_path.unlink(missing_ok=True)

        return {
            "summary": {
                "total_trades": summary.total_trades,
                "win_rate": summary.win_rate,
                "profit_factor": summary.profit_factor,
                "net_pnl": summary.net_pnl,
                "net_pnl_pct": summary.net_pnl_pct,
                "max_drawdown_pct": summary.max_drawdown_pct,
                "sharpe_ratio": summary.sharpe_ratio,
                "stop_loss_count": summary.stop_loss_count,
                "stop_loss_ratio": summary.stop_loss_ratio,
                "capital_basis": summary.capital_basis,
                "calc_on_order_fills": summary.calc_on_order_fills,
                "process_orders_on_close": summary.process_orders_on_close,
                "execution_mode": summary.execution_mode,
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
            "robustness": {
                "raw_sharpe": robustness.raw_sharpe,
                "dsr": robustness.dsr,
                "dsr_inflation_pct": robustness.dsr_inflation_pct,
                "n_trials": robustness.n_trials,
                "overall_robust": robustness.overall_robust,
                "worst_window": {
                    "window_size": robustness.worst_window.window_size,
                    "worst_composite": robustness.worst_window.worst_composite,
                    "worst_period_start": str(robustness.worst_window.worst_period_start),
                    "worst_period_end": str(robustness.worst_window.worst_period_end),
                    "full_sample_composite": robustness.worst_window.full_sample_composite,
                    "drop_points": robustness.worst_window.drop_points,
                    "n_windows_tested": robustness.worst_window.n_windows_tested,
                },
                "fragile_trade": [
                    {
                        "k": f.k,
                        "removed_pnl": f.removed_pnl,
                        "tsi_without": f.tsi_without,
                        "tsi_full": f.tsi_full,
                        "tsi_drop": f.tsi_drop,
                        "fragile": f.fragile,
                    }
                    for f in robustness.fragile_trade
                ],
                "tsi_pnl_crosscheck": {
                    "aligned": robustness.tsi_pnl_crosscheck.aligned,
                    "tsi_trend": robustness.tsi_pnl_crosscheck.tsi_trend,
                    "pnl_trend": robustness.tsi_pnl_crosscheck.pnl_trend,
                    "artifact_flag": robustness.tsi_pnl_crosscheck.artifact_flag,
                    "note": robustness.tsi_pnl_crosscheck.note,
                },
            },
            "drift": {
                "avg_exit_quality": drift.avg_exit_quality,
                "exits_flagged": drift.exits_flagged,
                "total_exits": drift.total_exits,
                "drift_estimate_pct": drift.drift_estimate_pct,
                "baseline_pct": drift.baseline_pct,
                "above_baseline": drift.above_baseline,
                "worst_exits": [
                    {
                        "trade_index": we.trade_index,
                        "close_time": str(we.close_time),
                        "side": we.side,
                        "net_pnl": we.net_pnl,
                        "mfe": we.mfe,
                        "mae": we.mae,
                        "mfe_capture_pct": we.mfe_capture_pct,
                        "issue": we.issue,
                    }
                    for we in drift.worst_exits[:5]  # Top 5 worst exits
                ],
            },
            "trades_parsed": len(raw_trades),
        }

    except Exception as e:
        logger.error("backtest_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/portfolio")
async def chat_portfolio(
    files: list[UploadFile] = File(...),
    capital_basis: float = Form(100000.0),
):
    """Upload multiple backtest xlsx files → portfolio correlation analysis.

    Returns pairwise correlation matrix, diversification ratio, and kill zone check.
    """
    import tempfile
    from pathlib import Path
    from tools.backtest_parser import parse_backtest_xlsx
    from tools.tsi_engine import aggregate_logical
    from tools.portfolio_metrics import compute_portfolio_metrics

    if len(files) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 backtest files required for portfolio analysis.",
        )

    logger.info("portfolio_upload", file_count=len(files))

    try:
        strategy_pnl: dict[str, list[float]] = {}
        strategy_capital: dict[str, float] = {}
        tmp_paths: list[Path] = []

        for file in files:
            if not file.filename or not file.filename.endswith(".xlsx"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Only .xlsx files supported. Got: {file.filename}",
                )

            # Extract strategy name from filename
            strategy_id = file.filename.replace(".xlsx", "").replace("_backtest", "")

            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = Path(tmp.name)
                tmp_paths.append(tmp_path)

            # Parse
            raw_trades, summary = parse_backtest_xlsx(
                tmp_path, capital_basis=capital_basis,
                strategy_id=strategy_id, asset="unknown",
            )

            # Aggregate to logical trades for daily P&L
            logical = aggregate_logical(raw_trades)

            # Build daily P&L series
            from datetime import date
            daily: dict[date, float] = {}
            for t in logical:
                d = t.close_time.date()
                daily[d] = daily.get(d, 0.0) + t.net_pnl

            strategy_pnl[strategy_id] = list(daily.values())
            strategy_capital[strategy_id] = capital_basis

        # Cleanup temp files
        for p in tmp_paths:
            p.unlink(missing_ok=True)

        # Compute portfolio metrics
        result = compute_portfolio_metrics(strategy_pnl, strategy_capital)

        return {
            "strategies": result.strategies,
            "correlation_matrix": result.correlation_matrix,
            "avg_pairwise_rho": result.avg_pairwise_rho,
            "min_pairwise_rho": result.min_pairwise_rho,
            "max_pairwise_rho": result.max_pairwise_rho,
            "diversification_ratio": result.diversification_ratio,
            "kill_zone_active": result.kill_zone_active,
            "triggering_pairs": result.triggering_pairs,
            "n_strategies": result.n_strategies,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("portfolio_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class InterpretRequest(BaseModel):
    """Request for LLM interpretation of backtest results."""

    tool_results: dict  # Full output from POST /chat/backtest
    strategy_id: str = "unknown"
    version: str | None = None  # e.g. "v15.8" — parsed from filename
    asset: str = "unknown"
    adapter: str = "gemini"


@router.post("/chat/backtest/interpret")
async def interpret_backtest(request: InterpretRequest):
    """Run LLM interpretation on backtest tool outputs.

    Takes the JSON output from POST /chat/backtest, adds strategy context
    from registry.db, and calls the LLM with the F-02 prompt to produce
    an interpretive narrative with improvement suggestions.
    """
    from orchestration.agent import run, _build_full_prompt
    from orchestration.llm_client import LLMRequest, get_llm_client
    from tools.kb_lookup import (
        query_params_by_class,
        query_params_by_category,
        get_governance_rules,
        get_filter_class_defs,
    )
    from tools.schemas import FunctionID

    logger.info("interpret_backtest", strategy_id=request.strategy_id)

    try:
        # Build strategy context from registry.db using existing kb_lookup functions
        strategy = request.strategy_id.lower()
        version = request.version  # e.g. "v15.8" or None for latest
        strategy_context = {}
        try:
            class_a = query_params_by_class("A", strategy=strategy, version=version)
            class_b = query_params_by_class("B", strategy=strategy, version=version)
            class_c = query_params_by_class("C", strategy=strategy, version=version)

            # If version was specified but returned 0 results, fall back to latest
            if version and len(class_a) == 0 and len(class_b) == 0 and len(class_c) == 0:
                logger.info("version_not_found_falling_back", strategy=strategy, version=version)
                version = None
                class_a = query_params_by_class("A", strategy=strategy)
                class_b = query_params_by_class("B", strategy=strategy)
                class_c = query_params_by_class("C", strategy=strategy)

            exit_params = query_params_by_category("Exit logic", strategy=strategy) + \
                         query_params_by_category("Exit / Stop", strategy=strategy)
            sizing_params = query_params_by_category("Capital & Sizing", strategy=strategy)

            strategy_context = {
                "strategy": strategy,
                "version": version or "latest",
                "parameter_count": len(class_a) + len(class_b) + len(class_c),
                "parameters_by_class": {
                    "A": class_a,
                    "B": class_b,
                    "C": class_c,
                },
                "governance": {
                    "governance_rules": get_governance_rules(),
                    "filter_classes": get_filter_class_defs(),
                },
                "exit_params": exit_params,
                "sizing_params": sizing_params,
            }
            logger.info(
                "strategy_context_built",
                strategy=strategy,
                version=version,
                class_a=len(class_a),
                class_b=len(class_b),
                class_c=len(class_c),
                exit_params=len(exit_params),
                sizing_params=len(sizing_params),
            )
        except Exception as e:
            logger.warning("strategy_context_failed", error=str(e), exc_info=True)
            # Continue without strategy context — LLM can still interpret tool outputs

        # Merge tool results + strategy context into structured_input
        structured_input = {
            **request.tool_results,
            "strategy_context": strategy_context,
        }

        # Build the full prompt (system + F-02 function prompt + structured input)
        full_prompt = _build_full_prompt(
            FunctionID.F02,
            f"Interpret this backtest for {request.strategy_id} ({request.asset})",
            structured_input,
        )

        # Call LLM directly (no RAG retrieval needed — all data is in structured_input)
        from config import get_settings
        settings = get_settings()

        llm_client = get_llm_client(request.adapter)
        model = settings.gemini_model_primary if request.adapter == "gemini" else settings.anthropic_model_primary

        llm_request = LLMRequest(
            system_prompt=full_prompt,
            user_message=f"Interpret this backtest for {request.strategy_id} ({request.asset}). "
                         f"Produce a full interpretive report with improvement suggestions.",
            context_chunks=[],  # No RAG — all context is in structured_input
            model=model,
            max_tokens=settings.max_tokens_per_response,
        )

        llm_response = await llm_client.complete(llm_request)

        return {
            "interpretation": llm_response.content,
            "model": llm_response.model,
            "input_tokens": llm_response.input_tokens,
            "output_tokens": llm_response.output_tokens,
            "cost_usd": llm_response.cost_usd,
        }

    except Exception as e:
        logger.error("interpret_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
