"""TSI v2.0 CA scoring engine — full implementation per spec §3–§15.

Implements from spec directly. No external dependency.
Wraps narrux_tsi_v2.py when available for validation.

NO pydantic_ai imports. Pure Python + Pydantic.

Key sections:
§3  — Logical Trade Aggregation (CRITICAL — most common bug)
§4  — Window partitioning
§5  — Minimum trade count (N < 5 rule)
§6  — Per-period metrics
§7  — MDD continuous equity model (CRITICAL — second most common bug)
§9  — Component scoring functions (piecewise)
§10 — FreqStab asymmetric v2
§12 — Stability
§13 — Catastrophic Floor
§14 — Final score
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog

from tools.schemas import PeriodMetrics, RawTrade, TSIResult, TSIGrade

logger = structlog.get_logger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

PERIOD_DAYS = {"12mo": 365, "6mo": 182, "3mo": 91, "1mo": 30, "7d": 7}
PERIOD_WEIGHTS = {"12mo": 0.19, "6mo": 0.24, "3mo": 0.29, "1mo": 0.23, "7d": 0.05}
PERIOD_ORDER = ["12mo", "6mo", "3mo", "1mo", "7d"]
MIN_N_FOR_INCLUSION = 5

# Component weights (must sum to 1.00)
COMP_WEIGHTS = {
    "sharpe": 0.20,
    "sortino": 0.17,
    "pf": 0.21,
    "mdd": 0.17,
    "wr": 0.07,
    "freq": 0.12,
    "trade_size": 0.06,
}

# Tier thresholds
TIER_THRESHOLDS = {"S": 85, "A": 70, "B": 55, "C": 40, "D": 0}


# ─── §3 — Logical Trade Aggregation ─────────────────────────────────────────


@dataclass
class LogicalTrade:
    """Aggregated logical trade from partial fills."""

    open_time: datetime
    close_time: datetime
    side: str  # "long" | "short"
    net_pnl: float
    net_pnl_pct: float
    partial_count: int = 1


def aggregate_logical(raw_trades: list[RawTrade]) -> list[LogicalTrade]:
    """Group partial fills by (open_time, side).

    A Partial TP strategy generates 3–4 rows per position.
    Counting each as a trade inflates WR by ~13pp and drags Tier A to Tier D.

    Aggregation key: (open_time, side) — NOT close_time
    LogicalTrade.close_time = last partial's close_time
    LogicalTrade.net_pnl = sum of all partials
    LogicalTrade.net_pnl_pct = sum of all partials
    """
    if not raw_trades:
        return []

    # Group by (open_time, side)
    groups: dict[tuple[datetime, str], list[RawTrade]] = {}
    for trade in raw_trades:
        key = (trade.open_time, trade.side)
        groups.setdefault(key, []).append(trade)

    logical: list[LogicalTrade] = []
    for (open_time, side), trades in groups.items():
        # Sort by close_time to get the last one
        trades.sort(key=lambda t: t.close_time)
        logical.append(
            LogicalTrade(
                open_time=open_time,
                close_time=trades[-1].close_time,
                side=side,
                net_pnl=sum(t.net_pnl for t in trades),
                net_pnl_pct=sum(t.net_pnl_pct for t in trades),
                partial_count=len(trades),
            )
        )

    logical.sort(key=lambda t: t.close_time)
    return logical


# ─── §4 — Window Partitioning ───────────────────────────────────────────────


def partition_windows(
    trades: list[LogicalTrade],
) -> dict[str, list[LogicalTrade]]:
    """Partition trades into time windows.

    Cutoff = close_time of most recent logical trade (NOT wall clock).
    Window: window_start < trade.close_time <= t_cutoff (right-inclusive, left-exclusive).
    """
    if not trades:
        return {p: [] for p in PERIOD_ORDER}

    t_cutoff = trades[-1].close_time
    windows: dict[str, list[LogicalTrade]] = {}

    for period in PERIOD_ORDER:
        days = PERIOD_DAYS[period]
        window_start = t_cutoff - timedelta(days=days)
        window_trades = [
            t for t in trades if window_start < t.close_time <= t_cutoff
        ]
        windows[period] = window_trades

    return windows


# ─── §6 — Per-Period Metrics ────────────────────────────────────────────────


def compute_period_metrics(
    period: str,
    trades: list[LogicalTrade],
    capital_basis: float,
    tpd_12mo_baseline: float = 0.0,
) -> PeriodMetrics:
    """Compute metrics for a single time window."""
    n = len(trades)

    if n == 0:
        return PeriodMetrics(
            period=period, n=0, win_rate=0.0, profit_factor=0.0,
            mdd_pct=0.0, sharpe_ann=0.0, sortino_ann=0.0,
            trades_per_day=0.0, composite=0.0, insufficient_sample=True,
        )

    insufficient = n < MIN_N_FOR_INCLUSION

    # Basic metrics
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    win_rate = len(wins) / n

    gross_profit = sum(t.net_pnl for t in wins) if wins else 0
    gross_loss = abs(sum(t.net_pnl for t in losses)) if losses else 1e-10
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    # P&L percentages for Sharpe/Sortino
    pnls_pct = [t.net_pnl_pct for t in trades]
    mean_pnl = sum(pnls_pct) / n

    # §6 — Sharpe annualisation: sqrt(tpy) where tpy = (n / days_in_window) * 365
    days_in_window = PERIOD_DAYS[period]
    tpd = n / days_in_window if days_in_window > 0 else 0
    tpy = tpd * 365

    variance = sum((p - mean_pnl) ** 2 for p in pnls_pct) / max(n - 1, 1)
    std_pnl = math.sqrt(variance) if variance > 0 else 1e-10
    sharpe_ann = (mean_pnl / std_pnl) * math.sqrt(tpy) if std_pnl > 0 else 0

    # §6 — Sortino: downside = [p for p in pnls_pct if p < 0]
    downside = [p for p in pnls_pct if p < 0]
    if len(downside) > 1:
        down_var = sum(p**2 for p in downside) / len(downside)
        down_std = math.sqrt(down_var)
        sortino_ann = (mean_pnl / down_std) * math.sqrt(tpy) if down_std > 0 else 99.0
    elif mean_pnl > 0:
        sortino_ann = 99.0
    else:
        sortino_ann = 0.0

    # §7 — MDD continuous equity model
    mdd_pct = _compute_mdd_continuous(trades, capital_basis)

    # Component scores for this period
    s_sharpe = score_sharpe(sharpe_ann)
    s_sortino = score_sortino(sortino_ann)
    s_pf = score_pf(pf)
    s_mdd = score_mdd(mdd_pct)
    s_wr = score_wr(win_rate * 100)
    s_freq = score_freq_v2(tpd / tpd_12mo_baseline if tpd_12mo_baseline > 0 else 1.0, 0.0)
    s_trade_size = score_trade_size(pnls_pct)

    # Period composite (weighted average of component scores)
    composite = (
        s_sharpe * COMP_WEIGHTS["sharpe"]
        + s_sortino * COMP_WEIGHTS["sortino"]
        + s_pf * COMP_WEIGHTS["pf"]
        + s_mdd * COMP_WEIGHTS["mdd"]
        + s_wr * COMP_WEIGHTS["wr"]
        + s_freq * COMP_WEIGHTS["freq"]
        + s_trade_size * COMP_WEIGHTS["trade_size"]
    )

    return PeriodMetrics(
        period=period,
        n=n,
        win_rate=round(win_rate, 4),
        profit_factor=round(pf, 3),
        mdd_pct=round(mdd_pct, 4),
        sharpe_ann=round(sharpe_ann, 4),
        sortino_ann=round(sortino_ann, 4),
        trades_per_day=round(tpd, 4),
        composite=round(composite, 2),
        insufficient_sample=insufficient,
    )


def _compute_mdd_continuous(
    trades: list[LogicalTrade], capital_basis: float
) -> float:
    """§7 — MDD continuous equity model.

    Build equity curve from capital_basis, adding net_pnl trade by trade.
    NEVER reset equity to synthetic baseline at each window start.
    MDD = largest peak-to-trough on the CONTINUOUS equity curve within the window.
    """
    equity = capital_basis
    peak = equity
    max_dd = 0.0

    for trade in trades:
        equity += trade.net_pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return max_dd * 100  # Return as percentage


# ─── §9 — Component Scoring Functions ───────────────────────────────────────


def score_sharpe(sharpe_ann: float) -> float:
    """Sharpe score: < 0 → 0; linear × 20; cap 100 at Sharpe 5.0."""
    if sharpe_ann < 0:
        return 0.0
    return min(100.0, sharpe_ann * 20)


def score_sortino(sortino_ann: float) -> float:
    """Sortino score: < 0 → 0; linear × 10; cap 100 at Sortino 10.0."""
    if sortino_ann < 0:
        return 0.0
    return min(100.0, sortino_ann * 10)


def score_pf(pf: float) -> float:
    """PF score: ≤ 1.0 → 0; ≥ 4.0 → 100; linear (pf-1)/3*100."""
    if pf <= 1.0:
        return 0.0
    return min(100.0, ((pf - 1) / 3) * 100)


def score_mdd(mdd_pct: float) -> float:
    """MDD score: ≤ 1% → 100; ≥ 30% → 0; linear in between."""
    if mdd_pct <= 1.0:
        return 100.0
    if mdd_pct >= 30.0:
        return 0.0
    return 100.0 - ((mdd_pct - 1) / 29) * 100


def score_wr(wr_pct: float) -> float:
    """WR score: ≤ 30 → 0; ≥ 85 → 100; linear in between."""
    if wr_pct <= 30:
        return 0.0
    if wr_pct >= 85:
        return 100.0
    return ((wr_pct - 30) / 55) * 100


def score_trade_size(pnls_pct: list[float]) -> float:
    """Trade size score: penalise avg_loss < -2% and largest_loss < -5%."""
    if not pnls_pct:
        return 100.0

    losses = [p for p in pnls_pct if p < 0]
    if not losses:
        return 100.0

    avg_loss = sum(losses) / len(losses)
    largest_loss = min(losses)

    base = 100.0
    if avg_loss < -2.0:
        base -= (abs(avg_loss) - 2.0) * 20
    if largest_loss < -5.0:
        base -= (abs(largest_loss) - 5.0) * 10

    return max(0.0, min(100.0, base))


# ─── §10 — FreqStab Asymmetric v2 ──────────────────────────────────────────


def score_freq_v2(ratio: float, perf_health: float) -> float:
    """FreqStab asymmetric v2.

    ratio = tpd_window / tpd_12mo_baseline
    perf_health = avg(score_sharpe, score_pf, score_mdd, score_wr) for this window
    raw = max(0, min(100, 100 - abs(1.0 - ratio) * 50))
    ASYMMETRIC RELIEF: if ratio > 1 AND perf_health >= 90:
        return min(100, raw + (perf_health - 90) * 10)
    else: return raw
    """
    raw = max(0.0, min(100.0, 100 - abs(1.0 - ratio) * 50))

    if ratio > 1 and perf_health >= 90:
        return min(100.0, raw + (perf_health - 90) * 10)

    return raw


# ─── §12 — Stability ───────────────────────────────────────────────────────


def compute_stability(
    period_composites: dict[str, float],
    period_n: dict[str, int],
    c12_composite: float,
) -> tuple[float, float, float, bool]:
    """Compute stability, sigma, trend_drop, and catastrophic floor.

    Returns (stability, sigma, trend_drop, catastrophic_floor).
    """
    # Eligible periods: N >= 5 only
    eligible = {
        p: c for p, c in period_composites.items()
        if period_n.get(p, 0) >= MIN_N_FOR_INCLUSION
    }

    # Sigma: sample stdev (n-1) across eligible period composites
    if len(eligible) >= 2:
        values = list(eligible.values())
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        sigma = math.sqrt(variance)
    else:
        sigma = 0.0

    # Tier floor based on c12_composite
    if c12_composite >= 85:
        tier_floor = 85
    elif c12_composite >= 70:
        tier_floor = 70
    elif c12_composite >= 55:
        tier_floor = 55
    elif c12_composite >= 40:
        tier_floor = 40
    else:
        tier_floor = 0

    # Recent min (1mo and 7d only, N >= 5)
    recent_periods = ["1mo", "7d"]
    recent_eligible = {
        p: period_composites[p]
        for p in recent_periods
        if period_n.get(p, 0) >= MIN_N_FOR_INCLUSION
    }

    # §13 — Catastrophic Floor
    catastrophic_floor = False
    if recent_eligible:
        recent_min = min(recent_eligible.values())
        if recent_min < 40:
            catastrophic_floor = True
    else:
        # If no recent periods have N >= 5, use c12
        recent_min = c12_composite

    # §12 — Trend drop
    if recent_min >= tier_floor:
        trend_drop = 0.0
    elif catastrophic_floor:
        # Full drop, no relief
        trend_drop = max(0.0, c12_composite - recent_min)
    else:
        trend_drop = max(0.0, c12_composite - recent_min)

    # Stability
    stability = max(0.0, 100 - sigma * 2 - trend_drop)

    return round(stability, 2), round(sigma, 2), round(trend_drop, 2), catastrophic_floor


# ─── §14 — Final Score ──────────────────────────────────────────────────────


def compute_final_tsi(weighted_composite: float, stability: float) -> float:
    """final_tsi = weighted_composite × (0.5 + 0.5 × stability / 100)"""
    return weighted_composite * (0.5 + 0.5 * stability / 100)


def grade_from_tsi(final_tsi: float) -> TSIGrade:
    """Derive grade from final_tsi via tier thresholds."""
    if final_tsi >= 85:
        return TSIGrade.S
    elif final_tsi >= 70:
        return TSIGrade.A
    elif final_tsi >= 55:
        return TSIGrade.B
    elif final_tsi >= 40:
        return TSIGrade.C
    else:
        return TSIGrade.D


def leverage_cap_for_grade(grade: TSIGrade) -> float:
    """Leverage cap from grade."""
    caps = {"S": 3.0, "A": 2.0, "B": 1.5, "C": 1.0, "D": 0.0}
    return caps[grade.value]


def weight_cap_for_grade(grade: TSIGrade) -> float | None:
    """Weight cap percentage from grade."""
    caps = {"S": None, "A": 15.0, "B": 8.0, "C": 5.0, "D": 0.0}
    return caps[grade.value]


# ─── DQ Triggers ────────────────────────────────────────────────────────────


def check_dq_triggers(
    period_metrics: dict[str, PeriodMetrics],
) -> list[str]:
    """Check hard DQ thresholds. Returns list of fired triggers."""
    triggers: list[str] = []

    pm_12 = period_metrics.get("12mo")
    pm_1 = period_metrics.get("1mo")

    if pm_12 and pm_12.profit_factor < 1.3:
        triggers.append("PF12<1.3")

    if pm_1 and pm_1.sharpe_ann < 0:
        triggers.append("Sharpe1<0")

    if pm_1 and pm_1.composite < -5:  # Net1 < -5%
        triggers.append("Net1<-5%")

    if pm_12 and pm_12.mdd_pct > 20:
        triggers.append("MDD>20%")

    return triggers


# ─── Main Scoring Function ──────────────────────────────────────────────────


def tsi_score(
    raw_trades: list[RawTrade],
    capital_basis: float,
    strategy_id: str = "unknown",
    asset: str = "unknown",
    aggregate: bool = True,
) -> TSIResult:
    """Compute TSI v2.0 CA score from raw trades.

    Args:
        raw_trades: RawTrade objects from backtest parser.
        capital_basis: Capital basis for MDD and P&L% calculations.
        strategy_id: Strategy identifier.
        asset: Asset ticker.
        aggregate: If True, aggregate partial fills into logical trades.

    Returns:
        Complete TSIResult with all fields populated.
    """
    logger.info("tsi_score_start", trades=len(raw_trades), capital_basis=capital_basis)

    # §3 — Aggregate partial fills
    if aggregate:
        logical_trades = aggregate_logical(raw_trades)
    else:
        logical_trades = [
            LogicalTrade(
                open_time=t.open_time,
                close_time=t.close_time,
                side=t.side,
                net_pnl=t.net_pnl,
                net_pnl_pct=t.net_pnl_pct,
            )
            for t in raw_trades
        ]

    if not logical_trades:
        logger.warning("no_trades_to_score")
        return _empty_tsi_result(strategy_id, asset, capital_basis)

    logger.info("logical_trades", count=len(logical_trades))

    # §4 — Partition into windows
    windows = partition_windows(logical_trades)

    # §6 — Compute per-period metrics
    tpd_12mo = len(windows.get("12mo", [])) / 365 if windows.get("12mo") else 0
    period_metrics_list: list[PeriodMetrics] = []
    period_composites: dict[str, float] = {}
    period_n: dict[str, int] = {}

    for period in PERIOD_ORDER:
        pm = compute_period_metrics(
            period, windows[period], capital_basis, tpd_12mo_baseline=tpd_12mo
        )
        period_metrics_list.append(pm)
        period_composites[period] = pm.composite
        period_n[period] = pm.n

    # Period-weighted composite
    weighted_composite = sum(
        period_composites[p] * PERIOD_WEIGHTS[p] for p in PERIOD_ORDER
    )

    # §12 — Stability
    c12_composite = period_composites.get("12mo", 0.0)
    stability, sigma, trend_drop, catastrophic_floor = compute_stability(
        period_composites, period_n, c12_composite
    )

    # §14 — Final score
    final_tsi = compute_final_tsi(weighted_composite, stability)
    grade = grade_from_tsi(final_tsi)
    leverage_cap = leverage_cap_for_grade(grade)
    weight_cap = weight_cap_for_grade(grade)

    # DQ triggers
    pm_dict = {pm.period: pm for pm in period_metrics_list}
    dq_triggers = check_dq_triggers(pm_dict)

    # Component scores (from 12mo for the top-level components dict)
    pm_12 = pm_dict.get("12mo")
    components = {}
    if pm_12:
        components = {
            "sharpe": pm_12.sharpe_ann,
            "sortino": pm_12.sortino_ann,
            "pf": pm_12.profit_factor,
            "mdd": pm_12.mdd_pct,
            "wr": pm_12.win_rate,
            "freq": pm_12.trades_per_day,
            "trade_size": 0.0,  # Computed from P&L distribution
        }

    # Diagnostics
    diagnostics = {
        "catastrophic_floor": catastrophic_floor,
        "tier_floor": TIER_THRESHOLDS.get(grade.value, 0),
        "trend_drop": trend_drop,
        "sigma": sigma,
    }

    result = TSIResult(
        strategy_id=strategy_id,
        asset=asset,
        period_start=logical_trades[0].close_time,
        period_end=logical_trades[-1].close_time,
        capital_basis=capital_basis,
        components=components,
        weighted_composite=round(weighted_composite, 2),
        stability=stability,
        sigma_periods=sigma,
        trend_drop=trend_drop,
        catastrophic_floor=catastrophic_floor,
        final_tsi=round(final_tsi, 2),
        grade=grade,
        leverage_cap=leverage_cap,
        weight_cap_pct=weight_cap,
        dq_triggers=dq_triggers,
        period_metrics=period_metrics_list,
        diagnostics=diagnostics,
    )

    logger.info(
        "tsi_score_complete",
        final_tsi=result.final_tsi,
        grade=grade.value,
        stability=stability,
    )

    return result


def _empty_tsi_result(strategy_id: str, asset: str, capital_basis: float) -> TSIResult:
    """Return an empty TSIResult when no trades are available."""
    return TSIResult(
        strategy_id=strategy_id,
        asset=asset,
        period_start=datetime.now(),
        period_end=datetime.now(),
        capital_basis=capital_basis,
        components={},
        weighted_composite=0.0,
        stability=0.0,
        sigma_periods=0.0,
        trend_drop=0.0,
        catastrophic_floor=False,
        final_tsi=0.0,
        grade=TSIGrade.D,
        leverage_cap=0.0,
        weight_cap_pct=0.0,
        dq_triggers=[],
        period_metrics=[
            PeriodMetrics(
                period=p, n=0, win_rate=0.0, profit_factor=0.0,
                mdd_pct=0.0, sharpe_ann=0.0, sortino_ann=0.0,
                trades_per_day=0.0, composite=0.0, insufficient_sample=True,
            )
            for p in PERIOD_ORDER
        ],
        diagnostics={"no_trades": True},
    )
