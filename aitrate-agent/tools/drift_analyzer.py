"""Exit drift analysis — Bar Magnifier exit quality estimation from backtest data.

PRD: docs/Strategy Docs - converted/backtest/NARRUX_Backtest_Analysis_Approach_v1.0.md §3.3

With backtest-only data (no live comparison), we estimate exit quality using
MFE/MAE proxies. Exits where profit was available but not captured indicate
potential Bar Magnifier drift.

NO pydantic_ai imports. Pure Python + Pydantic.
"""

from __future__ import annotations

import structlog

from tools.schemas import DriftAnalysisResult, ExitQualityFlag

logger = structlog.get_logger(__name__)

# Bar Magnifier baseline drift per exit (from PRD §3.3)
BASELINE_DRIFT_PCT = 0.19


def _mfe_capture_pct(net_pnl: float, mfe: float) -> float:
    """What percentage of the maximum favorable excursion was captured.

    MFE = peak unrealized profit during the trade.
    Only meaningful for winners — returns 0 for losers.
    """
    if mfe <= 0 or net_pnl <= 0:
        return 0.0
    return (net_pnl / mfe) * 100.0


def _classify_exit_issue(
    net_pnl: float,
    mfe: float,
    mae: float,
    mfe_capture: float,
) -> str | None:
    """Classify why an exit was suboptimal.

    Returns:
        "low_capture" — winner that captured <25% of MFE (exited too early or late)
        "reversal" — loser that had MFE > |loss| (profit available, then reversed)
        "wide_stop" — loser where MAE was large relative to loss (stop too wide)
        None — exit looks fine
    """
    if net_pnl > 0 and mfe > 0 and mfe_capture < 25.0:
        return "low_capture"

    if net_pnl < 0 and mfe > 0 and mfe > abs(net_pnl):
        return "reversal"

    if net_pnl < 0 and mae < 0:
        # MAE is negative (adverse), check if stop was hit near max adverse
        mae_abs = abs(mae)
        loss_abs = abs(net_pnl)
        if mae_abs > 0 and loss_abs / mae_abs > 0.8:
            return "wide_stop"

    return None


def analyze_exit_drift(
    raw_trades: list,
    logical_trades: list | None = None,
) -> DriftAnalysisResult:
    """Analyze exit quality and estimate Bar Magnifier drift.

    Uses MFE/MAE data from the backtest to estimate exit quality.
    Exits where |P&L| < 25% of MFE indicate the strategy left money on the table.

    Args:
        raw_trades: RawTrade objects with net_pnl, net_pnl_pct.
            If the trades have runup_usdt/drawdown_usdt fields, those are used as MFE/MAE.
        logical_trades: Optional LogicalTrade objects (aggregated). Used for
            total exit count if provided.

    Returns:
        DriftAnalysisResult with exit quality metrics and drift estimate.
    """
    logger.info("drift_analysis_start", trades=len(raw_trades))

    if not raw_trades:
        return DriftAnalysisResult(
            avg_exit_quality=0.0,
            worst_exits=[],
            exits_flagged=0,
            total_exits=0,
            drift_estimate_pct=0.0,
            baseline_pct=BASELINE_DRIFT_PCT,
            above_baseline=False,
        )

    exit_flags: list[ExitQualityFlag] = []
    mfe_captures: list[float] = []  # Only for winners

    for i, trade in enumerate(raw_trades):
        # Extract MFE/MAE — handle both RawTrade and dict-like access
        mfe = getattr(trade, "runup_usdt", None) or getattr(trade, "mfe", 0.0)
        mae = getattr(trade, "drawdown_usdt", None) or getattr(trade, "mae", 0.0)
        net_pnl = trade.net_pnl if hasattr(trade, "net_pnl") else trade.get("net_pnl", 0)
        close_time = trade.close_time if hasattr(trade, "close_time") else trade.get("close_time")
        side = trade.side if hasattr(trade, "side") else trade.get("side", "long")

        # Ensure MFE is non-negative, MAE is non-positive
        mfe = max(0.0, float(mfe)) if mfe else 0.0
        mae = min(0.0, float(mae)) if mae else 0.0

        mfe_cap = _mfe_capture_pct(net_pnl, mfe)
        # Only include winners in exit quality average — losers are classified by issue type
        if net_pnl > 0 and mfe > 0:
            mfe_captures.append(mfe_cap)

        issue = _classify_exit_issue(net_pnl, mfe, mae, mfe_cap)

        if issue:
            exit_flags.append(
                ExitQualityFlag(
                    trade_index=i,
                    close_time=close_time,
                    side=side,
                    net_pnl=round(net_pnl, 2),
                    mfe=round(mfe, 2),
                    mae=round(mae, 2),
                    mfe_capture_pct=round(mfe_cap, 2),
                    issue=issue,
                )
            )

    # Average exit quality (MFE capture %)
    avg_quality = sum(mfe_captures) / len(mfe_captures) if mfe_captures else 0.0

    # Sort worst exits by MFE capture (lowest first) and take top 10
    exit_flags.sort(key=lambda f: f.mfe_capture_pct)
    worst_exits = exit_flags[:10]

    # Drift estimate: exits flagged / total exits × baseline
    total_exits = len(logical_trades) if logical_trades else len(raw_trades)
    flag_rate = len(exit_flags) / max(1, total_exits)
    drift_estimate = flag_rate * BASELINE_DRIFT_PCT * 2  # conservative multiplier

    result = DriftAnalysisResult(
        avg_exit_quality=round(avg_quality, 2),
        worst_exits=worst_exits,
        exits_flagged=len(exit_flags),
        total_exits=total_exits,
        drift_estimate_pct=round(drift_estimate, 4),
        baseline_pct=BASELINE_DRIFT_PCT,
        above_baseline=drift_estimate > BASELINE_DRIFT_PCT,
    )

    logger.info(
        "drift_analysis_complete",
        avg_quality=round(avg_quality, 2),
        flagged=len(exit_flags),
        total=total_exits,
        drift_estimate=round(drift_estimate, 4),
    )

    return result
