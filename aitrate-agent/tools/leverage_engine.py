"""Leverage engine adapter — calls narrux_leverage.py for leverage calculations.

This is a thin adapter — the actual leverage logic lives in the existing NARRUX module.

NO framework imports. Pure Python + Pydantic.
"""

import subprocess
import json
import structlog
from pathlib import Path

from tools.schemas import (
    ParameterClass,
    ParameterRecommendationRequest,
    ParameterRecommendationResponse,
)

logger = structlog.get_logger(__name__)

# Path to the existing leverage engine
LEVERAGE_ENGINE_PATH = Path(__file__).parent.parent.parent.parent / "narrux_leverage.py"


async def recommend_parameter_adjustment(
    request: ParameterRecommendationRequest,
) -> ParameterRecommendationResponse:
    """Generate a parameter adjustment recommendation.

    This is the core of F-04. The recommendation logic:
    1. Look up parameter class (A/B/C)
    2. Check current value against valid range
    3. Consider regime context if available
    4. Generate recommendation within bounds
    5. Flag if human approval required (always True in v1)

    Args:
        request: Recommendation request with current parameter state.

    Returns:
        Parameter adjustment recommendation with rationale.
    """
    logger.info(
        "generating_recommendation",
        strategy_id=request.strategy_id,
        parameter=request.parameter_name,
        current_value=request.current_value,
    )

    # Try calling external leverage engine if available
    if LEVERAGE_ENGINE_PATH.exists():
        return await _call_external_leverage(request)

    # Fallback: generate recommendation based on parameter class rules
    return _generate_rule_based_recommendation(request)


async def _call_external_leverage(
    request: ParameterRecommendationRequest,
) -> ParameterRecommendationResponse:
    """Call the existing narrux_leverage.py as a subprocess."""
    logger.info("calling_external_leverage", path=str(LEVERAGE_ENGINE_PATH))

    input_data = json.dumps(
        {
            "strategy_id": request.strategy_id,
            "asset": request.asset,
            "parameter_name": request.parameter_name,
            "current_value": request.current_value,
            "context": request.context,
        }
    )

    try:
        result = subprocess.run(
            ["python", str(LEVERAGE_ENGINE_PATH), "--input", "-"],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error("leverage_engine_error", stderr=result.stderr)
            raise RuntimeError(f"Leverage engine failed: {result.stderr}")

        output = json.loads(result.stdout)
        return ParameterRecommendationResponse(
            strategy_id=request.strategy_id,
            parameter_name=request.parameter_name,
            parameter_class=ParameterClass(output["parameter_class"]),
            current_value=request.current_value,
            recommended_value=output["recommended_value"],
            range_min=output["range_min"],
            range_max=output["range_max"],
            confidence=output["confidence"],
            rationale=output["rationale"],
            risks=output.get("risks", []),
            requires_approval=True,
            citation="narrux_leverage.py",
        )
    except Exception as e:
        logger.warning("external_leverage_failed", error=str(e), fallback="rule-based")
        return _generate_rule_based_recommendation(request)


def _generate_rule_based_recommendation(
    request: ParameterRecommendationRequest,
) -> ParameterRecommendationResponse:
    """Generate a rule-based recommendation when external engine is unavailable.

    This implements the NARRUX parameter governance rules:
    - Class A: Don't touch. Set & forget.
    - Class B: Quarterly drift. Recommend within validated range.
    - Class C: Regime-coupled. Flag for regime assessment.
    """
    logger.info("generating_rule_based_recommendation", parameter=request.parameter_name)

    # Default ranges (would come from BDE config in production)
    default_ranges = {
        "stop_loss_pct": {"class": "B", "min": 1.0, "max": 4.0, "baseline": 2.25},
        "take_profit_pct": {"class": "B", "min": 3.0, "max": 10.0, "baseline": 5.0},
        "trailing_stop_pct": {"class": "B", "min": 0.5, "max": 3.0, "baseline": 1.5},
        "volume_threshold": {"class": "C", "min": 0.5, "max": 2.0, "baseline": 1.0},
    }

    param_config = default_ranges.get(request.parameter_name)
    if not param_config:
        # Unknown parameter — conservative recommendation
        return ParameterRecommendationResponse(
            strategy_id=request.strategy_id,
            parameter_name=request.parameter_name,
            parameter_class=ParameterClass.B,
            current_value=request.current_value,
            recommended_value=request.current_value,  # No change
            range_min=request.current_value * 0.8,
            range_max=request.current_value * 1.2,
            confidence=0.3,
            rationale=(
                f"Unknown parameter '{request.parameter_name}'. "
                "No validated range available. Recommend keeping current value "
                "until BDE classifies this parameter."
            ),
            risks=["Parameter not yet classified by BDE"],
            requires_approval=True,
            citation="Rule-based fallback (parameter not in known config)",
        )

    param_class = ParameterClass(param_config["class"])
    baseline = param_config["baseline"]
    range_min = param_config["min"]
    range_max = param_config["max"]

    # Class A: Don't touch
    if param_class == ParameterClass.A:
        return ParameterRecommendationResponse(
            strategy_id=request.strategy_id,
            parameter_name=request.parameter_name,
            parameter_class=param_class,
            current_value=request.current_value,
            recommended_value=request.current_value,
            range_min=range_min,
            range_max=range_max,
            confidence=0.95,
            rationale=(
                f"Parameter '{request.parameter_name}' is Class A (set & forget). "
                "It has been stable for 12+ months and should not be adjusted. "
                "Any change requires explicit override approval."
            ),
            risks=["Class A parameters should not be changed without compelling evidence"],
            requires_approval=True,
            citation="NARRUX Parameter Classification Framework",
        )

    # Class B: Recommend within range
    if param_class == ParameterClass.B:
        # Check if current value is out of range
        if request.current_value < range_min or request.current_value > range_max:
            recommended = baseline  # Reset to baseline if out of range
            confidence = 0.8
            rationale = (
                f"Parameter '{request.parameter_name}' is Class B (quarterly drift). "
                f"Current value {request.current_value} is outside validated range "
                f"[{range_min}, {range_max}]. Recommend reset to baseline {baseline}."
            )
            risks = [
                f"Resetting from {request.current_value} to {baseline}",
                "Validate against recent backtest before applying",
            ]
        else:
            # Within range — recommend baseline if significantly different
            delta_pct = abs(request.current_value - baseline) / baseline * 100
            if delta_pct > 15:
                recommended = round((request.current_value + baseline) / 2, 2)
                confidence = 0.6
                rationale = (
                    f"Parameter '{request.parameter_name}' is Class B. "
                    f"Current value {request.current_value} deviates {delta_pct:.0f}% "
                    f"from baseline {baseline}. Recommend gradual adjustment toward baseline."
                )
                risks = ["Gradual adjustment — verify with backtest before applying"]
            else:
                recommended = request.current_value
                confidence = 0.9
                rationale = (
                    f"Parameter '{request.parameter_name}' is Class B and within "
                    f"acceptable range. Current value {request.current_value} is "
                    f"close to baseline {baseline}. No change recommended."
                )
                risks = []

        return ParameterRecommendationResponse(
            strategy_id=request.strategy_id,
            parameter_name=request.parameter_name,
            parameter_class=param_class,
            current_value=request.current_value,
            recommended_value=recommended,
            range_min=range_min,
            range_max=range_max,
            confidence=confidence,
            rationale=rationale,
            risks=risks,
            requires_approval=True,
            citation="NARRUX Parameter Classification Framework + BDE validated ranges",
        )

    # Class C: Regime-coupled — flag for regime assessment
    return ParameterRecommendationResponse(
        strategy_id=request.strategy_id,
        parameter_name=request.parameter_name,
        parameter_class=param_class,
        current_value=request.current_value,
        recommended_value=request.current_value,  # Don't change without regime data
        range_min=range_min,
        range_max=range_max,
        confidence=0.4,
        rationale=(
            f"Parameter '{request.parameter_name}' is Class C (regime-coupled). "
            "Recommendation requires current regime classification from AGE/RCE. "
            "Without live regime data, recommend maintaining current value."
        ),
        risks=[
            "Class C parameters are unstable under regime changes",
            "Requires AGE Phase G2+ for accurate recommendation",
            "Manual regime assessment needed until AGE is live",
        ],
        requires_approval=True,
        citation="NARRUX Parameter Classification Framework (regime-coupled)",
    )
