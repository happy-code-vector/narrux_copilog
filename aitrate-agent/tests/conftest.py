"""Pytest fixtures for the NARRUX aiTrate Co-Pilot test suite."""

import pytest
from datetime import datetime
from uuid import uuid4

from config import get_settings
from tools.schemas import (
    BacktestSummary,
    ConfidenceLevel,
    FunctionID,
    TSIResult,
    TSIGrade,
    TradeRecord,
)


@pytest.fixture
def settings():
    """Return application settings."""
    return get_settings()


@pytest.fixture
def sample_trade_record():
    """Return a valid TradeRecord with realistic values."""
    return TradeRecord(
        trade_id=uuid4(),
        strategy_id="alpha_v15_9_1",
        asset="TSLA",
        timeframe="1H",
        source="backtest",
        execution_mode="CLOSED",
        side="long",
        entry_time=datetime(2024, 1, 15, 10, 0, 0),
        exit_time=datetime(2024, 1, 15, 14, 30, 0),
        entry_price=220.50,
        exit_price=225.75,
        size=10.0,
        pnl=52.50,
        pnl_pct=2.38,
        mae=-15.00,
        mfe=65.00,
        entry_method="F19_proximity",
        exit_reason="trailing_stop",
        filters_fired=["F19", "F7"],
        regime_label="trending",
        capital_basis=2425.50,
    )


@pytest.fixture
def sample_backtest_summary():
    """Return a BacktestSummary with stop_loss_ratio below threshold."""
    return BacktestSummary(
        strategy_id="alpha_v15_9_1",
        asset="TSLA",
        timeframe="1H",
        period_start=datetime(2024, 1, 1),
        period_end=datetime(2024, 6, 30),
        total_trades=150,
        win_rate=0.62,
        profit_factor=1.85,
        net_pnl=12500.00,
        net_pnl_pct=12.5,
        max_drawdown_pct=8.3,
        sharpe_ratio=1.45,
        stop_loss_count=37,
        stop_loss_ratio=0.25,  # Below 0.40 threshold
        capital_basis=100000.00,
        calc_on_order_fills=False,
        process_orders_on_close=False,
        execution_mode="CLOSED",
    )


@pytest.fixture
def sample_tsi_result():
    """Return a TSIResult with grade=B."""
    from tools.schemas import PeriodMetrics
    return TSIResult(
        strategy_id="alpha_v15_9_1",
        asset="TSLA",
        period_start=datetime(2024, 1, 1),
        period_end=datetime(2024, 6, 30),
        capital_basis=100000.0,
        components={"sharpe": 0.73, "pf": 0.91, "sortino": 0.80, "mdd": 0.75, "wr": 0.62, "freq": 0.55, "trade_size": 0.45},
        weighted_composite=72.5,
        stability=85.0,
        sigma_periods=2.5,
        trend_drop=0.0,
        catastrophic_floor=False,
        final_tsi=72.5,
        grade=TSIGrade.B,
        leverage_cap=1.5,
        weight_cap_pct=8.0,
        dq_triggers=[],
        period_metrics=[
            PeriodMetrics(period="12mo", n=150, win_rate=0.62, profit_factor=1.85, mdd_pct=8.3, sharpe_ann=1.45, sortino_ann=1.92, trades_per_day=0.83, composite=74.12, insufficient_sample=False),
            PeriodMetrics(period="6mo", n=80, win_rate=0.64, profit_factor=1.90, mdd_pct=6.5, sharpe_ann=1.55, sortino_ann=2.05, trades_per_day=0.88, composite=76.30, insufficient_sample=False),
            PeriodMetrics(period="3mo", n=40, win_rate=0.60, profit_factor=1.75, mdd_pct=5.2, sharpe_ann=1.35, sortino_ann=1.80, trades_per_day=0.87, composite=70.50, insufficient_sample=False),
            PeriodMetrics(period="1mo", n=15, win_rate=0.58, profit_factor=1.60, mdd_pct=3.1, sharpe_ann=1.20, sortino_ann=1.65, trades_per_day=0.94, composite=68.20, insufficient_sample=False),
            PeriodMetrics(period="7d", n=4, win_rate=0.75, profit_factor=2.10, mdd_pct=1.5, sharpe_ann=1.80, sortino_ann=2.50, trades_per_day=1.14, composite=80.00, insufficient_sample=True),
        ],
        diagnostics={},
        computed_from_raw_csv=False,
    )
