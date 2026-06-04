"""Unit tests for tools/schemas.py — no external services required."""

import json
import pytest
from datetime import datetime
from uuid import uuid4

from tools.schemas import (
    AgentResponse,
    AlphaWebhookAlert,
    AuditEntry,
    ConfidenceLevel,
    FunctionID,
    ParameterClass,
    Recommendation,
    SentinelWebhookAlert,
    TSIResult,
    TSIGrade,
    TradeRecord,
    parse_webhook_alert,
)


class TestParseWebhookAlert:
    """Test webhook alert parsing — Alpha JSON and Sentinel CSV."""

    def test_parse_webhook_alert_alpha(self):
        """Parse valid Alpha JSON payload → AlphaWebhookAlert."""
        payload = json.dumps({
            "symbol": "TSLA",
            "side": "long",
            "action": "entry",
            "qty": 1.5,
            "price": 220.50,
        })
        alert = parse_webhook_alert(payload)
        assert isinstance(alert, AlphaWebhookAlert)
        assert alert.symbol == "TSLA"
        assert alert.side == "long"
        assert alert.qty == 1.5

    def test_parse_webhook_alert_sentinel(self):
        """Parse Sentinel CSV → SentinelWebhookAlert."""
        payload = "NARRUX_SENTINEL,long,entry,qty=1.5"
        alert = parse_webhook_alert(payload)
        assert isinstance(alert, SentinelWebhookAlert)
        assert alert.bot_name == "NARRUX_SENTINEL"
        assert alert.side == "long"
        assert alert.action == "entry"
        assert alert.qty == 1.5

    def test_parse_webhook_alert_sentinel_minimal(self):
        """Parse minimal Sentinel CSV."""
        payload = "BOT_001,short,exit"
        alert = parse_webhook_alert(payload)
        assert isinstance(alert, SentinelWebhookAlert)
        assert alert.bot_name == "BOT_001"
        assert alert.side == "short"
        assert alert.qty is None


class TestTSILeverage:
    """Test TSI grade → leverage cap mapping."""

    def test_tsi_leverage_cap_s(self):
        result = TSIResult(
            strategy_id="test", asset="TSLA",
            period_start=datetime.now(), period_end=datetime.now(),
            weighted_score=95.0, grade=TSIGrade.S, leverage_cap=3.0,
        )
        assert result.leverage_cap_for_grade() == 3.0

    def test_tsi_leverage_cap_a(self):
        result = TSIResult(
            strategy_id="test", asset="TSLA",
            period_start=datetime.now(), period_end=datetime.now(),
            weighted_score=85.0, grade=TSIGrade.A, leverage_cap=2.0,
        )
        assert result.leverage_cap_for_grade() == 2.0

    def test_tsi_leverage_cap_b(self):
        result = TSIResult(
            strategy_id="test", asset="TSLA",
            period_start=datetime.now(), period_end=datetime.now(),
            weighted_score=72.5, grade=TSIGrade.B, leverage_cap=1.5,
        )
        assert result.leverage_cap_for_grade() == 1.5

    def test_tsi_leverage_cap_c(self):
        result = TSIResult(
            strategy_id="test", asset="TSLA",
            period_start=datetime.now(), period_end=datetime.now(),
            weighted_score=55.0, grade=TSIGrade.C, leverage_cap=1.0,
        )
        assert result.leverage_cap_for_grade() == 1.0

    def test_tsi_leverage_cap_d(self):
        result = TSIResult(
            strategy_id="test", asset="TSLA",
            period_start=datetime.now(), period_end=datetime.now(),
            weighted_score=30.0, grade=TSIGrade.D, leverage_cap=0.0,
        )
        assert result.leverage_cap_for_grade() == 0.0


class TestTradeRecord:
    """Test TradeRecord creation and roundtrip."""

    def test_trade_record_roundtrip(self):
        """Create TradeRecord, dump to dict, reconstruct, assert equal."""
        record = TradeRecord(
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
        )
        data = record.model_dump()
        reconstructed = TradeRecord(**data)
        assert reconstructed.strategy_id == record.strategy_id
        assert reconstructed.asset == record.asset
        assert reconstructed.entry_price == record.entry_price
        assert reconstructed.trade_id == record.trade_id


class TestAgentResponse:
    """Test AgentResponse creation."""

    def test_agent_response_abstain_confidence(self):
        """AgentResponse with ABSTAIN confidence and empty citations is valid."""
        response = AgentResponse(
            response_id=uuid4(),
            function_id=FunctionID.F01,
            content="I don't have enough information.",
            citations=[],
            confidence=ConfidenceLevel.abstain,
        )
        assert response.confidence == ConfidenceLevel.abstain
        assert response.citations == []


class TestRecommendation:
    """Test Recommendation model."""

    def test_recommendation_governance_class_c(self):
        """Recommendation with parameter_class=C and no regime_label is constructable.

        Governance enforcement is in validator, not model.
        """
        rec = Recommendation(
            parameter_name="CVD_threshold",
            parameter_class=ParameterClass.C,
            current_value=100.0,
            recommended_value=120.0,
            within_bounds=True,
            rationale="Regime shift detected",
            expected_impact="Better entry timing",
            risk_notes="Non-stationary, regime-coupled",
        )
        assert rec.parameter_class == ParameterClass.C
        assert rec.regime_label is None  # Validator catches this, not model
