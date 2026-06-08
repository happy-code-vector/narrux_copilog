"""Unit tests for TSI v2.0 CA engine — tools/tsi_engine.py.

Tests use synthetic data (no DB, no API keys needed).
"""

import pytest
from datetime import datetime, timedelta

from tools.schemas import RawTrade, TSIGrade
from tools.tsi_engine import (
    aggregate_logical,
    compute_final_tsi,
    compute_period_metrics,
    compute_stability,
    grade_from_tsi,
    score_freq_v2,
    score_mdd,
    score_pf,
    score_sharpe,
    score_sortino,
    score_trade_size,
    score_wr,
    tsi_score,
)


def _make_trades(n: int, win_rate: float = 0.6, base_pnl: float = 500.0) -> list[RawTrade]:
    """Generate synthetic trades for testing."""
    trades = []
    base_time = datetime(2025, 1, 1)
    for i in range(n):
        is_win = (i % 100) / 100 < win_rate
        pnl = base_pnl if is_win else -base_pnl * 0.6
        trades.append(
            RawTrade(
                open_time=base_time + timedelta(days=i),
                close_time=base_time + timedelta(days=i, hours=6),
                side="long" if i % 2 == 0 else "short",
                net_pnl=pnl,
                net_pnl_pct=pnl / 100000 * 100,
            )
        )
    return trades


class TestLogicalAggregation:
    """§3 — Logical trade aggregation tests."""

    def test_no_aggregation_needed(self):
        """Trades with different open_times are not aggregated."""
        trades = _make_trades(10)
        logical = aggregate_logical(trades)
        assert len(logical) == 10

    def test_partial_fills_aggregated(self):
        """Trades with same open_time+side are aggregated."""
        base = datetime(2025, 1, 1)
        trades = [
            RawTrade(open_time=base, close_time=base + timedelta(hours=1),
                     side="long", net_pnl=100, net_pnl_pct=0.1),
            RawTrade(open_time=base, close_time=base + timedelta(hours=2),
                     side="long", net_pnl=200, net_pnl_pct=0.2),
            RawTrade(open_time=base, close_time=base + timedelta(hours=3),
                     side="long", net_pnl=-50, net_pnl_pct=-0.05),
        ]
        logical = aggregate_logical(trades)
        assert len(logical) == 1
        assert logical[0].net_pnl == 250
        assert logical[0].partial_count == 3

    def test_different_sides_not_aggregated(self):
        """Same open_time but different sides are separate logical trades."""
        base = datetime(2025, 1, 1)
        trades = [
            RawTrade(open_time=base, close_time=base + timedelta(hours=1),
                     side="long", net_pnl=100, net_pnl_pct=0.1),
            RawTrade(open_time=base, close_time=base + timedelta(hours=1),
                     side="short", net_pnl=200, net_pnl_pct=0.2),
        ]
        logical = aggregate_logical(trades)
        assert len(logical) == 2


class TestComponentScoring:
    """§9 — Component scoring function tests."""

    def test_score_sharpe(self):
        assert score_sharpe(-1) == 0
        assert score_sharpe(0) == 0
        assert score_sharpe(2.5) == 50
        assert score_sharpe(5.0) == 100
        assert score_sharpe(10.0) == 100  # capped

    def test_score_sortino(self):
        assert score_sortino(-1) == 0
        assert score_sortino(5.0) == 50
        assert score_sortino(10.0) == 100

    def test_score_pf(self):
        assert score_pf(0.5) == 0
        assert score_pf(1.0) == 0
        assert score_pf(2.5) == 50
        assert score_pf(4.0) == 100

    def test_score_mdd(self):
        assert score_mdd(0.5) == 100
        assert score_mdd(1.0) == 100
        assert score_mdd(15.5) == pytest.approx(50, abs=1)
        assert score_mdd(30) == 0
        assert score_mdd(50) == 0

    def test_score_wr(self):
        assert score_wr(20) == 0
        assert score_wr(30) == 0
        assert score_wr(57.5) == pytest.approx(50, abs=1)
        assert score_wr(85) == 100
        assert score_wr(95) == 100

    def test_score_trade_size_no_losses(self):
        assert score_trade_size([1.0, 2.0, 3.0]) == 100

    def test_score_trade_size_with_losses(self):
        # avg_loss = -3%, largest = -6%
        score = score_trade_size([1.0, 2.0, -3.0, -6.0])
        assert score < 100


class TestFreqStab:
    """§10 — FreqStab asymmetric v2 tests."""

    def test_balanced_ratio(self):
        assert score_freq_v2(1.0, 0) == 100

    def test_low_ratio(self):
        score = score_freq_v2(0.5, 0)
        assert score == 75  # 100 - |1-0.5| * 50

    def test_asymmetric_relief(self):
        # ratio > 1 AND perf_health >= 90
        score = score_freq_v2(1.5, 95)
        raw = 100 - abs(1.0 - 1.5) * 50  # = 75
        expected = min(100, raw + (95 - 90) * 10)  # = 75 + 50 = 100
        assert score == expected


class TestStability:
    """§12 — Stability computation tests."""

    def test_stable_strategy(self):
        """All periods similar → high stability, low sigma."""
        composites = {"12mo": 75, "6mo": 76, "3mo": 74, "1mo": 75, "7d": 77}
        n = {"12mo": 100, "6mo": 50, "3mo": 25, "1mo": 10, "7d": 6}
        stability, sigma, trend_drop, cat_floor = compute_stability(composites, n, 75)
        assert stability > 90
        assert sigma < 5
        assert trend_drop == 0
        assert cat_floor is False

    def test_catastrophic_floor(self):
        """1mo composite < 40 with N >= 5 triggers Cat Floor."""
        composites = {"12mo": 80, "6mo": 75, "3mo": 60, "1mo": 30, "7d": 25}
        n = {"12mo": 100, "6mo": 50, "3mo": 25, "1mo": 10, "7d": 6}
        stability, sigma, trend_drop, cat_floor = compute_stability(composites, n, 80)
        assert cat_floor is True
        assert trend_drop > 0

    def test_insufficient_sample_no_cat_floor(self):
        """N < 5 in recent periods → Cat Floor cannot trigger."""
        composites = {"12mo": 80, "6mo": 75, "3mo": 60, "1mo": 30, "7d": 25}
        n = {"12mo": 100, "6mo": 50, "3mo": 25, "1mo": 3, "7d": 2}
        stability, sigma, trend_drop, cat_floor = compute_stability(composites, n, 80)
        assert cat_floor is False


class TestFinalScore:
    """§14 — Final score tests."""

    def test_final_tsi_formula(self):
        """final_tsi = weighted_composite × (0.5 + 0.5 × stability / 100)."""
        result = compute_final_tsi(80.0, 90.0)
        expected = 80.0 * (0.5 + 0.5 * 90.0 / 100)
        assert abs(result - expected) < 0.001

    def test_grade_thresholds(self):
        assert grade_from_tsi(90) == TSIGrade.S
        assert grade_from_tsi(85) == TSIGrade.S
        assert grade_from_tsi(70) == TSIGrade.A
        assert grade_from_tsi(55) == TSIGrade.B
        assert grade_from_tsi(40) == TSIGrade.C
        assert grade_from_tsi(39) == TSIGrade.D

    def test_no_cat_floor_multiplier(self):
        """Final TSI must equal weighted_composite × (0.5 + 0.5 × stability/100). No extra haircut."""
        trades = _make_trades(100, win_rate=0.65, base_pnl=600)
        result = tsi_score(trades, capital_basis=100000)
        expected = result.weighted_composite * (0.5 + 0.5 * result.stability / 100)
        assert abs(result.final_tsi - expected) < 0.01


class TestTSIScoreIntegration:
    """Integration tests for tsi_score()."""

    def test_basic_scoring(self):
        """Basic scoring with sufficient trades."""
        trades = _make_trades(100, win_rate=0.6)
        result = tsi_score(trades, capital_basis=100000)
        assert result.grade in [TSIGrade.S, TSIGrade.A, TSIGrade.B, TSIGrade.C, TSIGrade.D]
        assert result.leverage_cap >= 0
        assert len(result.period_metrics) == 5

    def test_empty_trades(self):
        """Empty trade list returns Grade D."""
        result = tsi_score([], capital_basis=100000)
        assert result.grade == TSIGrade.D
        assert result.final_tsi == 0

    def test_all_wins(self):
        """All winning trades → high score."""
        trades = _make_trades(50, win_rate=1.0, base_pnl=500)
        result = tsi_score(trades, capital_basis=100000)
        assert result.final_tsi > 50

    def test_all_losses(self):
        """All losing trades → low score."""
        trades = _make_trades(50, win_rate=0.0, base_pnl=500)
        result = tsi_score(trades, capital_basis=100000)
        assert result.final_tsi < 30
