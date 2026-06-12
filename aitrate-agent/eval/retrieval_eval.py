"""Retrieval evaluation — measure recall@K and MRR on known-answer questions.

Usage:
    python -m eval.retrieval_eval --questions eval/pillar_a_questions.yaml
"""

from __future__ import annotations

import asyncio
import yaml
from pathlib import Path

import structlog

from retrieval.embeddings import embed_query
from retrieval.reranker import rerank
from retrieval.vector_store import init_client, close_client, similarity_search

logger = structlog.get_logger(__name__)


async def evaluate_recall(
    questions: list[dict],
    top_k: int = 20,
    rerank_n: int = 5,
) -> dict:
    """Evaluate recall@K on a set of questions.

    For each question, check if expected_citations appear in top-K results.
    Returns recall@K and MRR.
    """
    hits = 0
    rr_sum = 0.0
    total = 0

    for q in questions:
        if q.get("must_abstain"):
            continue

        expected_citations = q.get("expected_citations", [])
        if not expected_citations:
            continue

        total += 1
        query = q["question"]
        query_embedding = await embed_query(query)
        chunks = await similarity_search(query_embedding=query_embedding, top_k=top_k)
        ranked = await rerank(query, chunks, top_n=rerank_n)

        # Check if any expected citation appears in results
        result_doc_ids = {rc.chunk.doc_id for rc in ranked}

        for expected in expected_citations:
            if expected in result_doc_ids:
                hits += 1
                # Find rank
                for i, rc in enumerate(ranked):
                    if rc.chunk.doc_id == expected:
                        rr_sum += 1.0 / (i + 1)
                        break
                break

    recall = hits / total if total > 0 else 0
    mrr = rr_sum / total if total > 0 else 0

    return {
        "recall_at_k": round(recall, 4),
        "mrr": round(mrr, 4),
        "total_questions": total,
        "hits": hits,
    }


async def run_eval(questions_path: str, top_k: int = 20, rerank_n: int = 5):
    """Run retrieval evaluation from a YAML file."""
    with open(questions_path, "r", encoding="utf-8") as f:
        questions = yaml.safe_load(f)

    logger.info("eval_start", questions=len(questions), top_k=top_k)

    results = await evaluate_recall(questions, top_k, rerank_n)

    print(f"\nRetrieval Evaluation Results:")
    print(f"  Questions: {results['total_questions']}")
    print(f"  Hits: {results['hits']}")
    print(f"  Recall@{top_k}: {results['recall_at_k']:.2%}")
    print(f"  MRR: {results['mrr']:.2%}")

    return results


if __name__ == "__main__":
    import sys

    async def main():
        init_client()
        try:
            questions_path = sys.argv[1] if len(sys.argv) > 1 else "eval/pillar_a_questions.yaml"
            await run_eval(questions_path)
        finally:
            close_client()

    asyncio.run(main())
