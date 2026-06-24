"""Portfolio-level metrics — correlation, diversification, kill zone.

PRD: docs/Strategy Docs - converted/backtest/NARRUX_Backtest_Analysis_Approach_v1.0.md §7

NO pydantic_ai imports. Pure Python + Pydantic.
"""

from __future__ import annotations

import math
from itertools import combinations

import structlog

from tools.schemas import PortfolioResult

logger = structlog.get_logger(__name__)

# Kill zone thresholds (PRD §7)
KILL_ZONE_RHO = 0.30
KILL_ZONE_TAIL = 0.20  # 20% tail loss threshold


def _pearson_rho(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation coefficient between two series.

    Handles unequal lengths by truncating to the shorter one.
    Returns 0.0 if insufficient data.
    """
    n = min(len(x), len(y))
    if n < 3:
        return 0.0

    x = x[:n]
    y = y[:n]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (n - 1)

    var_x = sum((xi - mean_x) ** 2 for xi in x) / (n - 1)
    var_y = sum((yi - mean_y) ** 2 for yi in y) / (n - 1)

    std_x = math.sqrt(var_x) if var_x > 0 else 1e-10
    std_y = math.sqrt(var_y) if var_y > 0 else 1e-10

    return cov / (std_x * std_y)


def _tail_loss(daily_pnl: list[float], capital: float, percentile: float = 0.05) -> float:
    """Compute tail loss: the average of the worst N% of daily returns.

    Returns the tail loss as a positive fraction (e.g., 0.20 = 20% loss).
    """
    if not daily_pnl or capital <= 0:
        return 0.0

    returns = sorted([p / capital for p in daily_pnl])
    n_tail = max(1, int(len(returns) * percentile))
    tail_returns = returns[:n_tail]

    # Tail loss = average of worst returns (negative values)
    avg_tail = sum(tail_returns) / len(tail_returns)
    return abs(avg_tail) if avg_tail < 0 else 0.0


def _check_kill_zone(
    daily_pnl_a: list[float],
    daily_pnl_b: list[float],
    capital_a: float,
    capital_b: float,
) -> tuple[bool, float, float]:
    """Check if a pair of strategies triggers the kill zone.

    Kill zone: rho >= 0.30 AND tail >= 20% (2008/2020 envelope).
    BOTH conditions required.

    Returns:
        (kill_zone_active, rho, max_tail_loss)
    """
    rho = _abs(_pearson_rho(daily_pnl_a, daily_pnl_b))

    tail_a = _tail_loss(daily_pnl_a, capital_a)
    tail_b = _tail_loss(daily_pnl_b, capital_b)
    max_tail = max(tail_a, tail_b)

    active = rho >= KILL_ZONE_RHO and max_tail >= KILL_ZONE_TAIL
    return active, round(rho, 4), round(max_tail, 4)


def _abs(x: float) -> float:
    return x if x >= 0 else -x


def compute_portfolio_metrics(
    strategy_pnl: dict[str, list[float]],
    strategy_capital: dict[str, float] | None = None,
) -> PortfolioResult:
    """Compute portfolio-level correlation and diversification metrics.

    §7: Near-zero pairwise correlation (empirical mean ~0.026) is the source
    of diversification gain. Kill zone: rho >= 0.30 AND tail >= 20%.

    Args:
        strategy_pnl: {strategy_id: [daily_pnl_usd, ...]}
        strategy_capital: {strategy_id: capital_basis} for tail loss computation.
            If None, tail loss check is skipped.

    Returns:
        PortfolioResult with correlation matrix, diversification ratio, kill zone.
    """
    strategies = list(strategy_pnl.keys())
    n = len(strategies)

    logger.info("portfolio_metrics_start", strategies=n)

    if n < 2:
        return PortfolioResult(
            strategies=strategies,
            correlation_matrix={},
            avg_pairwise_rho=0.0,
            min_pairwise_rho=0.0,
            max_pairwise_rho=0.0,
            diversification_ratio=1.0,
            kill_zone_active=False,
            triggering_pairs=[],
            n_strategies=n,
        )

    # Compute pairwise correlation matrix
    corr_matrix: dict[str, dict[str, float]] = {s: {} for s in strategies}
    rhos: list[float] = []
    kill_zone_pairs: list[str] = []

    for sym_a, sym_b in combinations(strategies, 2):
        pnl_a = strategy_pnl[sym_a]
        pnl_b = strategy_pnl[sym_b]

        rho = _pearson_rho(pnl_a, pnl_b)
        rho_rounded = round(rho, 4)

        corr_matrix[sym_a][sym_b] = rho_rounded
        corr_matrix[sym_b][sym_a] = rho_rounded
        rhos.append(_abs(rho))

        # Kill zone check
        if strategy_capital:
            cap_a = strategy_capital.get(sym_a, 100000.0)
            cap_b = strategy_capital.get(sym_b, 100000.0)
            kz, _, _ = _check_kill_zone(pnl_a, pnl_b, cap_a, cap_b)
            if kz:
                kill_zone_pairs.append(f"{sym_a}/{sym_b}")

    # Diagonal = 1.0
    for s in strategies:
        corr_matrix[s][s] = 1.0

    # Summary stats
    avg_rho = sum(rhos) / len(rhos) if rhos else 0.0
    min_rho = min(rhos) if rhos else 0.0
    max_rho = max(rhos) if rhos else 0.0

    # Diversification ratio: 1 / (1 + avg_rho)
    # When avg_rho = 0 → ratio = 1.0 (perfect diversification)
    # When avg_rho = 1 → ratio = 0.5 (no diversification)
    div_ratio = 1.0 / (1.0 + avg_rho) if avg_rho >= 0 else 1.0

    result = PortfolioResult(
        strategies=strategies,
        correlation_matrix=corr_matrix,
        avg_pairwise_rho=round(avg_rho, 4),
        min_pairwise_rho=round(min_rho, 4),
        max_pairwise_rho=round(max_rho, 4),
        diversification_ratio=round(div_ratio, 4),
        kill_zone_active=len(kill_zone_pairs) > 0,
        triggering_pairs=kill_zone_pairs,
        n_strategies=n,
    )

    logger.info(
        "portfolio_metrics_complete",
        avg_rho=round(avg_rho, 4),
        div_ratio=round(div_ratio, 4),
        kill_zone=result.kill_zone_active,
    )

    return result
