"""
Layer 4 Retrieval Evaluation Harness for 520-Page Full Ingestion Run.
File: scripts/run_retrieval_eval.py

Evaluates Layer4BM25Index against canonical chunk datasets using the audited
benchmark questions in evaluation/data/evaluation_questions.jsonl.

Metrics computed with exact denominators:
- Chunk-level Recall@1, Recall@3, Recall@5 (hits / answerable_total)
- Page-level Recall@1, Recall@3, Recall@5 (hits / answerable_total)
- Page Citation Accuracy@1 (page_hits_at_1 / answerable_total)
- Page Citation Accuracy@5 (page_hits_at_5 / answerable_total)
- Mean Reciprocal Rank (MRR_page and MRR_chunk)
- Abstention Precision (true_abstentions / (true_abstentions + false_abstentions))
- Abstention Recall (true_abstentions / unanswerable_total)
- Abstention F1 Score
"""

import os
import sys
import json
import logging
from typing import Dict, List, Any, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipeline.retrieval.loader import load_canonical_chunks
from pipeline.retrieval.bm25 import Layer4BM25Index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RetrievalEval")


def evaluate_retrieval(
    chunks: list,
    questions: list[dict],
    k1: float = 1.2,
    b: float = 0.45,
    abstention_threshold: float = 14.5,
    min_term_coverage: float = 0.40,
    score_threshold: Optional[float] = None,
) -> tuple[dict, list[dict]]:
    """
    Core retrieval evaluation engine computing explicit metrics with distinct denominators.
    Can be invoked with in-memory chunks and questions for testing or benchmarking.
    """
    effective_threshold = score_threshold if score_threshold is not None else abstention_threshold
    index = Layer4BM25Index(
        chunks=chunks,
        k1=k1,
        b=b,
        abstention_threshold=effective_threshold,
        min_term_coverage=min_term_coverage,
    )

    answerable_total = 0
    unanswerable_total = 0

    chunk_hits_at_1 = 0
    chunk_hits_at_3 = 0
    chunk_hits_at_5 = 0

    page_hits_at_1 = 0
    page_hits_at_3 = 0
    page_hits_at_5 = 0

    page_reciprocal_ranks = []
    chunk_reciprocal_ranks = []
    
    true_abstentions = 0
    false_abstentions = 0
    missed_abstentions = 0

    question_results = []

    for q in questions:
        qid = q["question_id"]
        q_text = q["question"]
        expected_pages = set(q.get("expected_pdf_pages", []))
        expected_chunks = set(q.get("expected_relevant_chunk_ids", []))
        is_answerable = q.get("answerability", "answerable") == "answerable"

        resp = index.retrieve(q_text, top_k=5)
        top_k_chunks = [r.chunk_id for r in resp.results]
        top_k_pages = [r.physical_page for r in resp.results]

        q_rec = {
            "question_id": qid,
            "category": q.get("category"),
            "question": q_text,
            "answerability": q.get("answerability"),
            "is_abstention": resp.is_abstention,
            "abstention_reason": resp.abstention_reason,
            "top_candidates_scored": resp.total_candidates_scored,
            "expected_pages": list(expected_pages),
            "expected_chunks": list(expected_chunks),
            "results": [
                {
                    "rank": r.rank,
                    "chunk_id": r.chunk_id,
                    "physical_page": r.physical_page,
                    "score": r.score,
                    "term_coverage": r.term_coverage,
                    "matched_terms": r.matched_terms,
                    "snippet": r.content[:150].replace("\n", " "),
                }
                for r in resp.results
            ]
        }

        if not is_answerable:
            unanswerable_total += 1
            if resp.is_abstention:
                true_abstentions += 1
                q_rec["abstention_verdict"] = "CORRECT_ABSTENTION"
            else:
                missed_abstentions += 1
                q_rec["abstention_verdict"] = "FAILED_TO_ABSTAIN"
        else:
            answerable_total += 1
            if resp.is_abstention:
                false_abstentions += 1
                q_rec["abstention_verdict"] = "FALSE_ABSTENTION"
            else:
                q_rec["abstention_verdict"] = "RETRIEVED"

            # 1. Chunk-level hits
            c_hit_1 = bool(top_k_chunks[:1] and (top_k_chunks[0] in expected_chunks))
            c_hit_3 = any(cid in expected_chunks for cid in top_k_chunks[:3])
            c_hit_5 = any(cid in expected_chunks for cid in top_k_chunks[:5])

            if c_hit_1:
                chunk_hits_at_1 += 1
            if c_hit_3:
                chunk_hits_at_3 += 1
            if c_hit_5:
                chunk_hits_at_5 += 1

            # 2. Page-level hits (Recall@k)
            p_hit_1 = bool(top_k_pages[:1] and (top_k_pages[0] in expected_pages))
            p_hit_3 = any(p in expected_pages for p in top_k_pages[:3])
            p_hit_5 = any(p in expected_pages for p in top_k_pages[:5])

            if p_hit_1:
                page_hits_at_1 += 1
            if p_hit_3:
                page_hits_at_3 += 1
            if p_hit_5:
                page_hits_at_5 += 1

            # 3. Citation Page Accuracy:
            # - Citation Acc@1 is the hit rate of rank-1 returned citation page.
            # - Citation Acc@5 is the precision among all top-5 citation pages returned (supported citations / total citations emitted).
            supported_citations_in_top5 = sum(1 for p in top_k_pages[:5] if p in expected_pages)
            total_citations_emitted_top5 = len(top_k_pages[:5])
            q_rec["supported_citations_in_top5"] = supported_citations_in_top5
            q_rec["total_citations_emitted_top5"] = total_citations_emitted_top5

            # 4. Reciprocal Ranks
            p_rr = 0.0
            for rank_idx, p in enumerate(top_k_pages, start=1):
                if p in expected_pages:
                    p_rr = 1.0 / rank_idx
                    break
            page_reciprocal_ranks.append(p_rr)

            c_rr = 0.0
            for rank_idx, cid in enumerate(top_k_chunks, start=1):
                if cid in expected_chunks:
                    c_rr = 1.0 / rank_idx
                    break
            chunk_reciprocal_ranks.append(c_rr)

            q_rec["chunk_hit_at_1"] = c_hit_1
            q_rec["chunk_hit_at_5"] = c_hit_5
            q_rec["page_hit_at_1"] = p_hit_1
            q_rec["page_hit_at_5"] = p_hit_5
            q_rec["page_reciprocal_rank"] = p_rr
            q_rec["chunk_reciprocal_rank"] = c_rr

        question_results.append(q_rec)

    # Compute aggregate metrics with explicit definitions and distinct denominators
    c_recall_1 = (chunk_hits_at_1 / answerable_total) if answerable_total else 0.0
    c_recall_3 = (chunk_hits_at_3 / answerable_total) if answerable_total else 0.0
    c_recall_5 = (chunk_hits_at_5 / answerable_total) if answerable_total else 0.0

    p_recall_1 = (page_hits_at_1 / answerable_total) if answerable_total else 0.0
    p_recall_3 = (page_hits_at_3 / answerable_total) if answerable_total else 0.0
    p_recall_5 = (page_hits_at_5 / answerable_total) if answerable_total else 0.0

    # Citation Accuracy at Rank 1: fraction of answerable questions with supported Rank-1 page
    citation_acc_1 = p_recall_1

    # Citation Accuracy at Rank 5: precision of returned citations across all top-5 result slots
    total_supported_citations = sum(q.get("supported_citations_in_top5", 0) for q in question_results if q.get("answerability") == "answerable")
    total_emitted_citations = sum(q.get("total_citations_emitted_top5", 0) for q in question_results if q.get("answerability") == "answerable")
    citation_precision_at_5 = (total_supported_citations / total_emitted_citations) if total_emitted_citations > 0 else 0.0

    mrr_page = (sum(page_reciprocal_ranks) / len(page_reciprocal_ranks)) if page_reciprocal_ranks else 0.0
    mrr_chunk = (sum(chunk_reciprocal_ranks) / len(chunk_reciprocal_ranks)) if chunk_reciprocal_ranks else 0.0

    abstention_precision = (
        true_abstentions / (true_abstentions + false_abstentions)
        if (true_abstentions + false_abstentions) > 0
        else 0.0
    )
    abstention_recall = (
        true_abstentions / unanswerable_total
        if unanswerable_total > 0
        else 0.0
    )
    abstention_f1 = (
        2 * (abstention_precision * abstention_recall) / (abstention_precision + abstention_recall)
        if (abstention_precision + abstention_recall) > 0
        else 0.0
    )

    metrics_result = {
        "dataset_total_chunks": len(chunks),
        "total_questions": len(questions),
        "answerable_questions": answerable_total,
        "unanswerable_questions": unanswerable_total,
        "parameters": {
            "k1": k1,
            "b": b,
            "abstention_threshold": abstention_threshold,
            "min_term_coverage": min_term_coverage,
        },
        "metrics": {
            "chunk_recall_at_1": round(c_recall_1, 4),
            "chunk_recall_at_3": round(c_recall_3, 4),
            "chunk_recall_at_5": round(c_recall_5, 4),
            "page_recall_at_1": round(p_recall_1, 4),
            "page_recall_at_3": round(p_recall_3, 4),
            "page_recall_at_5": round(p_recall_5, 4),
            "page_citation_accuracy_at_1": round(citation_acc_1, 4),
            "page_citation_accuracy_at_5": round(citation_precision_at_5, 4),
            "mrr_page": round(mrr_page, 4),
            "mrr_chunk": round(mrr_chunk, 4),
            "abstention_precision": round(abstention_precision, 4),
            "abstention_recall": round(abstention_recall, 4),
            "abstention_f1": round(abstention_f1, 4),
        },
        "denominators": {
            "chunk_recall_denominator": f"Total Answerable Questions = {answerable_total}",
            "page_recall_denominator": f"Total Answerable Questions = {answerable_total}",
            "page_citation_accuracy_at_1_denominator": f"Total Answerable Questions = {answerable_total} (Note: Identical to Page Recall@1 under exact page-support definition)",
            "page_citation_accuracy_at_5_denominator": f"Total Citations Emitted in Top-5 = {total_emitted_citations} (Precision: supported citations / emitted citations)",
            "mrr_page_denominator": f"Total Answerable Questions = {answerable_total}",
            "mrr_chunk_denominator": f"Total Answerable Questions = {answerable_total}",
            "abstention_precision_denominator": f"Total Abstentions Triggered = {true_abstentions + false_abstentions}",
            "abstention_recall_denominator": f"Total Unanswerable Questions = {unanswerable_total}",
        },
        "detailed_results": question_results,
    }

    return metrics_result, question_results


def run_evaluation(
    chunks_path: str = "data/output_chunks/run_full_ar26_p1_520_v1/chunks.jsonl",
    questions_path: str = "evaluation/data/evaluation_questions.jsonl",
    output_report_path: str = "evaluation/retrieval_eval_report.json",
    k1: float = 1.2,
    b: float = 0.45,
    abstention_threshold: float = 14.5,
    min_term_coverage: float = 0.40,
) -> Dict[str, Any]:
    logger.info(f"Loading canonical chunks from {chunks_path}...")
    chunks = load_canonical_chunks(chunks_path)
    logger.info(f"Loaded {len(chunks):,} canonical chunks.")

    logger.info(f"Loading evaluation questions from {questions_path}...")
    with open(questions_path, "r", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]

    logger.info(f"Evaluating {len(questions)} benchmark questions...")
    metrics, question_results = evaluate_retrieval(
        chunks=chunks,
        questions=questions,
        k1=k1,
        b=b,
        abstention_threshold=abstention_threshold,
        min_term_coverage=min_term_coverage,
    )

    # Save to disk
    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    logger.info(f"Evaluation report saved to {output_report_path}")

    m = metrics["metrics"]
    ans_total = metrics["answerable_questions"]
    unans_total = metrics["unanswerable_questions"]

    # Output formatted console table
    print("\n" + "=" * 88)
    print("LAYER 4 RETRIEVAL EVALUATION REPORT — HUDCO ANNUAL REPORT 2025-26")
    print("=" * 88)
    print(f"Total Canonical Chunks Indexed : {len(chunks):,}")
    print(f"Benchmark Questions Evaluated  : {len(questions)} ({ans_total} answerable, {unans_total} unanswerable)")
    print(f"BM25 Tuning Parameters         : k1={k1}, b={b}, threshold={abstention_threshold}, min_cov={min_term_coverage:.0%}")
    print("-" * 88)
    print(f"Page Recall@1                  : {m['page_recall_at_1']:.1%} ({metrics['denominators']['page_recall_denominator']})")
    print(f"Page Recall@3                  : {m['page_recall_at_3']:.1%} ({metrics['denominators']['page_recall_denominator']})")
    print(f"Page Recall@5                  : {m['page_recall_at_5']:.1%} ({metrics['denominators']['page_recall_denominator']})")
    print(f"Chunk Recall@1                 : {m['chunk_recall_at_1']:.1%} ({metrics['denominators']['chunk_recall_denominator']})")
    print(f"Chunk Recall@3                 : {m['chunk_recall_at_3']:.1%} ({metrics['denominators']['chunk_recall_denominator']})")
    print(f"Chunk Recall@5                 : {m['chunk_recall_at_5']:.1%} ({metrics['denominators']['chunk_recall_denominator']})")
    print(f"Page Citation Accuracy@1       : {m['page_citation_accuracy_at_1']:.1%} ({metrics['denominators']['page_citation_accuracy_at_1_denominator']})")
    print(f"Page Citation Accuracy@5 (Prec): {m['page_citation_accuracy_at_5']:.1%} ({metrics['denominators']['page_citation_accuracy_at_5_denominator']})")
    print(f"MRR (Page Provenance)          : {m['mrr_page']:.4f}")
    print(f"MRR (Chunk Provenance)         : {m['mrr_chunk']:.4f}")
    print(f"Abstention Precision           : {m['abstention_precision']:.1%} ({metrics['denominators']['abstention_precision_denominator']})")
    print(f"Abstention Recall              : {m['abstention_recall']:.1%} ({metrics['denominators']['abstention_recall_denominator']})")
    print(f"Abstention F1 Score            : {m['abstention_f1']:.1%}")
    print("=" * 88)
    print("\nPer-Question Evaluation Summary:")
    print(f"{'QID':<5} | {'Category':<14} | {'Verdict':<18} | {'Top-1 Score':<11} | {'Top Page':<8} | {'Expected':<12}")
    print("-" * 88)
    for q_rec in question_results:
        top_score = q_rec["results"][0]["score"] if q_rec["results"] else 0.0
        top_p = q_rec["results"][0]["physical_page"] if q_rec["results"] else "N/A"
        orig = next(x for x in questions if x["question_id"] == q_rec["question_id"])
        exp_p = str(orig.get("expected_pdf_pages", []))
        verdict = q_rec.get("abstention_verdict", "OK")
        if q_rec["answerability"] == "answerable":
            verdict = f"Hit@1: {'YES' if q_rec.get('page_hit_at_1') else 'NO'}"
        print(f"{q_rec['question_id']:<5} | {q_rec['category']:<14} | {verdict:<18} | {top_score:<11.2f} | {str(top_p):<8} | {exp_p:<12}")
    print("=" * 88 + "\n")

    return metrics


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Layer 4 Retrieval Evaluation Harness for HUDCO Document Processing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--chunks", default="data/output_chunks/run_full_ar26_p1_520_v1/chunks.jsonl", help="Path to canonical chunks JSONL")
    parser.add_argument("--questions", default="evaluation/data/evaluation_questions.jsonl", help="Path to evaluation questions JSONL")
    parser.add_argument("--output", default="evaluation/retrieval_eval_report.json", help="Path to output JSON report")
    parser.add_argument("--k1", type=float, default=1.2, help="BM25 k1 parameter")
    parser.add_argument("--b", type=float, default=0.45, help="BM25 b parameter")
    parser.add_argument("--abstention-threshold", type=float, default=14.5, help="BM25 score threshold for abstention")
    parser.add_argument("--min-term-coverage", type=float, default=0.40, help="Minimum query term coverage for abstention")

    args = parser.parse_args()
    run_evaluation(
        chunks_path=args.chunks,
        questions_path=args.questions,
        output_report_path=args.output,
        k1=args.k1,
        b=args.b,
        abstention_threshold=args.abstention_threshold,
        min_term_coverage=args.min_term_coverage,
    )


if __name__ == "__main__":
    main()

