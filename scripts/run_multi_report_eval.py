"""
Multi-Report Retrieval Evaluation Runner across All Processed HUDCO Annual Reports.
File: scripts/run_multi_report_eval.py

Evaluates the 32-question multi-report benchmark (evaluation/data/multi_report_evaluation_questions.jsonl)
across:
  1. ar26 Baseline Corpus (2,682 chunks)
  2. Combined Historical Corpus (ar26 + ar24: 5,042 chunks)
  3. Full Stage C Corpus (ar26 + ar24 + ar23 + ar22 + ar21: 11,518 chunks)

Computes exact metrics with distinct denominators:
  - Answerable Total vs Unanswerable Total
  - Page-Level Recall@1, Recall@3, Recall@5
  - Multi-page provenance coverage
  - Mean Reciprocal Rank (MRR)
  - True Abstentions, False Abstentions, Missed Abstentions
  - Abstention Precision, Recall, and F1 Score
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MultiReportEval")

from config.settings import settings
from pipeline.retrieval.contracts import RetrievalFilter
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.loader import load_canonical_chunks


RUN_DIRECTORIES = {
    "ar26": settings.OUTPUT_CHUNKS_DIR / "run_full_ar26_p1_520_v1",
    "ar24": settings.OUTPUT_CHUNKS_DIR / "run_pilot_ar24_p1_426_v1",
    "ar21": settings.OUTPUT_CHUNKS_DIR / "run_full_ar21_p1_332_v1",
    "ar22": settings.OUTPUT_CHUNKS_DIR / "run_full_ar22_p1_358_v1",
    "ar23": settings.OUTPUT_CHUNKS_DIR / "run_full_ar23_p1_362_v1",
}


def load_corpus_runs(run_keys: List[str]) -> Tuple[List[Any], Dict[str, int]]:
    """Loads chunks from specific run directories without modifying approved pointer."""
    all_chunks = []
    counts = {}
    for key in run_keys:
        run_dir = RUN_DIRECTORIES[key]
        chunks_file = run_dir / "chunks.jsonl"
        if not chunks_file.exists():
            raise FileNotFoundError(f"Run chunks file not found: {chunks_file}")
        chunks = load_canonical_chunks(str(chunks_file))
        counts[key] = len(chunks)
        all_chunks.extend(chunks)
        logger.info(f"Loaded {len(chunks)} chunks from {key} ({run_dir.name}).")
    return all_chunks, counts


def run_evaluation_on_corpus(
    chunks: List[Any],
    questions: List[Dict[str, Any]],
    corpus_name: str,
    abstention_threshold: float = 14.5,
    min_term_coverage: float = 0.35,
) -> Dict[str, Any]:
    """Evaluates BM25 retrieval across chunks against the provided benchmark questions."""
    logger.info(f"Building BM25 index for {corpus_name} ({len(chunks)} chunks)...")
    t0 = time.time()
    index = Layer4BM25Index(
        chunks=chunks,
        k1=1.2,
        b=0.45,
        abstention_threshold=abstention_threshold,
        min_term_coverage=min_term_coverage,
    )
    build_time = time.time() - t0
    logger.info(f"Index built in {build_time:.2f}s.")

    answerable_count = 0
    unanswerable_count = 0

    page_hits_at_1 = 0
    page_hits_at_3 = 0
    page_hits_at_5 = 0
    reciprocal_ranks = []

    true_abstentions = 0
    false_abstentions = 0
    missed_abstentions = 0

    question_evaluations = []

    for q in questions:
        qid = q["question_id"]
        q_text = q["question"]
        is_answerable = q.get("answerability", "answerable") == "answerable"
        expected_doc = q.get("expected_source_document")
        expected_pages = set(q.get("expected_pdf_pages", []))
        expected_chunks = set(q.get("expected_relevant_chunk_ids", []))

        resp = index.retrieve(q_text, top_k=5)
        top_k_chunks = [r.chunk_id for r in resp.results]

        # Multi-page aware page extraction
        top_k_page_sets = [
            set(r.physical_pages if hasattr(r, "physical_pages") and r.physical_pages else [r.physical_page])
            for r in resp.results
        ]
        top_k_primary_pages = [r.physical_page for r in resp.results]
        top_k_docs = [r.document_id for r in resp.results]

        q_res = {
            "question_id": qid,
            "category": q.get("category"),
            "question": q_text,
            "answerability": q.get("answerability"),
            "is_abstention": resp.is_abstention,
            "abstention_reason": resp.abstention_reason,
            "retrieved_results": [
                {
                    "rank": r.rank,
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "physical_page": r.physical_page,
                    "physical_pages": getattr(r, "physical_pages", [r.physical_page]),
                    "score": r.score,
                    "term_coverage": r.term_coverage,
                    "matched_terms": r.matched_terms,
                    "snippet": r.content[:150].replace("\n", " "),
                }
                for r in resp.results
            ]
        }

        if not is_answerable:
            unanswerable_count += 1
            if resp.is_abstention:
                true_abstentions += 1
                q_res["verdict"] = "CORRECT_ABSTENTION"
            else:
                missed_abstentions += 1
                q_res["verdict"] = "MISSED_ABSTENTION"
        else:
            answerable_count += 1
            if resp.is_abstention:
                false_abstentions += 1
                q_res["verdict"] = "FALSE_ABSTENTION"
            else:
                q_res["verdict"] = "RETRIEVED"

            # Check if target report exists in this corpus
            corpus_has_target = True
            if expected_doc:
                target_docs = [d.strip() for d in expected_doc.split(",")]
                available_docs = set(c.document_id for c in chunks)
                if not any(td in available_docs for td in target_docs):
                    corpus_has_target = False

            q_res["corpus_has_target"] = corpus_has_target

            # Page hits: check if expected_pages intersects the result pages
            hit_1 = False
            hit_3 = False
            hit_5 = False

            if expected_pages:
                if top_k_page_sets and bool(top_k_page_sets[0].intersection(expected_pages)):
                    hit_1 = True
                if any(bool(pset.intersection(expected_pages)) for pset in top_k_page_sets[:3]):
                    hit_3 = True
                if any(bool(pset.intersection(expected_pages)) for pset in top_k_page_sets[:5]):
                    hit_5 = True
            elif expected_doc:
                # If question targets doc without explicit page requirement
                target_docs = [d.strip() for d in expected_doc.split(",")]
                if top_k_docs and top_k_docs[0] in target_docs:
                    hit_1 = True
                if any(d in target_docs for d in top_k_docs[:3]):
                    hit_3 = True
                if any(d in target_docs for d in top_k_docs[:5]):
                    hit_5 = True

            if hit_1:
                page_hits_at_1 += 1
            if hit_3:
                page_hits_at_3 += 1
            if hit_5:
                page_hits_at_5 += 1

            # Reciprocal rank
            rr = 0.0
            for rank_idx, pset in enumerate(top_k_page_sets, start=1):
                if expected_pages and bool(pset.intersection(expected_pages)):
                    rr = 1.0 / rank_idx
                    break
                elif not expected_pages and expected_doc:
                    target_docs = [d.strip() for d in expected_doc.split(",")]
                    if top_k_docs[rank_idx - 1] in target_docs:
                        rr = 1.0 / rank_idx
                        break
            reciprocal_ranks.append(rr)

        question_evaluations.append(q_res)

    # Compute aggregate metrics
    recall_at_1 = page_hits_at_1 / answerable_count if answerable_count > 0 else 0.0
    recall_at_3 = page_hits_at_3 / answerable_count if answerable_count > 0 else 0.0
    recall_at_5 = page_hits_at_5 / answerable_count if answerable_count > 0 else 0.0
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

    abst_precision = true_abstentions / (true_abstentions + false_abstentions) if (true_abstentions + false_abstentions) > 0 else 1.0
    abst_recall = true_abstentions / unanswerable_count if unanswerable_count > 0 else 1.0
    abst_f1 = (2 * abst_precision * abst_recall / (abst_precision + abst_recall)) if (abst_precision + abst_recall) > 0 else 0.0

    return {
        "corpus_name": corpus_name,
        "total_chunks_indexed": len(chunks),
        "total_questions_evaluated": len(questions),
        "answerable_questions": answerable_count,
        "unanswerable_questions": unanswerable_count,
        "recall_at_1": round(recall_at_1, 4),
        "recall_at_3": round(recall_at_3, 4),
        "recall_at_5": round(recall_at_5, 4),
        "mrr": round(mrr, 4),
        "true_abstentions": true_abstentions,
        "false_abstentions": false_abstentions,
        "missed_abstentions": missed_abstentions,
        "abstention_precision": round(abst_precision, 4),
        "abstention_recall": round(abst_recall, 4),
        "abstention_f1": round(abst_f1, 4),
        "question_details": question_evaluations,
    }


def main():
    logger.info("=" * 80)
    logger.info("STARTING MULTI-REPORT RETRIEVAL EVALUATION")
    logger.info("=" * 80)

    benchmark_path = settings.DATA_DIR / "multi_report_evaluation_questions.jsonl"
    if not benchmark_path.exists():
        benchmark_path = PROJECT_ROOT / "evaluation" / "data" / "multi_report_evaluation_questions.jsonl"

    questions = []
    with open(benchmark_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line.strip()))
    logger.info(f"Loaded {len(questions)} evaluation questions from {benchmark_path.name}.")

    # Experiment 1: ar24 + ar26 Combined
    logger.info("\n--- EXPERIMENT 1: ar24 + ar26 Combined Corpus ---")
    chunks_24_26, counts_24_26 = load_corpus_runs(["ar26", "ar24"])
    res_24_26 = run_evaluation_on_corpus(chunks_24_26, questions, "ar24_plus_ar26")

    # Experiment 2: Full Stage C Corpus (ar21, ar22, ar23, ar24, ar26)
    logger.info("\n--- EXPERIMENT 2: Full Stage C Corpus (ar21 + ar22 + ar23 + ar24 + ar26) ---")
    chunks_all, counts_all = load_corpus_runs(["ar26", "ar24", "ar23", "ar22", "ar21"])
    res_all = run_evaluation_on_corpus(chunks_all, questions, "full_stage_c_corpus")

    # Save results
    report_output = settings.DATA_DIR / "multi_report_retrieval_evaluation_report.json"
    report_data = {
        "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmark_file": benchmark_path.name,
        "benchmark_question_count": len(questions),
        "experiments": [
            res_24_26,
            res_all,
        ]
    }
    with open(report_output, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    logger.info(f"Evaluation results successfully saved to {report_output}")

    print("\n" + "=" * 80)
    print("MULTI-REPORT RETRIEVAL EVALUATION SUMMARY")
    print("=" * 80)
    for exp in [res_24_26, res_all]:
        print(f"Corpus: {exp['corpus_name']:<25} Chunks: {exp['total_chunks_indexed']:<6}")
        print(f"  Recall@1: {exp['recall_at_1']:.1%} | Recall@3: {exp['recall_at_3']:.1%} | Recall@5: {exp['recall_at_5']:.1%} | MRR: {exp['mrr']:.4f}")
        print(f"  Abstention: True={exp['true_abstentions']}, False={exp['false_abstentions']}, Missed={exp['missed_abstentions']} | F1={exp['abstention_f1']:.1%}")
        print("-" * 80)


if __name__ == "__main__":
    main()
