"""End-to-end evaluation — run full agent pipeline, score with ragas.

Runs each question through the full RAG pipeline (retrieve → rerank → LLM → respond)
and checks expected_content keyword matching + must_abstain flags.

Usage:
    python -m eval.e2e_eval --pillar A
    python -m eval.e2e_eval --all
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

# Pillar → default FunctionID mapping
PILLAR_FUNCTION = {
    "A": "F-01",   # Strategy Knowledge
    "B": "F-02",   # Backtest Interpreter
    "C": "F-04",   # Parameter Recommender
}


def _load_questions(pillar: str) -> list[dict]:
    path = EVAL_DIR / f"pillar_{pillar.lower()}_questions.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def run_e2e_eval(
    questions: list[dict],
    pillar: str,
    adapter: str = "gemini",
    keyword_threshold: float = 0.5,
) -> dict:
    """Run end-to-end evaluation for a set of questions.

    For each question:
    1. Call the agent pipeline (retrieve → rerank → LLM → respond)
    2. Check must_abstain flag (confidence must be 'abstain')
    3. Check expected_content keywords in response (50% threshold default)

    Returns dict with per-question results and summary stats.
    """
    from orchestration.agent import run
    from tools.schemas import FunctionID

    function_id = FunctionID(PILLAR_FUNCTION.get(pillar, "F01"))
    logger.info("e2e_eval_start", pillar=pillar, questions=len(questions), function_id=function_id.value)

    per_question = []
    skipped_abstain = 0
    errors = 0

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        query = q["question"]

        if q.get("must_abstain"):
            skipped_abstain += 1
            # Still test must_abstain questions — agent SHOULD abstain
            try:
                start = time.monotonic()
                response = await run(
                    function_id=function_id,
                    user_message=query,
                    user_id="eval_e2e",
                    adapter=adapter,
                )
                elapsed = time.monotonic() - start

                passed = response.confidence.value == "abstain"
                per_question.append({
                    "id": qid,
                    "question": query,
                    "passed": passed,
                    "test_type": "must_abstain",
                    "confidence": response.confidence.value,
                    "content_preview": response.content[:200],
                    "elapsed_s": round(elapsed, 2),
                    "reason": "" if passed else f"expected_abstain_got_{response.confidence.value}",
                })

                status = "PASS" if passed else "FAIL"
                print(f"  [{i}/{len(questions)}] {qid} {status} (abstain test, got {response.confidence.value})")

            except Exception as e:
                errors += 1
                logger.error("e2e_error", qid=qid, error=str(e))
                per_question.append({
                    "id": qid, "question": query, "passed": False,
                    "test_type": "must_abstain", "error": str(e), "reason": "exception",
                })
                print(f"  [{i}/{len(questions)}] {qid} ERROR: {e}")

            continue

        # Normal question — check expected_content keywords
        expected = q.get("expected_content") or q.get("must_include") or []
        if not expected:
            continue

        try:
            start = time.monotonic()
            response = await run(
                function_id=function_id,
                user_message=query,
                user_id="eval_e2e",
                adapter=adapter,
            )
            elapsed = time.monotonic() - start

            content_lower = response.content.lower()
            found = [kw for kw in expected if kw.lower() in content_lower]
            missing = [kw for kw in expected if kw.lower() not in content_lower]
            keyword_recall = len(found) / len(expected) if expected else 0.0
            passed = keyword_recall >= keyword_threshold

            per_question.append({
                "id": qid,
                "question": query,
                "passed": passed,
                "test_type": "keyword_match",
                "confidence": response.confidence.value,
                "keyword_recall": round(keyword_recall, 3),
                "found_keywords": found,
                "missing_keywords": missing,
                "content_preview": response.content[:300],
                "elapsed_s": round(elapsed, 2),
                "reason": "" if passed else f"low_recall_{keyword_recall:.0%}",
            })

            status = "PASS" if passed else "FAIL"
            print(f"  [{i}/{len(questions)}] {qid} {status} "
                  f"(recall {keyword_recall:.0%}, {len(found)}/{len(expected)} keywords, {elapsed:.1f}s)")

        except Exception as e:
            errors += 1
            logger.error("e2e_error", qid=qid, error=str(e))
            per_question.append({
                "id": qid, "question": query, "passed": False,
                "test_type": "keyword_match", "error": str(e), "reason": "exception",
            })
            print(f"  [{i}/{len(questions)}] {qid} ERROR: {e}")

    return _summarize(per_question, skipped_abstain, errors)


def _summarize(per_question: list[dict], skipped_abstain: int, errors: int) -> dict:
    total = len(per_question)
    passed = sum(1 for r in per_question if r["passed"])
    failed = [r for r in per_question if not r["passed"]]

    return {
        "per_question": per_question,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0,
        "skipped_abstain": skipped_abstain,
        "errors": errors,
        "failed_questions": failed,
    }


def _print_report(pillar: str, result: dict) -> None:
    print(f"\n{'='*74}")
    print(f"E2E EVALUATION — Pillar {pillar}")
    print(f"{'='*74}")
    print(f"  Total questions : {result['total']}")
    print(f"  Passed          : {result['passed']}")
    print(f"  Failed          : {result['failed']}")
    print(f"  Pass rate       : {result['pass_rate']:.1%}")
    print(f"  Errors          : {result['errors']}")

    if result["failed_questions"]:
        print(f"\n  FAILED QUESTIONS:")
        for q in result["failed_questions"]:
            print(f"    {q['id']}: {q.get('reason', 'unknown')}")
            if q.get("missing_keywords"):
                print(f"      missing: {q['missing_keywords']}")


async def run_all(adapter: str = "gemini", keyword_threshold: float = 0.5) -> None:
    """Run E2E evaluation on all pillars."""
    all_results = {}

    for pillar in ("A", "B", "C"):
        questions = _load_questions(pillar)
        print(f"\nRunning E2E eval for Pillar {pillar} ({len(questions)} questions)...")
        result = await run_e2e_eval(questions, pillar, adapter, keyword_threshold)
        _print_report(pillar, result)
        all_results[pillar] = result

    # Overall summary
    total = sum(r["total"] for r in all_results.values())
    passed = sum(r["passed"] for r in all_results.values())
    print(f"\n{'='*74}")
    print(f"OVERALL E2E RESULTS")
    print(f"{'='*74}")
    print(f"  Total   : {total}")
    print(f"  Passed  : {passed}")
    print(f"  Failed  : {total - passed}")
    print(f"  Pass rate: {passed/total:.1%}" if total else "  No questions evaluated")


async def main():
    parser = argparse.ArgumentParser(description="Run end-to-end agent evaluation")
    parser.add_argument("--pillar", type=str, help="Pillar to evaluate (A, B, or C)")
    parser.add_argument("--all", action="store_true", help="Evaluate all pillars (A, B, C)")
    parser.add_argument("--adapter", type=str, default="gemini", help="LLM adapter (gemini, anthropic)")
    parser.add_argument("--threshold", type=float, default=0.5, help="Keyword match threshold (0-1)")
    args = parser.parse_args()

    if args.all:
        await run_all(args.adapter, args.threshold)
    elif args.pillar:
        questions = _load_questions(args.pillar)
        print(f"Running E2E eval for Pillar {args.pillar} ({len(questions)} questions)...")
        result = await run_e2e_eval(questions, args.pillar, args.adapter, args.threshold)
        _print_report(args.pillar, result)
    else:
        parser.error("Specify --all or --pillar {A|B|C}")


if __name__ == "__main__":
    init_client()
    try:
        asyncio.run(main())
    finally:
        close_client()
