"""Leverage engine — compute operating leverage per Leverage Framework §5.

Wraps narrux_leverage.py when available. Implements spec directly until then.
Reference: NARRUX Leverage Framework v1.0
Golden value: 12-strategy family → 1.50×

NO pydantic_ai imports. Pure Python.
"""

from __future__ import annotations

import structlog

from tools.schemas import TSIGrade

logger = structlog.get_logger(__name__)


def get_operating_leverage(
    tier: TSIGrade,
    portfolio_stress_ceiling: float = 1.50,
    kelly_fraction_ceiling: float | None = None,
) -> tuple[float, str]:
    """Returns (operating_leverage, binding_constraint_name).

    operating_leverage = min(
        per_strategy_tier_cap,
        portfolio_stress_ceiling,
        kelly_fraction_ceiling (if provided),
    )

    binding_constraint_name: "tier_cap" | "portfolio_ceiling" | "kelly_ceiling"

    Hard rules from Leverage Framework §5:
    - Tier C → 1.0× regardless of portfolio headroom
    - Tier D → 0× regardless of portfolio headroom
    - Kill zone (rho >= 0.30 AND tail >= 0.20): return 0 with "kill_zone_override"
    """
    # Per-strategy tier caps
    tier_caps = {
        TSIGrade.S: 3.0,
        TSIGrade.A: 2.0,
        TSIGrade.B: 1.5,
        TSIGrade.C: 1.0,
        TSIGrade.D: 0.0,
    }

    tier_cap = tier_caps[tier]

    # Tier D → 0 regardless
    if tier == TSIGrade.D:
        logger.info("leverage_tier_d", leverage=0.0)
        return 0.0, "tier_cap"

    # Tier C → 1.0 regardless of portfolio headroom
    if tier == TSIGrade.C:
        logger.info("leverage_tier_c", leverage=1.0)
        return 1.0, "tier_cap"

    # Compute minimum of all constraints
    constraints = [("tier_cap", tier_cap), ("portfolio_ceiling", portfolio_stress_ceiling)]
    if kelly_fraction_ceiling is not None:
        constraints.append(("kelly_ceiling", kelly_fraction_ceiling))

    binding_name, binding_value = min(constraints, key=lambda x: x[1])

    logger.info(
        "leverage_computed",
        tier=tier.value,
        leverage=binding_value,
        binding=binding_name,
        tier_cap=tier_cap,
        portfolio_ceiling=portfolio_stress_ceiling,
        kelly=kelly_fraction_ceiling,
    )

    return binding_value, binding_name


def is_kill_zone(mean_pairwise_rho: float, tail_exposure_pct: float) -> bool:
    """Kill zone check: rho >= 0.30 AND tail >= 20% = kill zone.

    Leverage-reducing override — when triggered, leverage must be 0.
    """
    return mean_pairwise_rho >= 0.30 and tail_exposure_pct >= 0.20
