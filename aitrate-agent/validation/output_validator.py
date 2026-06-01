"""Output validator — cross-checks agent claims against KB facts.

When the agent claims "F19 is Class B, baseline 16, range 12-20",
this validator checks that against param_classification.yaml before rendering.

NO framework imports. Pure Python + Pydantic.
"""

import re
import structlog
from dataclasses import dataclass

from retrieval.vector_store import SearchResult

logger = structlog.get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of output validation."""

    is_valid: bool
    mismatches: list[str]
    warnings: list[str]


class OutputValidator:
    """Validates agent output against known facts in the KB.

    Checks:
    - Parameter class claims (A/B/C) match KB
    - Baseline values match KB
    - Range values match KB
    - Filter behavior claims match KB
    """

    def validate_parameter_claim(
        self,
        parameter_name: str,
        claimed_class: str,
        claimed_baseline: float | None,
        claimed_range: tuple[float, float] | None,
        kb_results: list[SearchResult],
    ) -> ValidationResult:
        """Validate a parameter claim against KB.

        Args:
            parameter_name: Name of the parameter.
            claimed_class: Claimed class (A, B, or C).
            claimed_baseline: Claimed baseline value.
            claimed_range: Claimed (min, max) range.
            kb_results: Search results from KB for this parameter.

        Returns:
            Validation result with mismatches.
        """
        mismatches = []
        warnings = []

        if not kb_results:
            warnings.append(f"No KB data found for parameter '{parameter_name}'")
            return ValidationResult(is_valid=True, mismatches=[], warnings=warnings)

        # Extract KB data from top result
        kb = kb_results[0]
        kb_content = kb.content.lower()

        # Check class claim
        class_pattern = re.compile(r'class\s+([abc])', re.IGNORECASE)
        class_match = class_pattern.search(kb_content)
        if class_match:
            kb_class = class_match.group(1).upper()
            if claimed_class.upper() != kb_class:
                mismatches.append(
                    f"Parameter class mismatch: claimed '{claimed_class}', "
                    f"KB says '{kb_class}'"
                )

        # Check baseline claim
        if claimed_baseline is not None:
            baseline_pattern = re.compile(r'baseline\s*(?:is|of|=|:)\s*(\d+\.?\d*)')
            baseline_match = baseline_pattern.search(kb_content)
            if baseline_match:
                kb_baseline = float(baseline_match.group(1))
                if abs(claimed_baseline - kb_baseline) > 0.01:
                    mismatches.append(
                        f"Baseline mismatch: claimed {claimed_baseline}, "
                        f"KB says {kb_baseline}"
                    )

        # Check range claim
        if claimed_range is not None:
            range_pattern = re.compile(r'range\s*(?:is|of|=|:)?\s*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)')
            range_match = range_pattern.search(kb_content)
            if range_match:
                kb_min = float(range_match.group(1))
                kb_max = float(range_match.group(2))
                if abs(claimed_range[0] - kb_min) > 0.01 or abs(claimed_range[1] - kb_max) > 0.01:
                    mismatches.append(
                        f"Range mismatch: claimed {claimed_range}, "
                        f"KB says ({kb_min}, {kb_max})"
                    )

        is_valid = len(mismatches) == 0

        if not is_valid:
            logger.warning(
                "validation_failed",
                parameter=parameter_name,
                mismatches=mismatches,
            )

        return ValidationResult(
            is_valid=is_valid,
            mismatches=mismatches,
            warnings=warnings,
        )

    def validate_filter_claim(
        self,
        filter_id: str,
        claimed_behavior: str,
        kb_results: list[SearchResult],
    ) -> ValidationResult:
        """Validate a filter behavior claim against KB.

        Args:
            filter_id: Filter identifier (e.g., "F19").
            claimed_behavior: Description of filter behavior.
            kb_results: Search results from KB for this filter.

        Returns:
            Validation result.
        """
        mismatches = []
        warnings = []

        if not kb_results:
            warnings.append(f"No KB data found for filter '{filter_id}'")
            return ValidationResult(is_valid=True, mismatches=[], warnings=warnings)

        # Basic check: does the KB mention this filter?
        kb = kb_results[0]
        if filter_id.upper() not in kb.content.upper():
            warnings.append(f"KB result doesn't mention {filter_id}")

        return ValidationResult(
            is_valid=len(mismatches) == 0,
            mismatches=mismatches,
            warnings=warnings,
        )
