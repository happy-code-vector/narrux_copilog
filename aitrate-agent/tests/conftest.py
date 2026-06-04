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
    TradeSource,
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
    return TSIResult(
        strategy_id="alpha_v15_9_1",
        asset="TSLA",
        period_start=datetime(2024, 1, 1),
        period_end=datetime(2024, 6, 30),
        components={
            "sharpe": 1.45,
            "profit_factor": 1.85,
            "sortino": 1.92,
            "max_drawdown": 8.3,
            "win_rate": 0.62,
        },
        weighted_score=72.5,
        grade=TSIGrade.B,
        leverage_cap=1.5,
        dq_triggers=[],
        computed_from_raw_csv=False,
    )
