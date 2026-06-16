"""Retrieval evaluation — RAG performance on KB-answerable questions.

Metrics per question:
  - recall@N (post-rerank): expected keywords in the final top-N LLM context.
  - recall@K (pre-rerank):  expected keywords in the raw top-K vector pool.
  - recall@ALL:             expected keywords anywhere in the whole corpus.

Because only 25 documents are ingested, some eval questions reference content
not in the KB. recall@ALL classifies each question:
  - answerable (recall@ALL > 0): expected content exists in the corpus.
  - absent    (recall@ALL = 0): content gap — no RAG system could answer.
The fair RAG number is recall@N / recall@K over the ANSWERABLE subset.

Matching is normalized (rho/rho, >=/≥, x/×, sqrt/√) to avoid false negatives
on symbol/wording variants between the eval keywords and the source prose.

Usage:
    python -m eval.retrieval_eval --all
    python -m eval.retrieval_eval --pillar A
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import yaml
from pathlib import Path

import structlog

from config import get_settings
from retrieval.embeddings import embed_query
from retrieval.reranker import rerank
from retrieval.vector_store import _get_client, init_client, close_client, similarity_search

# Windows consoles default to cp1252 — force UTF-8 so reports never crash mid-print.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
logging.basicConfig(level=logging.WARNING)  # silence structlog INFO noise

logger = structlog.get_logger(__name__)

EVAL_DIR = Path(__file__).parent

_TRANS = {
    "ρ": "rho", "≥": ">=", "≤": "<=", "×": "x", "√": "sqrt", "±": "+/-",
    "→": "->", "−": "-", "–": "-", "—": "-", "&amp;": "&", "&#124;": "|",
    "&lt;": "<", "&gt;": ">", "&nbsp;": " ",
}


def _normalize(s: str) -> str:
    """Lowercase + fold symbol/HTML variants so 'rho >= 0.30' matches 'ρ ≥ 0.30'."""
    s = s.lower()
    for a, b in _TRANS.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _load_questions(pillar: str) -> list[dict]:
    path = EVAL_DIR / f"pillar_{pillar.lower()}_questions.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _keyword_recall(keywords: list[str], corpus: str) -> tuple[float, list[str]]:
    """Normalized fraction of keywords present in corpus. Returns (recall, missing)."""
    found, missing = [], []
    for kw in keywords:
        (found if _normalize(kw) in corpus else missing).append(kw)
    recall = len(found) / len(keywords) if keywords else 0.0
    return recall, missing


def _load_full_corpus() -> str:
    """Concatenate every non-deprecated chunk's content (normalized) — the answerability pool."""
    client = _get_client()
    settings = get_settings()
    parts: list[str] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            payload = p.payload or {}
            if payload.get("content"):
                parts.append(_normalize(payload["content"]))
        if offset is None:
            break
    return " ".join(parts)


async def evaluate_keyword_recall(
    questions: list[dict],
    full_corpus: str,
    top_k: int = 20,
    rerank_n: int = 5,
) -> dict:
    """Keyword recall + answerability classification per question."""
    per_question = []
    skipped_abstain = 0
    errors = 0

    for q in questions:
        qid = q["id"]
        keywords = q.get("expected_content") or q.get("must_include") or []

        if q.get("must_abstain"):
            skipped_abstain += 1
            continue
        if not keywords:
            continue

        # Answerability: is the expected content in the corpus AT ALL?
        recall_all, absent_from_kb = _keyword_recall(keywords, full_corpus)
        answerable = recall_all > 0
        query = q["question"]

        try:
            query_embedding = await embed_query(query)
            chunks = await similarity_search(query_embedding=query_embedding, top_k=top_k)
            ranked = await rerank(query, chunks, top_n=rerank_n)

            context_n = _normalize(" ".join(rc.chunk.content for rc in ranked))
            context_k = _normalize(" ".join(c.content for c in chunks))
            recall_n, missing_n = _keyword_recall(keywords, context_n)
            recall_k, _ = _keyword_recall(keywords, context_k)
            top_sim = ranked[0].score if ranked else 0.0
            err = None
        except Exception as e:
            errors += 1
            logger.error("eval_question_error", qid=qid, error=str(e))
            recall_n = recall_k = top_sim = 0.0
            missing_n = keywords
            err = str(e)

        per_question.append({
            "id": qid,
            "question": query,
            "recall_at_n": recall_n,
            "recall_at_k": recall_k,
            "recall_at_all": recall_all,
            "answerable": answerable,
            "top_similarity": top_sim,
            "missing_in_context": missing_n,
            "absent_from_kb": absent_from_kb,
            "error": err,
        })

    return _summarize(per_question, skipped_abstain, errors, top_k, rerank_n)


def _summarize(per_question, skipped_abstain, errors, top_k, rerank_n) -> dict:
    def agg(rows):
        n = len(rows)
        if not n:
            return None
        return {
            "n": n,
            "recall_at_n": round(sum(p["recall_at_n"] for p in rows) / n, 4),
            "recall_at_k": round(sum(p["recall_at_k"] for p in rows) / n, 4),
            "avg_top_similarity": round(sum(p["top_similarity"] for p in rows) / n, 4),
            "perfect_at_n": sum(1 for p in rows if p["recall_at_n"] >= 1.0),
        }

    answerable = [p for p in per_question if p["answerable"]]
    absent = [p for p in per_question if not p["answerable"]]
    return {
        "per_question": per_question,
        "all": agg(per_question),
        "answerable": agg(answerable),
        "absent": agg(absent),
        "absent_questions": absent,
        "questions_evaluated": len(per_question),
        "skipped_abstain": skipped_abstain,
        "errors": errors,
    }


def _print_block(label: str, s: dict | None, top_k: int, rerank_n: int) -> None:
    if not s:
        print(f"    {label}: (none)")
        return
    print(f"    {label:<18}: n={s['n']:<3} recall@{rerank_n}={s['recall_at_n']:.1%}  "
          f"recall@{top_k}={s['recall_at_k']:.1%}  perfect@{rerank_n}={s['perfect_at_n']}/{s['n']}")


def _print_pillar_report(pillar: str, kw: dict, top_k: int, rerank_n: int) -> None:
    print(f"\n{'='*74}")
    print(f"Pillar {pillar}  -  top_k={top_k}  rerank_n={rerank_n}  "
          f"(evaluated {kw['questions_evaluated']}, abstain {kw['skipped_abstain']}, errors {kw['errors']})")
    print(f"{'='*74}")
    _print_block("All questions", kw["all"], top_k, rerank_n)
    _print_block("Answerable (in KB)", kw["answerable"], top_k, rerank_n)
    _print_block("Absent (content gap)", kw["absent"], top_k, rerank_n)
    if kw["absent_questions"]:
        print(f"  Content-gap questions (excluded from fair RAG score):")
        for p in kw["absent_questions"]:
            print(f"    {p['id']}  absent keywords: {p['absent_from_kb']}")


async def run_pillar(pillar: str, full_corpus: str, top_k: int = 20, rerank_n: int = 5) -> dict:
    questions = _load_questions(pillar)
    logger.info("eval_start", pillar=pillar, questions=len(questions))
    kw = await evaluate_keyword_recall(questions, full_corpus, top_k, rerank_n)
    _print_pillar_report(pillar, kw, top_k, rerank_n)
    return kw


async def run_all(top_k: int = 20, rerank_n: int = 5) -> None:
    print("Building full-corpus answerability index (1597 chunks)...")
    full_corpus = _load_full_corpus()

    pillars = {p: await run_pillar(p, full_corpus, top_k, rerank_n) for p in ("A", "B", "C")}
    all_pq = [p for kw in pillars.values() for p in kw["per_question"]]
    ans_pq = [p for p in all_pq if p["answerable"]]

    def agg(rows):
        n = len(rows)
        return {
            "n": n,
            "recall_at_n": sum(p["recall_at_n"] for p in rows) / n if n else 0,
            "recall_at_k": sum(p["recall_at_k"] for p in rows) / n if n else 0,
            "perfect": sum(1 for p in rows if p["recall_at_n"] >= 1.0),
        }
    a_all, a_ans = agg(all_pq), agg(ans_pq)

    print(f"\n{'='*74}")
    print(f"OVERALL")
    print(f"{'='*74}")
    print(f"  All questions        : n={a_all['n']:<3} recall@{rerank_n}={a_all['recall_at_n']:.1%}  "
          f"recall@{top_k}={a_all['recall_at_k']:.1%}  perfect={a_all['perfect']}/{a_all['n']}")
    print(f"  Answerable (in KB)   : n={a_ans['n']:<3} recall@{rerank_n}={a_ans['recall_at_n']:.1%}  "
          f"recall@{top_k}={a_ans['recall_at_k']:.1%}  perfect={a_ans['perfect']}/{a_ans['n']}")
    print(f"\n  >>> Fair RAG retrieval recall@{rerank_n} (answerable subset): {a_ans['recall_at_n']:.1%} "
          f"({a_ans['perfect']}/{a_ans['n']} perfect) <<<")

    print(f"\n  Per-question (answerable only) recall@{rerank_n}/recall@{top_k}:")
    for p in sorted(ans_pq, key=lambda x: x["recall_at_n"]):
        status = "OK" if p["recall_at_n"] >= 1.0 else ("PART" if p["recall_at_n"] >= 0.5 else "FAIL")
        miss = f"  ctx-missing: {p['missing_in_context']}" if p["missing_in_context"] else ""
        print(f"    {p['id']}  {p['recall_at_n']:.2f}/{p['recall_at_k']:.2f} | {status}{miss}")


async def main():
    parser = argparse.ArgumentParser(description="Run retrieval evaluation")
    parser.add_argument("--pillar", type=str, help="Pillar to evaluate (A, B, or C)")
    parser.add_argument("--all", action="store_true", help="Evaluate all pillars (A, B, C)")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--rerank-n", type=int, default=5)
    args = parser.parse_args()

    full_corpus = _load_full_corpus() if args.pillar else None
    if args.all:
        await run_all(args.top_k, args.rerank_n)
    elif args.pillar:
        await run_pillar(args.pillar.upper(), full_corpus, args.top_k, args.rerank_n)
    else:
        parser.error("Specify --all or --pillar {A|B|C}")


if __name__ == "__main__":
    init_client()
    try:
        asyncio.run(main())
    finally:
        close_client()
