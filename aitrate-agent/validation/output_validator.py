"""Output validator — function-specific validation of agent responses.

NO pydantic_ai imports. Pure Python + Pydantic.
"""

import structlog

from tools.schemas import AgentResponse, ConfidenceLevel, FunctionID

logger = structlog.get_logger(__name__)

# Class C component names for the check_class_c_flagged validator
CLASS_C_COMPONENTS = [
    "cvd",
    "cumulative volume delta",
    "cmf",
    "chaikin money flow",
    "mfi",
    "money flow index",
    "volume exhaustion",
    "spike exit",
    "momentum override",
]


def validate_response(response: AgentResponse) -> AgentResponse:
    """Run function-specific validators based on response.function_id.

    F-04 → validate_recommendations
    F-02 → validate_backtest_response
    F-05 → validate_drift_response
    All → check_class_c_flagged

    If any validator fails AND confidence==HIGH → downgrade to MEDIUM.
    """
    issues: list[str] = []

    if response.function_id == FunctionID.F04:
        issues.extend(validate_recommendations(response).get("issues", []))
    elif response.function_id == FunctionID.F02:
        issues.extend(validate_backtest_response(response).get("issues", []))
    elif response.function_id == FunctionID.F05:
        issues.extend(validate_drift_response(response).get("issues", []))

    # All responses: check Class C flagged
    issues.extend(check_class_c_flagged(response).get("issues", []))

    if issues and response.confidence == ConfidenceLevel.high:
        logger.warning("validation_downgrading", issues=issues)
        response = response.model_copy(
            update={
                "confidence": ConfidenceLevel.medium,
                "validator_results": {
                    **(response.validator_results or {}),
                    "output_validator": {"issues": issues},
                },
            }
        )

    return response


def validate_recommendations(response: AgentResponse) -> dict:
    """Validate parameter recommendations (F-04).

    - Class A proposal → log warning
    - Class B with evidence_count < 3 → issue
    - Class C without regime_label → issue
    - within_bounds=False → issue
    """
    issues: list[str] = []

    if not response.structured_output:
        return {"issues": issues}

    recommendations = response.structured_output.get("recommendations", [])
    for rec in recommendations:
        name = rec.get("parameter_name", "unknown")
        param_class = rec.get("parameter_class")
        evidence_count = rec.get("evidence_backtest_count", 0)
        regime_label = rec.get("regime_label")
        within_bounds = rec.get("within_bounds", True)

        if param_class == "A":
            logger.warning("class_a_proposal", parameter=name)
            issues.append(f"class_a_proposal:{name}")

        if param_class == "B" and evidence_count < 3:
            issues.append(f"class_b_insufficient_evidence:{name}:{evidence_count}<3")

        if param_class == "C" and not regime_label:
            issues.append(f"class_c_missing_regime_label:{name}")

        if not within_bounds:
            issues.append(f"out_of_bounds:{name}")

    return {"issues": issues}


def validate_backtest_response(response: AgentResponse) -> dict:
    """Validate backtest interpretation (F-02).

    Check content contains required terms.
    Check stop-loss ratio flagging.
    """
    issues: list[str] = []
    content = response.content.lower()

    # Required terms
    required = [
        (["tsi", "grade", "score"], "missing_tsi_reference"),
        (["p&l", "pnl", "profit", "return", "net"], "missing_pnl_reference"),
        (["capital basis", "initial capital", "returns basis"], "missing_capital_basis"),
    ]

    for terms, issue_name in required:
        if not any(t in content for t in terms):
            issues.append(issue_name)

    # Check stop-loss ratio flagging
    if response.structured_output:
        sl_ratio = response.structured_output.get("stop_loss_ratio", 0)
        if sl_ratio > 0.40:
            if "stop.loss ratio" not in content and "sl ratio" not in content:
                issues.append("high_sl_ratio_not_flagged")

    return {"issues": issues}


def validate_drift_response(response: AgentResponse) -> dict:
    """Validate drift monitoring (F-05).

    Check for authority role and drift status in content.
    """
    issues: list[str] = []
    content = response.content.lower()

    if not any(t in content for t in ["advisory", "veto", "override"]):
        issues.append("missing_authority_role")

    if not any(t in content for t in ["stable", "watch", "breach"]):
        issues.append("missing_drift_status")

    return {"issues": issues}


def check_class_c_flagged(response: AgentResponse) -> dict:
    """Check that Class C components are properly flagged.

    If any Class C component is mentioned without regime/non-stationary warning → fail.
    """
    issues: list[str] = []
    content = response.content.lower()

    mentioned_components = [comp for comp in CLASS_C_COMPONENTS if comp in content]

    if mentioned_components:
        warning_terms = ["regime", "class c", "non-stationary", "regime-coupled", "volume-based"]
        has_warning = any(t in content for t in warning_terms)
        if not has_warning:
            for comp in mentioned_components:
                issues.append(f"class_c_not_flagged:{comp}")

    return {"issues": issues}
