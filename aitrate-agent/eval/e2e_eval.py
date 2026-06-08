"""End-to-end evaluation — run full agent pipeline, score with ragas.

Stub — requires running DB + LLM API keys.
Full implementation after retrieval quality is validated.
"""

from __future__ import annotations

import asyncio
import yaml
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


async def run_e2e_eval(questions_path: str, adapter: str = "pydantic_ai"):
    """Run end-to-end evaluation.

    For each question:
    1. Call the agent pipeline
    2. Check expected_content keywords in response
    3. Check must_abstain flag
    4. Score factual accuracy

    Requires: DB running, LLM API keys configured.
    """
    from orchestration.agent import run
    from tools.schemas import FunctionID

    with open(questions_path, "r", encoding="utf-8") as f:
        questions = yaml.safe_load(f)

    logger.info("e2e_eval_start", questions=len(questions))

    results = []
    for q in questions:
        function_id = FunctionID.F01  # Default; override based on question pillar
        qid = q["id"]

        try:
            response = await run(
                function_id=function_id,
                user_message=q["question"],
                user_id="eval",
                adapter=adapter,
            )

            # Check abstain
            if q.get("must_abstain"):
                passed = response.confidence.value == "abstain"
            else:
                # Check expected content keywords
                expected = q.get("expected_content", [])
                content_lower = response.content.lower()
                keyword_hits = sum(1 for kw in expected if kw.lower() in content_lower)
                passed = keyword_hits >= len(expected) * 0.5  # 50% keyword match threshold

            results.append({"id": qid, "passed": passed, "confidence": response.confidence.value})

        except Exception as e:
            logger.error("eval_error", qid=qid, error=str(e))
            results.append({"id": qid, "passed": False, "error": str(e)})

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\nE2E Evaluation: {passed_count}/{len(results)} passed ({passed_count/len(results):.0%})")

    return results


if __name__ == "__main__":
    import sys

    async def main():
        questions_path = sys.argv[1] if len(sys.argv) > 1 else "eval/pillar_a_questions.yaml"
        await run_e2e_eval(questions_path)

    asyncio.run(main())
