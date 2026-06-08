"""Adversarial evaluation — test agent against hallucination-bait questions.

All questions must return ABSTAIN or correct-contradict.
100% pass rate required before shipping.

Stub — requires running DB + LLM API keys.
"""

from __future__ import annotations

import asyncio
import yaml
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


async def run_adversarial_eval(questions_path: str, adapter: str = "pydantic_ai"):
    """Run adversarial evaluation.

    For each question:
    - must_abstain: response must have confidence=abstain
    - must_contradict: response must contradict the false premise
    - must_include: response must contain these keywords
    """
    from orchestration.agent import run
    from tools.schemas import FunctionID

    with open(questions_path, "r", encoding="utf-8") as f:
        questions = yaml.safe_load(f)

    logger.info("adversarial_eval_start", questions=len(questions))

    results = []
    for q in questions:
        qid = q["id"]

        try:
            response = await run(
                function_id=FunctionID.F01,
                user_message=q["question"],
                user_id="eval_adversarial",
                adapter=adapter,
            )

            passed = True
            reason = ""

            # Check must_abstain
            if q.get("must_abstain"):
                if response.confidence.value != "abstain":
                    passed = False
                    reason = "should_have_abstained"

            # Check must_contradict
            if q.get("must_contradict"):
                expected = q.get("expected_content", [])
                content_lower = response.content.lower()
                if not any(kw.lower() in content_lower for kw in expected):
                    passed = False
                    reason = "did_not_contradict"

            # Check must_include
            if q.get("must_include"):
                expected = q["must_include"]
                content_lower = response.content.lower()
                if not all(kw.lower() in content_lower for kw in expected):
                    passed = False
                    reason = "missing_required_content"

            results.append({"id": qid, "passed": passed, "reason": reason})

        except Exception as e:
            logger.error("adversarial_error", qid=qid, error=str(e))
            results.append({"id": qid, "passed": False, "error": str(e)})

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\nAdversarial Evaluation: {passed_count}/{len(results)} passed ({passed_count/len(results):.0%})")
    if passed_count < len(results):
        print("FAILED questions:")
        for r in results:
            if not r["passed"]:
                print(f"  {r['id']}: {r.get('reason', r.get('error', 'unknown'))}")

    return results


if __name__ == "__main__":
    import sys

    async def main():
        questions_path = sys.argv[1] if len(sys.argv) > 1 else "eval/adversarial.yaml"
        await run_adversarial_eval(questions_path)

    asyncio.run(main())
