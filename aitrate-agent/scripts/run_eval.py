"""Evaluation harness — run eval questions against the agent.

Usage:
    python scripts/run_eval.py --pillar A
    python scripts/run_eval.py --all
"""

import asyncio
import json
import argparse
from pathlib import Path

from config.settings import get_settings
from db.session import async_session_factory
from retrieval.embeddings import EmbeddingClient
from retrieval.vector_store import VectorStore
from retrieval.reranker import Reranker


async def run_eval(pillar: str = "A"):
    """Run evaluation for a specific pillar."""
    settings = get_settings()

    # Load eval questions
    eval_dir = Path(__file__).parent.parent / "eval" / "questions"
    question_file = eval_dir / f"pillar_{pillar.lower()}.json"

    if not question_file.exists():
        print(f"Error: Question file not found: {question_file}")
        return

    with open(question_file, "r") as f:
        questions = json.load(f)

    print(f"Running eval for Pillar {pillar}: {len(questions)} questions")

    async with async_session_factory() as session:
        embeddings = EmbeddingClient()
        vector_store = VectorStore(session, embeddings)
        reranker = Reranker()

        results = []
        for i, q in enumerate(questions, 1):
            print(f"\n[{i}/{len(questions)}] {q['question'][:80]}...")

            # Retrieve
            search_results = await vector_store.search(
                query=q["question"],
                top_k=settings.retrieval_top_k,
            )

            # Rerank
            reranked = await reranker.rerank(
                query=q["question"],
                results=search_results,
                top_n=settings.retrieval_top_n,
            )

            # Check if any result contains the expected answer
            expected_keywords = q.get("keywords", [])
            found_keywords = []
            for result in reranked:
                for keyword in expected_keywords:
                    if keyword.lower() in result.content.lower():
                        found_keywords.append(keyword)

            recall = len(set(found_keywords)) / len(expected_keywords) if expected_keywords else 0.0

            results.append({
                "question": q["question"],
                "expected_keywords": expected_keywords,
                "found_keywords": list(set(found_keywords)),
                "recall": recall,
                "top_similarity": reranked[0].similarity if reranked else 0.0,
            })

            print(f"  Recall: {recall:.2%} ({len(set(found_keywords))}/{len(expected_keywords)} keywords)")

        # Summary
        avg_recall = sum(r["recall"] for r in results) / len(results) if results else 0.0
        avg_similarity = sum(r["top_similarity"] for r in results) / len(results) if results else 0.0

        print(f"\n{'='*60}")
        print(f"Pillar {pillar} Eval Summary:")
        print(f"  Questions: {len(results)}")
        print(f"  Average Recall: {avg_recall:.2%}")
        print(f"  Average Top Similarity: {avg_similarity:.4f}")
        print(f"  Min Recall Threshold: {settings.eval_min_recall_at_5:.2%}")
        print(f"  PASSED: {'✓' if avg_recall >= settings.eval_min_recall_at_5 else '✗'}")

        return results


async def main():
    parser = argparse.ArgumentParser(description="Run aiTrate agent evaluation")
    parser.add_argument("--pillar", type=str, default="A", help="Pillar to evaluate (A, B, C)")
    parser.add_argument("--all", action="store_true", help="Evaluate all pillars")

    args = parser.parse_args()

    if args.all:
        for pillar in ["A", "B", "C"]:
            await run_eval(pillar)
    else:
        await run_eval(args.pillar)


if __name__ == "__main__":
    asyncio.run(main())
