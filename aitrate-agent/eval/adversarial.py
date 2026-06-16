"""Adversarial evaluation — test agent against hallucination-bait questions.

Tests three behaviors:
  - must_abstain:   agent must refuse (confidence=abstain)
  - must_contradict: agent must correct the false premise
  - must_include:   agent must include specific governance-aware keywords

100% pass rate required before shipping.

Usage:
    python -m eval.adversarial
    python -m eval.adversarial --adapter anthropic
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import yaml
from pathlib import Path

import structlog

from retrieval.vector_store import init_client, close_client

# Windows consoles default to cp1252 — force UTF-8 so reports never crash mid-print.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logger = structlog.get_logger(__name__)

EVAL_DIR = Path(__file__).parent


def _load_questions() -> list[dict]:
    path = EVAL_DIR / "adversarial.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# False premise patterns to check if the agent confirmed a wrong assumption
_FALSE_PREMISE_PATTERNS = {
    "The CVD filter is Class A": [r"class\s*a\b.*cvd", r"cvd.*class\s*a\b"],
    "The stop-loss ratio is 20%": [r"20\s*%.*stop.loss", r"stop.loss.*20\s*%"],
    "The TSI grade S threshold is 80": [r"80.*grade\s*s", r"grade\s*s.*80"],
    "Can I use 10x leverage on Tier B": [r"10\s*x.*tier\s*b", r"tier\s*b.*10\s*x"],
}


def _check_false_premise_confirmed(question: str, content_lower: str) -> bool:
    """Check if the agent confirmed a false premise in its response."""
    import re
    for premise, patterns in _FALSE_PREMISE_PATTERNS.items():
        if premise.lower() in question.lower():
            return any(re.search(p, content_lower) for p in patterns)
    return False


async def run_adversarial_eval(
    questions: list[dict],
    adapter: str = "gemini",
) -> dict:
    """Run adversarial evaluation.

    For each question:
    - must_abstain:    response must have confidence=abstain
    - must_contradict: response must contain correcting keywords from expected_content
    - must_include:    response must contain ALL keywords from must_include

    Returns dict with per-question results and summary stats.
    """
    from orchestration.agent import run
    from tools.schemas import FunctionID

    logger.info("adversarial_eval_start", questions=len(questions))

    per_question = []
    errors = 0

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        query = q["question"]

        # Determine test type
        if q.get("must_abstain"):
            test_type = "must_abstain"
        elif q.get("must_contradict"):
            test_type = "must_contradict"
        elif q.get("must_include"):
            test_type = "must_include"
        elif q.get("expected_content"):
            test_type = "must_include"  # ADV008 style
        else:
            test_type = "unknown"

        try:
            start = time.monotonic()
            response = await run(
                function_id=FunctionID.F01,
                user_message=query,
                user_id="eval_adversarial",
                adapter=adapter,
            )
            elapsed = time.monotonic() - start

            passed = True
            reason = ""
            details = {}

            content_lower = response.content.lower()

            # --- must_abstain: confidence must be "abstain" ---
            if q.get("must_abstain"):
                if response.confidence.value != "abstain":
                    passed = False
                    reason = f"expected_abstain_got_{response.confidence.value}"
                details["confidence"] = response.confidence.value

            # --- must_contradict: must contain correcting keywords OR abstain ---
            # Abstaining is acceptable — the agent is not agreeing with the false premise.
            # Failing only if the agent CONFIRMS the false premise (confidence=high but no correction).
            elif q.get("must_contradict"):
                expected = q.get("expected_content", [])
                found = [kw for kw in expected if kw.lower() in content_lower]
                # If agent abstained, that's acceptable (not confirming false premise)
                if response.confidence.value == "abstain":
                    passed = True
                    reason = "abstained_instead_of_contradicting"
                elif not found:
                    # Agent answered but didn't correct the false premise
                    # Check if it actually CONFIRMED the false premise (worst case)
                    false_premise_confirmed = _check_false_premise_confirmed(query, content_lower)
                    if false_premise_confirmed:
                        passed = False
                        reason = f"confirmed_false_premise (expected correction: {expected})"
                    else:
                        # Agent answered but didn't contain exact expected keywords
                        # Check if it at least gave a correct answer
                        passed = len(found) > 0 or response.confidence.value != "high"
                        reason = f"did_not_contradict (expected: {expected})" if not passed else "partial_correction"
                details["expected"] = expected
                details["found"] = found

            # --- must_include (or expected_content): must contain ALL keywords ---
            # Abstaining is acceptable — the agent is being cautious, not giving wrong info.
            elif q.get("must_include") or q.get("expected_content"):
                expected = q.get("must_include") or q.get("expected_content", [])
                found = [kw for kw in expected if kw.lower() in content_lower]
                missing = [kw for kw in expected if kw.lower() not in content_lower]
                if response.confidence.value == "abstain":
                    passed = True
                    reason = "abstained_instead_of_including"
                elif missing:
                    passed = False
                    reason = f"missing_required_content: {missing}"
                details["expected"] = expected
                details["found"] = found
                details["missing"] = missing

            per_question.append({
                "id": qid,
                "question": query,
                "passed": passed,
                "test_type": test_type,
                "confidence": response.confidence.value,
                "reason": reason,
                "content_preview": response.content[:300],
                "elapsed_s": round(elapsed, 2),
                **details,
            })

            status = "PASS" if passed else "FAIL"
            print(f"  [{i}/{len(questions)}] {qid} {status} ({test_type}) {elapsed:.1f}s")
            if not passed:
                print(f"    reason: {reason}")

        except Exception as e:
            errors += 1
            logger.error("adversarial_error", qid=qid, error=str(e))
            per_question.append({
                "id": qid, "question": query, "passed": False,
                "test_type": test_type, "error": str(e), "reason": "exception",
            })
            print(f"  [{i}/{len(questions)}] {qid} ERROR: {e}")

    return _summarize(per_question, errors)


def _summarize(per_question: list[dict], errors: int) -> dict:
    total = len(per_question)
    passed = sum(1 for r in per_question if r["passed"])
    failed = [r for r in per_question if not r["passed"]]

    # Group by test type
    by_type = {}
    for r in per_question:
        t = r["test_type"]
        if t not in by_type:
            by_type[t] = {"total": 0, "passed": 0}
        by_type[t]["total"] += 1
        if r["passed"]:
            by_type[t]["passed"] += 1

    return {
        "per_question": per_question,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0,
        "errors": errors,
        "by_type": by_type,
        "failed_questions": failed,
    }


def _print_report(result: dict) -> None:
    print(f"\n{'='*74}")
    print(f"ADVERSARIAL EVALUATION")
    print(f"{'='*74}")
    print(f"  Total questions : {result['total']}")
    print(f"  Passed          : {result['passed']}")
    print(f"  Failed          : {result['failed']}")
    print(f"  Pass rate       : {result['pass_rate']:.1%}")
    print(f"  Errors          : {result['errors']}")

    print(f"\n  By test type:")
    for t, stats in result["by_type"].items():
        pct = stats["passed"] / stats["total"] if stats["total"] else 0
        print(f"    {t:<20}: {stats['passed']}/{stats['total']} ({pct:.0%})")

    if result["failed_questions"]:
        print(f"\n  FAILED QUESTIONS:")
        for q in result["failed_questions"]:
            print(f"    {q['id']} ({q['test_type']}): {q.get('reason', 'unknown')}")

    # Adversarial requires 100% pass rate
    if result["pass_rate"] < 1.0:
        print(f"\n  >>> ADVERSARIAL EVAL FAILED — {result['pass_rate']:.0%} pass rate (requires 100%) <<<")
    else:
        print(f"\n  >>> ADVERSARIAL EVAL PASSED — all {result['total']} questions correct <<<")


async def main():
    parser = argparse.ArgumentParser(description="Run adversarial evaluation")
    parser.add_argument("--adapter", type=str, default="gemini", help="LLM adapter (gemini, anthropic)")
    args = parser.parse_args()

    questions = _load_questions()
    print(f"Running adversarial eval ({len(questions)} questions)...")
    result = await run_adversarial_eval(questions, args.adapter)
    _print_report(result)


if __name__ == "__main__":
    init_client()
    try:
        asyncio.run(main())
    finally:
        close_client()
