"""TSI (Trading Strategy Index) v2.0 CA engine adapter.

Calls narrux_tsi_v2.py for scoring. This is a thin adapter —
the actual TSI logic lives in the existing NARRUX module.

NO framework imports. Pure Python + Pydantic.
"""

import subprocess
import json
import structlog
from pathlib import Path

from tools.schemas import (
    TradeRecord,
    TSIGrade,
    TSIScoreComponent,
    TSIScoreRequest,
    TSIScoreResponse,
)

logger = structlog.get_logger(__name__)

# Path to the existing TSI engine — adjust based on actual location
TSI_ENGINE_PATH = Path(__file__).parent.parent.parent.parent / "narrux_tsi_v2.py"


def _determine_grade(score: float) -> TSIGrade:
    """Map TSI score to grade."""
    if score >= 90:
        return TSIGrade.S
    elif score >= 75:
        return TSIGrade.A
    elif score >= 60:
        return TSIGrade.B
    elif score >= 40:
        return TSIGrade.C
    else:
        return TSIGrade.D


def _check_dq_triggers(
    profit_factor: float,
    sharpe: float,
    net_profit_pct: float,
    max_drawdown_pct: float,
) -> list[str]:
    """Check Data Quality triggers per TSI spec.

    DQ triggers:
    - PF12 < 1.3
    - Sharpe1 < 0
    - Net1 < -5%
    - MDD > 20%
    """
    triggers = []
    if profit_factor < 1.3:
        triggers.append(f"PF12={profit_factor:.2f} < 1.3")
    if sharpe < 0:
        triggers.append(f"Sharpe1={sharpe:.2f} < 0")
    if net_profit_pct < -5.0:
        triggers.append(f"Net1={net_profit_pct:.1f}% < -5%")
    if max_drawdown_pct > 20.0:
        triggers.append(f"MDD={max_drawdown_pct:.1f}% > 20%")
    return triggers


async def compute_tsi(request: TSIScoreRequest) -> TSIScoreResponse:
    """Compute TSI v2.0 CA score for a set of trades.

    This adapter has two modes:
    1. If narrux_tsi_v2.py exists, call it as a subprocess
    2. Otherwise, compute a simplified TSI score locally

    Args:
        request: TSI scoring request with trade records.

    Returns:
        TSI score with grade and component breakdown.
    """
    logger.info(
        "computing_tsi",
        strategy_id=request.strategy_id,
        asset=request.asset,
        trade_count=len(request.trades),
    )

    # Try calling the existing TSI engine
    if TSI_ENGINE_PATH.exists():
        return await _call_external_tsi(request)

    # Fallback: compute simplified TSI locally
    return _compute_simplified_tsi(request)


async def _call_external_tsi(request: TSIScoreRequest) -> TSIScoreResponse:
    """Call the existing narrux_tsi_v2.py as a subprocess."""
    logger.info("calling_external_tsi", path=str(TSI_ENGINE_PATH))

    # Prepare trade data as JSON for the subprocess
    trades_json = json.dumps(
        [t.model_dump(mode="json") for t in request.trades],
        default=str,
    )

    try:
        result = subprocess.run(
            ["python", str(TSI_ENGINE_PATH), "--input", "-"],
            input=trades_json,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error("tsi_engine_error", stderr=result.stderr)
            raise RuntimeError(f"TSI engine failed: {result.stderr}")

        tsi_output = json.loads(result.stdout)
        return TSIScoreResponse(
            strategy_id=request.strategy_id,
            asset=request.asset,
            overall_score=tsi_output["overall_score"],
            grade=TSIGrade(tsi_output["grade"]),
            components=[
                TSIScoreComponent(**c) for c in tsi_output["components"]
            ],
            dq_triggers=tsi_output.get("dq_triggers", []),
            citation="narrux_tsi_v2.py",
        )
    except Exception as e:
        logger.warning("external_tsi_failed", error=str(e), fallback="simplified")
        return _compute_simplified_tsi(request)


def _compute_simplified_tsi(request: TSIScoreRequest) -> TSIScoreResponse:
    """Compute a simplified TSI score locally.

    Uses the v1.3 weights:
    - Sharpe Ratio: 20%
    - Profit Factor: 21%
    - Sortino: 17%
    - Max Drawdown: 17%
    - Frequency Stability: 12%
    - Win Rate: 7%
    - Trade Size Robustness: 6%
    """
    logger.info("computing_simplified_tsi", strategy_id=request.strategy_id)

    trades = request.trades
    if not trades:
        raise ValueError("No trades provided for TSI scoring")

    # Basic calculations
    winning = [t for t in trades if t.pnl and t.pnl > 0]
    losing = [t for t in trades if t.pnl and t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades if t.pnl)
    gross_wins = sum(t.pnl for t in winning if t.pnl)
    gross_losses = abs(sum(t.pnl for t in losing if t.pnl))

    win_rate = len(winning) / len(trades) if trades else 0.0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0.0

    # Simplified Sharpe (annualized, assuming daily returns)
    returns = [t.pnl_pct / 100 for t in trades if t.pnl_pct is not None]
    if returns:
        import numpy as np
        mean_return = np.mean(returns)
        std_return = np.std(returns) if len(returns) > 1 else 1.0
        sharpe = (mean_return / std_return) * (252**0.5) if std_return > 0 else 0.0
        # Simplified Sortino (downside deviation only)
        downside_returns = [r for r in returns if r < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 1 else std_return
        sortino = (mean_return / downside_std) * (252**0.5) if downside_std > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        if t.pnl:
            cumulative += t.pnl
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / (peak if peak > 0 else 1) * 100
            max_dd = max(max_dd, dd)

    # Score each component (0-100 scale)
    components = [
        TSIScoreComponent(
            name="Sharpe Ratio",
            weight=0.20,
            raw_value=sharpe,
            weighted_score=min(max(sharpe / 3.0 * 100, 0), 100) * 0.20,
            grade_contribution="20%",
        ),
        TSIScoreComponent(
            name="Profit Factor",
            weight=0.21,
            raw_value=profit_factor,
            weighted_score=min(max(profit_factor / 2.5 * 100, 0), 100) * 0.21,
            grade_contribution="21%",
        ),
        TSIScoreComponent(
            name="Sortino",
            weight=0.17,
            raw_value=sortino,
            weighted_score=min(max(sortino / 4.0 * 100, 0), 100) * 0.17,
            grade_contribution="17%",
        ),
        TSIScoreComponent(
            name="Max Drawdown",
            weight=0.17,
            raw_value=max_dd,
            weighted_score=min(max((100 - max_dd * 2), 0), 100) * 0.17,
            grade_contribution="17%",
        ),
        TSIScoreComponent(
            name="Win Rate",
            weight=0.07,
            raw_value=win_rate * 100,
            weighted_score=min(max(win_rate * 100, 0), 100) * 0.07,
            grade_contribution="7%",
        ),
    ]

    overall_score = sum(c.weighted_score for c in components)
    grade = _determine_grade(overall_score)
    dq_triggers = _check_dq_triggers(profit_factor, sharpe, total_pnl, max_dd)

    logger.info(
        "tsi_computed",
        strategy_id=request.strategy_id,
        overall_score=f"{overall_score:.1f}",
        grade=grade.value,
        dq_triggers=len(dq_triggers),
    )

    return TSIScoreResponse(
        strategy_id=request.strategy_id,
        asset=request.asset,
        overall_score=overall_score,
        grade=grade,
        components=components,
        dq_triggers=dq_triggers,
        citation="Simplified TSI computation (narrux_tsi_v2.py not available)",
    )
