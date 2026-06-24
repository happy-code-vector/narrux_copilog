"""Robustness analysis — DSR, worst-window, fragile-trade, TSI vs P&L cross-check.

PRD: docs/Strategy Docs - converted/backtest/NARRUX_Backtest_Analysis_Approach_v1.0.md §4.3, §4.5, §5.1, §5.2

NO pydantic_ai imports. Pure Python + Pydantic.
"""

from __future__ import annotations

import math
from datetime import timedelta

import structlog

from tools.schemas import (
    FragileTradeResult,
    PeriodMetrics,
    RobustnessResult,
    TSIPnLCrossCheck,
    WorstWindowResult,
)

logger = structlog.get_logger(__name__)


# ─── §5.1 — Deflated Sharpe Ratio ──────────────────────────────────────────


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (percent-point function) approximation.

    Rational approximation for 0 < p < 1. Accurate to ~4.5e-4.
    Avoids scipy dependency.
    """
    if p <= 0 or p >= 1:
        return 0.0

    # For extreme tails, clamp
    if p < 1e-10:
        return -6.36
    if p > 1 - 1e-10:
        return 6.36

    # Abramowitz & Stegun approximation 26.2.23
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))

    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308

    result = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)

    return result if p >= 0.5 else -result


def compute_dsr(
    sharpe_ann: float,
    n_trades: int,
    n_trials: int = 1,
    annualization_factor: float = 252.0,
) -> tuple[float, float]:
    """Deflated Sharpe Ratio per §5.1.

    Adjusts raw Sharpe for multiple-testing bias.
    When n_trials=1, DSR ≈ raw Sharpe (no deflation).

    Args:
        sharpe_ann: Annualized Sharpe ratio.
        n_trades: Number of trades in the sample.
        n_trials: Number of configurations tried (default 1).
        annualization_factor: Trading days per year (default 252).

    Returns:
        (dsr, inflation_pct) where inflation_pct = how much raw Sharpe
        was inflated by multiple-testing.
    """
    if n_trades < 2 or n_trials < 1:
        return 0.0, 0.0

    # Standard error of Sharpe
    # Var(SR) ≈ (1 + 0.5 * SR²) / n
    # For annualized: divide by sqrt(annualization_factor)
    sr = sharpe_ann
    var_sr = (1.0 + 0.5 * sr * sr) / n_trades
    se_sr = math.sqrt(var_sr)

    # DSR = SR - SE(SR) × Φ⁻¹(1 - α/N)
    # where α = 0.05 (95% confidence), N = n_trials
    alpha = 0.05
    p = 1.0 - alpha / n_trials
    z = _norm_ppf(p)

    dsr = sr - se_sr * z

    # Inflation: how much of the raw Sharpe is explained by multiple-testing
    if abs(sr) > 1e-10:
        inflation_pct = ((sr - dsr) / abs(sr)) * 100.0
    else:
        inflation_pct = 0.0

    return round(dsr, 4), round(inflation_pct, 2)


# ─── §5.2 — Worst-Window Robustness ────────────────────────────────────────


def _compute_window_composite(
    trades: list,
    capital_basis: float,
    period_weights: dict[str, float] | None = None,
) -> float:
    """Compute a simplified TSI composite for a subset of trades.

    Uses the same component scoring as tsi_engine.py but on a single window.
    Returns composite score 0-100.
    """
    from tools.tsi_engine import (
        compute_period_metrics,
        score_sharpe,
        score_sortino,
        score_pf,
        score_mdd,
        score_wr,
        score_freq_v2,
        score_trade_size,
        COMP_WEIGHTS,
    )

    n = len(trades)
    if n < 3:
        return 0.0

    # Compute metrics for this window as a single period
    # Use a synthetic period name
    pnls_pct = [t.net_pnl_pct for t in trades]
    mean_pnl = sum(pnls_pct) / n

    # Win rate
    wins = [t for t in trades if t.net_pnl > 0]
    win_rate = len(wins) / n

    # Profit factor
    gross_profit = sum(t.net_pnl for t in wins) if wins else 0
    losses = [t for t in trades if t.net_pnl <= 0]
    gross_loss = abs(sum(t.net_pnl for t in losses)) if losses else 1e-10
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    # Sharpe (annualized from window trades)
    if n > 1:
        variance = sum((p - mean_pnl) ** 2 for p in pnls_pct) / (n - 1)
        std_pnl = math.sqrt(variance) if variance > 0 else 1e-10
        # Approximate tpy from window
        days_span = max(1, (trades[-1].close_time - trades[0].close_time).days)
        tpd = n / days_span
        tpy = tpd * 365
        sharpe_ann = (mean_pnl / std_pnl) * math.sqrt(tpy) if std_pnl > 0 else 0
    else:
        sharpe_ann = 0.0

    # Sortino
    downside = [p for p in pnls_pct if p < 0]
    if len(downside) > 1:
        down_var = sum(p ** 2 for p in downside) / len(downside)
        down_std = math.sqrt(down_var)
        sortino_ann = (mean_pnl / down_std) * math.sqrt(tpy) if down_std > 0 else 0
    else:
        sortino_ann = sharpe_ann * 2 if sharpe_ann > 0 else 0

    # MDD
    equity = capital_basis
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity += t.net_pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    mdd_pct = max_dd * 100

    # Component scores
    s_sharpe = score_sharpe(sharpe_ann)
    s_sortino = score_sortino(sortino_ann)
    s_pf = score_pf(pf)
    s_mdd = score_mdd(mdd_pct)
    s_wr = score_wr(win_rate * 100)
    s_freq = score_freq_v2(1.0, 0.0)  # no baseline in window
    s_trade_size = score_trade_size(pnls_pct)

    composite = (
        s_sharpe * COMP_WEIGHTS["sharpe"]
        + s_sortino * COMP_WEIGHTS["sortino"]
        + s_pf * COMP_WEIGHTS["pf"]
        + s_mdd * COMP_WEIGHTS["mdd"]
        + s_wr * COMP_WEIGHTS["wr"]
        + s_freq * COMP_WEIGHTS["freq"]
        + s_trade_size * COMP_WEIGHTS["trade_size"]
    )

    return round(composite, 2)


def analyze_worst_window(
    trades: list,
    capital_basis: float,
    full_sample_composite: float,
    window_size: int = 30,
    step: int = 5,
) -> WorstWindowResult:
    """Slide a window across trades and find the worst TSI composite.

    §5.2: A strategy whose edge collapses in its worst window is fragile
    even with a strong full-sample TSI.
    """
    n = len(trades)
    if n < window_size:
        # Not enough trades — use all trades as one window
        composite = _compute_window_composite(trades, capital_basis)
        return WorstWindowResult(
            window_size=n,
            worst_composite=composite,
            worst_period_start=trades[0].close_time if trades else None,
            worst_period_end=trades[-1].close_time if trades else None,
            full_sample_composite=full_sample_composite,
            drop_points=round(full_sample_composite - composite, 2),
            n_windows_tested=1,
        )

    worst_composite = float("inf")
    worst_start = None
    worst_end = None
    n_windows = 0

    for i in range(0, n - window_size + 1, step):
        window = trades[i : i + window_size]
        composite = _compute_window_composite(window, capital_basis)
        n_windows += 1

        if composite < worst_composite:
            worst_composite = composite
            worst_start = window[0].close_time
            worst_end = window[-1].close_time

    return WorstWindowResult(
        window_size=window_size,
        worst_composite=round(worst_composite, 2),
        worst_period_start=worst_start,
        worst_period_end=worst_end,
        full_sample_composite=full_sample_composite,
        drop_points=round(full_sample_composite - worst_composite, 2),
        n_windows_tested=n_windows,
    )


# ─── §4.5 — Fragile-Trade Dependency ───────────────────────────────────────


def analyze_fragile_trades(
    trades: list,
    capital_basis: float,
    full_tsi: float,
    k_values: list[int] | None = None,
) -> list[FragileTradeResult]:
    """Leave-K-out analysis: remove top-K trades by |P&L|, recompute TSI.

    §4.5: If TSI drops >10 points when removing 1-2 trades → fragile.
    """
    from tools.tsi_engine import tsi_score, aggregate_logical, partition_windows

    if k_values is None:
        k_values = [1, 2, 3]

    results: list[FragileTradeResult] = []

    # Sort trades by |P&L| descending to find the most impactful
    sorted_by_impact = sorted(trades, key=lambda t: abs(t.net_pnl), reverse=True)

    for k in k_values:
        if k >= len(trades):
            continue

        # Remove top-K most impactful trades
        removed = sorted_by_impact[:k]
        remaining = [t for t in trades if t not in removed]

        # Recompute TSI on remaining trades
        # We need to convert back to RawTrade-like objects for tsi_score
        # Since we have LogicalTrade objects, compute composite directly
        composite = _compute_window_composite(remaining, capital_basis)

        tsi_drop = round(full_tsi - composite, 2)
        fragile = tsi_drop > 10.0

        results.append(
            FragileTradeResult(
                k=k,
                removed_pnl=[round(t.net_pnl, 2) for t in removed],
                tsi_without=round(composite, 2),
                tsi_full=round(full_tsi, 2),
                tsi_drop=tsi_drop,
                fragile=fragile,
            )
        )

    return results


# ─── §4.3 — TSI vs P&L Cross-Check ────────────────────────────────────────


def check_tsi_pnl_alignment(
    period_metrics: list[PeriodMetrics],
) -> TSIPnLCrossCheck:
    """Check if TSI composite trend aligns with P&L trend.

    §4.3: TSI up + P&L flat = re-adjustment artifact.
    """
    if len(period_metrics) < 2:
        return TSIPnLCrossCheck(
            aligned=True,
            tsi_trend="flat",
            pnl_trend="flat",
            artifact_flag=False,
            note="Insufficient periods for trend analysis.",
        )

    # Sort by period order (12mo → 7d)
    period_order = {"12mo": 0, "6mo": 1, "3mo": 2, "1mo": 3, "7d": 4}
    sorted_pm = sorted(
        [pm for pm in period_metrics if pm.n > 0],
        key=lambda pm: period_order.get(pm.period, 99),
    )

    if len(sorted_pm) < 2:
        return TSIPnLCrossCheck(
            aligned=True,
            tsi_trend="flat",
            pnl_trend="flat",
            artifact_flag=False,
            note="Insufficient periods with trades.",
        )

    # TSI trend: compare 12mo composite vs 1mo composite
    c12 = sorted_pm[0].composite
    c_recent = sorted_pm[-1].composite
    tsi_diff = c_recent - c12

    if tsi_diff > 3:
        tsi_trend = "rising"
    elif tsi_diff < -3:
        tsi_trend = "falling"
    else:
        tsi_trend = "flat"

    # P&L trend: compare win_rate and profit_factor across periods
    # Use a simple heuristic: is recent period worse than 12mo?
    wr_12 = sorted_pm[0].win_rate
    wr_recent = sorted_pm[-1].win_rate
    pf_12 = sorted_pm[0].profit_factor
    pf_recent = sorted_pm[-1].profit_factor

    pnl_improving = (wr_recent > wr_12 * 1.05) or (pf_recent > pf_12 * 1.1)
    pnl_declining = (wr_recent < wr_12 * 0.95) or (pf_recent < pf_12 * 0.9)

    if pnl_improving:
        pnl_trend = "rising"
    elif pnl_declining:
        pnl_trend = "falling"
    else:
        pnl_trend = "flat"

    # Artifact detection: TSI rising but P&L not improving
    artifact_flag = tsi_trend == "rising" and pnl_trend != "rising"
    aligned = not artifact_flag

    if artifact_flag:
        note = (
            f"TSI trend is {tsi_trend} ({c12:.1f} → {c_recent:.1f}) but P&L trend is "
            f"{pnl_trend}. This may indicate a re-adjustment artifact — parameter tweaks "
            f"that raised TSI without improving absolute returns."
        )
    else:
        note = f"TSI ({tsi_trend}) and P&L ({pnl_trend}) trends are aligned."

    return TSIPnLCrossCheck(
        aligned=aligned,
        tsi_trend=tsi_trend,
        pnl_trend=pnl_trend,
        artifact_flag=artifact_flag,
        note=note,
    )


# ─── Main Entry Point ──────────────────────────────────────────────────────


def analyze_robustness(
    trades: list,
    capital_basis: float,
    tsi_final: float,
    period_metrics: list[PeriodMetrics],
    sharpe_ann: float,
    n_trials: int = 1,
) -> RobustnessResult:
    """Run complete robustness analysis on a backtest.

    Args:
        trades: LogicalTrade objects (post-aggregation).
        capital_basis: Capital basis for MDD calculations.
        tsi_final: The full-sample TSI final score.
        period_metrics: Per-period metrics from TSIResult.
        sharpe_ann: Annualized Sharpe from 12mo period.
        n_trials: Number of configurations tried (for DSR).

    Returns:
        RobustnessResult with DSR, worst-window, fragile-trade, and cross-check.
    """
    logger.info("robustness_start", trades=len(trades), tsi_final=tsi_final)

    # §5.1 — DSR
    dsr, inflation = compute_dsr(sharpe_ann, len(trades), n_trials)

    # §5.2 — Worst-window
    worst_window = analyze_worst_window(trades, capital_basis, tsi_final)

    # §4.5 — Fragile-trade
    fragile = analyze_fragile_trades(trades, capital_basis, tsi_final)

    # §4.3 — TSI vs P&L cross-check
    crosscheck = check_tsi_pnl_alignment(period_metrics)

    # Overall robustness: no critical flags
    has_fragile = any(f.fragile for f in fragile)
    has_artifact = crosscheck.artifact_flag
    has_dsr_inflation = inflation > 50.0  # >50% inflation is concerning
    worst_drop_severe = worst_window.drop_points > 20.0

    overall = not (has_fragile or has_artifact or has_dsr_inflation or worst_drop_severe)

    result = RobustnessResult(
        raw_sharpe=round(sharpe_ann, 4),
        dsr=dsr,
        dsr_inflation_pct=inflation,
        n_trials=n_trials,
        worst_window=worst_window,
        fragile_trade=fragile,
        tsi_pnl_crosscheck=crosscheck,
        overall_robust=overall,
    )

    logger.info(
        "robustness_complete",
        dsr=dsr,
        inflation_pct=inflation,
        worst_window_drop=worst_window.drop_points,
        overall_robust=overall,
    )

    return result
