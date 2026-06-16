"""Retrieval evaluation — keyword recall over the reranked context.

Measures two things per question:
  - recall@N (post-rerank): do the expected keywords appear in the final
    top-N chunks the agent feeds to the LLM? This is the real RAG signal.
  - recall@K (pre-rerank): do the keywords appear anywhere in the raw
    top-K vector-search candidates? The gap vs recall@N shows rerank/
    truncation loss.

Ground truth comes from `expected_content` keywords (present on every
non-abstain question). Citation recall (`expected_citations`) is also
reported where labelled — but only A001 carries it, so keyword recall is
the primary metric.

Usage:
    python -m eval.retrieval_eval --all
    python -m eval.retrieval_eval --pillar A
    python -m eval.retrieval_eval eval/pillar_a_questions.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import yaml
from pathlib import Path

import structlog

# Windows consoles default to cp1252/cp437 — keep output ASCII-only and force UTF-8
# so box drawing / status glyphs never raise UnicodeEncodeError mid-report.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
logging.basicConfig(level=logging.WARNING)  # silence structlog INFO noise

from retrieval.embeddings import embed_query
from retrieval.reranker import rerank
from retrieval.vector_store import init_client, close_client, similarity_search

logger = structlog.get_logger(__name__)

EVAL_DIR = Path(__file__).parent


def _load_questions(pillar: str) -> list[dict]:
    path = EVAL_DIR / f"pillar_{pillar.lower()}_questions.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _keyword_recall(keywords: list[str], corpus: str) -> tuple[float, list[str]]:
    """Fraction of keywords present in corpus (case-insensitive). Returns (recall, missing)."""
    corpus_lower = corpus.lower()
    found = [kw for kw in keywords if kw.lower() in corpus_lower]
    missing = [kw for kw in keywords if kw.lower() not in corpus_lower]
    recall = len(found) / len(keywords) if keywords else 0.0
    return recall, missing


async def evaluate_recall(
    questions: list[dict],
    top_k: int = 20,
    rerank_n: int = 5,
) -> dict:
    """Citation recall@K + MRR — only meaningful where expected_citations are labelled."""
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

        result_doc_ids = {rc.chunk.doc_id for rc in ranked}
        for expected in expected_citations:
            if expected in result_doc_ids:
                hits += 1
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


async def evaluate_keyword_recall(
    questions: list[dict],
    top_k: int = 20,
    rerank_n: int = 5,
) -> dict:
    """Keyword recall over the reranked context — the primary RAG retrieval metric."""
    per_question = []
    skipped_abstain = 0
    errors = 0

    for q in questions:
        qid = q["id"]
        keywords = q.get("expected_content") or q.get("must_include") or []

        # must_abstain questions test abstention (needs the LLM), not retrieval.
        if q.get("must_abstain"):
            skipped_abstain += 1
            continue
        if not keywords:
            continue

        try:
            query = q["question"]
            query_embedding = await embed_query(query)
            chunks = await similarity_search(query_embedding=query_embedding, top_k=top_k)
            ranked = await rerank(query, chunks, top_n=rerank_n)

            context_n = " ".join(rc.chunk.content for rc in ranked)  # final LLM context
            context_k = " ".join(c.content for c in chunks)          # raw candidate pool
            recall_n, missing_n = _keyword_recall(keywords, context_n)
            recall_k, _ = _keyword_recall(keywords, context_k)
            top_sim = ranked[0].score if ranked else 0.0

            per_question.append({
                "id": qid,
                "question": query,
                "recall_at_n": recall_n,
                "recall_at_k": recall_k,
                "top_similarity": top_sim,
                "missing": missing_n,
                "n_chunks_context": len(ranked),
            })
        except Exception as e:
            errors += 1
            logger.error("eval_question_error", qid=qid, error=str(e))
            per_question.append({
                "id": qid, "question": q["question"], "recall_at_n": 0.0,
                "recall_at_k": 0.0, "top_similarity": 0.0, "missing": keywords,
                "n_chunks_context": 0, "error": str(e),
            })

    n = len(per_question)
    avg = lambda key: sum(p[key] for p in per_question) / n if n else 0.0
    perfect = sum(1 for p in per_question if p["recall_at_n"] >= 1.0)
    failed = [p for p in per_question if p["recall_at_n"] < 0.5]

    return {
        "per_question": per_question,
        "avg_recall_at_n": round(avg("recall_at_n"), 4),
        "avg_recall_at_k": round(avg("recall_at_k"), 4),
        "avg_top_similarity": round(avg("top_similarity"), 4),
        "perfect_recall_count": perfect,
        "failed_count": len(failed),
        "failed": failed,
        "questions_evaluated": n,
        "skipped_abstain": skipped_abstain,
        "errors": errors,
    }


def _print_pillar_report(pillar: str, kw: dict, cit: dict, top_k: int, rerank_n: int) -> None:
    print(f"\n{'='*72}")
    print(f"Pillar {pillar}  —  top_k={top_k}  rerank_n={rerank_n}")
    print(f"{'='*72}")
    print(f"  Questions evaluated : {kw['questions_evaluated']}"
          f"  (skipped abstain: {kw['skipped_abstain']}, errors: {kw['errors']})")
    print(f"  Keyword recall@{rerank_n} (final LLM context): {kw['avg_recall_at_n']:.1%}")
    print(f"  Keyword recall@{top_k} (raw vector pool)    : {kw['avg_recall_at_k']:.1%}")
    print(f"  Perfect recall@{rerank_n} (all keywords)    : {kw['perfect_recall_count']}/{kw['questions_evaluated']}")
    print(f"  Avg top-1 similarity score                   : {kw['avg_top_similarity']:.4f}")
    if cit["total_questions"]:
        print(f"  Citation recall@{top_k} (labelled only)    : {cit['hits']}/{cit['total_questions']}"
              f"  (MRR {cit['mrr']:.2f})")

    print(f"\n  Per-question (recall@{rerank_n} / recall@{top_k} | top-sim | status):")
    for p in kw["per_question"]:
        status = "OK" if p["recall_at_n"] >= 1.0 else ("PART" if p["recall_at_n"] >= 0.5 else "FAIL")
        miss = f"  missing: {p['missing']}" if p["missing"] else ""
        print(f"    {p['id']}  {p['recall_at_n']:.2f}/{p['recall_at_k']:.2f} | "
              f"{p['top_similarity']:.3f} | {status}{miss}")


async def run_pillar(pillar: str, top_k: int = 20, rerank_n: int = 5) -> dict:
    questions = _load_questions(pillar)
    logger.info("eval_start", pillar=pillar, questions=len(questions), top_k=top_k)
    kw = await evaluate_keyword_recall(questions, top_k, rerank_n)
    cit = await evaluate_recall(questions, top_k, rerank_n)
    _print_pillar_report(pillar, kw, cit, top_k, rerank_n)
    return {"pillar": pillar, "keyword": kw, "citation": cit}


async def run_all(top_k: int = 20, rerank_n: int = 5) -> list[dict]:
    results = []
    for pillar in ("A", "B", "C"):
        results.append(await run_pillar(pillar, top_k, rerank_n))

    # Cross-pillar rollup
    all_pq = [p for r in results for p in r["keyword"]["per_question"]]
    n = len(all_pq)
    avg_n = sum(p["recall_at_n"] for p in all_pq) / n if n else 0.0
    avg_k = sum(p["recall_at_k"] for p in all_pq) / n if n else 0.0
    perfect = sum(1 for p in all_pq if p["recall_at_n"] >= 1.0)
    print(f"\n{'='*72}")
    print(f"OVERALL  ({n} questions across A/B/C)")
    print(f"{'='*72}")
    print(f"  Keyword recall@{rerank_n} (final context) : {avg_n:.1%}")
    print(f"  Keyword recall@{top_k} (raw pool)        : {avg_k:.1%}")
    print(f"  Perfect recall@{rerank_n}               : {perfect}/{n}")
    worst = sorted(all_pq, key=lambda p: p["recall_at_n"])[:8]
    print(f"\n  Worst 8 questions:")
    for p in worst:
        print(f"    {p['id']}  recall@{rerank_n}={p['recall_at_n']:.2f}  "
              f"missing: {p['missing']}")
    return results


async def main():
    parser = argparse.ArgumentParser(description="Run retrieval evaluation")
    parser.add_argument("--pillar", type=str, help="Pillar to evaluate (A, B, or C)")
    parser.add_argument("--all", action="store_true", help="Evaluate all pillars (A, B, C)")
    parser.add_argument("--top-k", type=int, default=20, help="Vector search candidates (default 20)")
    parser.add_argument("--rerank-n", type=int, default=5, help="Final context size (default 5)")
    args = parser.parse_args()

    if args.all:
        await run_all(args.top_k, args.rerank_n)
    elif args.pillar:
        await run_pillar(args.pillar.upper(), args.top_k, args.rerank_n)
    else:
        parser.error("Specify --all or --pillar {A|B|C}")


if __name__ == "__main__":
    init_client()
    try:
        asyncio.run(main())
    finally:
        close_client()
