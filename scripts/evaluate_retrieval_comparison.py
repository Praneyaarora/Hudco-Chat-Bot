"""
Comparative Retrieval Evaluation Harness: BM25 vs Semantic vs Hybrid RRF.
File: scripts/evaluate_retrieval_comparison.py

Executes side-by-side evaluation over identical corpora and benchmarks:
- BM25 Baseline (Okapi k1=1.2, b=0.45)
- Persistent Semantic Vector Index (all-MiniLM-L6-v2, 384-d, cosine similarity)
- Hybrid RRF Retrieval (Reciprocal Rank Fusion, k=60)

Evaluates:
1. Multi-Report Benchmark (32 questions across historical reports ar15-ar26)
2. Single-Report Benchmark (20 questions on ar26 baseline)

Implements Section 4 integrity corrections:
- Multi-page citation checking over full physical_pages span.
- Strict separate reporting of answerable vs unanswerable questions.
- Abstention Precision, Recall, and F1 calculations.
- Ground truth chunk existence verification against the active corpus.
- Separate warm-up latency vs steady-state latency percentiles (mean, p50, p95, p99).
- Exact numerators, denominators, and per-question diagnostics saved to JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RetrievalComparison")

from config.settings import settings
from pipeline.core.contracts import CanonicalChunk
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.contracts import RetrievalResponse
from pipeline.retrieval.hybrid_search import HybridRetriever
from pipeline.retrieval.semantic_search import PersistentVectorIndex
from scripts.build_semantic_index import collect_eligible_corpus_chunks


def run_warmup(engine: Any, dummy_query: str = "Housing and Urban Development financial profit PAT") -> float:
    """Warms up engine and embedding threads, returning warmup latency in milliseconds."""
    t0 = time.perf_counter()
    if hasattr(engine, "search"):
        engine.search(dummy_query, top_k=2)
    elif hasattr(engine, "retrieve"):
        engine.retrieve(dummy_query, top_k=2)
    warmup_ms = (time.perf_counter() - t0) * 1000.0
    return round(warmup_ms, 2)


def evaluate_retriever_on_benchmark(
    name: str,
    retriever: Any,
    questions: List[Dict[str, Any]],
    indexed_chunk_ids: Set[str],
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    Evaluates a specific retriever branch on a set of benchmark questions.
    Returns comprehensive metrics with exact numerators, denominators, and latency stats.
    """
    warmup_latency_ms = run_warmup(retriever)

    answerable_q = []
    unanswerable_q = []
    for q in questions:
        if q.get("answerability", "answerable") == "unanswerable":
            unanswerable_q.append(q)
        else:
            answerable_q.append(q)

    # Steady-state evaluation
    latencies_ms: List[float] = []
    question_records: List[Dict[str, Any]] = []

    # Counters for answerable questions
    page_hits_1 = 0
    page_hits_3 = 0
    page_hits_5 = 0

    chunk_hits_1 = 0
    chunk_hits_3 = 0
    chunk_hits_5 = 0
    chunk_eval_eligible = 0  # questions where expected chunks actually exist in index

    doc_hits_1 = 0
    doc_hits_5 = 0

    page_rr_list: List[float] = []
    chunk_rr_list: List[float] = []

    false_abstentions = 0

    for q in answerable_q:
        qid = q.get("question_id", "Q")
        query_text = q.get("question", "")
        expected_pages = set(q.get("expected_pdf_pages", []))
        expected_doc = q.get("expected_source_document", "")
        # Map legacy doc ID if present
        if expected_doc == "HUDCO_AR_2025_26_c412ce14":
            expected_doc = "doc_ar26"

        raw_expected_chunks = q.get("expected_relevant_chunk_ids", [])
        valid_expected_chunks = set([c for c in raw_expected_chunks if c in indexed_chunk_ids])
        missing_annotation_chunks = [c for c in raw_expected_chunks if c not in indexed_chunk_ids]

        t0 = time.perf_counter()
        if hasattr(retriever, "retrieve"):
            resp: RetrievalResponse = retriever.retrieve(query_text, top_k=top_k)
        else:
            resp: RetrievalResponse = retriever.search(query_text, top_k=top_k)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        is_abstention = resp.is_abstention
        retrieved_items = resp.results

        if is_abstention:
            false_abstentions += 1

        # Check multi-page physical pages span
        p_hit_1 = False
        p_hit_3 = False
        p_hit_5 = False
        first_page_rr = 0.0

        for rank, item in enumerate(retrieved_items, start=1):
            item_pages = set(item.physical_pages) if item.physical_pages else {item.physical_page}
            if item_pages & expected_pages:
                if rank == 1:
                    p_hit_1 = True
                if rank <= 3:
                    p_hit_3 = True
                if rank <= 5:
                    p_hit_5 = True
                if first_page_rr == 0.0:
                    first_page_rr = 1.0 / rank

        if p_hit_1:
            page_hits_1 += 1
        if p_hit_3:
            page_hits_3 += 1
        if p_hit_5:
            page_hits_5 += 1
        page_rr_list.append(first_page_rr)

        # Document accuracy
        retrieved_docs = [it.document_id for it in retrieved_items]
        doc_hit_1 = bool(retrieved_docs and retrieved_docs[0] == expected_doc) if expected_doc else True
        doc_hit_5 = bool(expected_doc in retrieved_docs[:5]) if expected_doc else True
        if doc_hit_1:
            doc_hits_1 += 1
        if doc_hit_5:
            doc_hits_5 += 1

        # Chunk accuracy
        c_hit_1 = False
        c_hit_3 = False
        c_hit_5 = False
        first_chunk_rr = 0.0

        if valid_expected_chunks:
            chunk_eval_eligible += 1
            retrieved_cids = [it.chunk_id for it in retrieved_items]
            for rank, cid in enumerate(retrieved_cids, start=1):
                if cid in valid_expected_chunks:
                    if rank == 1:
                        c_hit_1 = True
                    if rank <= 3:
                        c_hit_3 = True
                    if rank <= 5:
                        c_hit_5 = True
                    if first_chunk_rr == 0.0:
                        first_chunk_rr = 1.0 / rank
            if c_hit_1:
                chunk_hits_1 += 1
            if c_hit_3:
                chunk_hits_3 += 1
            if c_hit_5:
                chunk_hits_5 += 1
            chunk_rr_list.append(first_chunk_rr)

        top1 = retrieved_items[0] if retrieved_items else None
        question_records.append({
            "question_id": qid,
            "query": query_text,
            "answerability": "answerable",
            "is_abstention": is_abstention,
            "expected_pages": sorted(list(expected_pages)),
            "expected_doc": expected_doc,
            "page_hit_1": p_hit_1,
            "page_hit_3": p_hit_3,
            "page_hit_5": p_hit_5,
            "doc_hit_1": doc_hit_1,
            "doc_hit_5": doc_hit_5,
            "chunk_hit_1": c_hit_1 if valid_expected_chunks else None,
            "chunk_hit_5": c_hit_5 if valid_expected_chunks else None,
            "missing_annotation_chunks": missing_annotation_chunks,
            "top1_chunk_id": top1.chunk_id if top1 else None,
            "top1_page": top1.physical_page if top1 else None,
            "top1_pages": top1.physical_pages if top1 else [],
            "top1_citation": top1.citation_label if top1 else "",
            "top1_score": top1.score if top1 else 0.0,
            "latency_ms": round(elapsed_ms, 2),
        })

    # Unanswerable queries evaluation
    true_abstentions = 0
    missed_abstentions = 0

    for q in unanswerable_q:
        qid = q.get("question_id", "Q")
        query_text = q.get("question", "")

        t0 = time.perf_counter()
        if hasattr(retriever, "retrieve"):
            resp = retriever.retrieve(query_text, top_k=top_k)
        else:
            resp = retriever.search(query_text, top_k=top_k)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        if resp.is_abstention:
            true_abstentions += 1
        else:
            missed_abstentions += 1

        question_records.append({
            "question_id": qid,
            "query": query_text,
            "answerability": "unanswerable",
            "is_abstention": resp.is_abstention,
            "abstention_reason": resp.abstention_reason,
            "latency_ms": round(elapsed_ms, 2),
        })

    num_ans = len(answerable_q)
    num_unans = len(unanswerable_q)

    # Compute abstention precision, recall, F1
    ab_denom_p = true_abstentions + false_abstentions
    abstention_precision = (true_abstentions / ab_denom_p) if ab_denom_p > 0 else 0.0

    ab_denom_r = true_abstentions + missed_abstentions
    abstention_recall = (true_abstentions / ab_denom_r) if ab_denom_r > 0 else 0.0

    if abstention_precision + abstention_recall > 0:
        abstention_f1 = 2 * (abstention_precision * abstention_recall) / (abstention_precision + abstention_recall)
    else:
        abstention_f1 = 0.0

    lat_arr = np.array(latencies_ms) if latencies_ms else np.array([0.0])

    return {
        "retriever_name": name,
        "sample_size": {
            "total_questions": len(questions),
            "answerable_questions": num_ans,
            "unanswerable_questions": num_unans,
            "chunk_annotated_questions": chunk_eval_eligible,
        },
        "page_recall": {
            "recall_at_1": round(page_hits_1 / num_ans, 4) if num_ans else 0.0,
            "recall_at_1_numerator": page_hits_1,
            "recall_at_1_denominator": num_ans,
            "recall_at_3": round(page_hits_3 / num_ans, 4) if num_ans else 0.0,
            "recall_at_3_numerator": page_hits_3,
            "recall_at_3_denominator": num_ans,
            "recall_at_5": round(page_hits_5 / num_ans, 4) if num_ans else 0.0,
            "recall_at_5_numerator": page_hits_5,
            "recall_at_5_denominator": num_ans,
            "page_mrr": round(float(np.mean(page_rr_list)), 4) if page_rr_list else 0.0,
            "rank1_citation_accuracy": round(page_hits_1 / num_ans, 4) if num_ans else 0.0,
        },
        "document_accuracy": {
            "doc_acc_at_1": round(doc_hits_1 / num_ans, 4) if num_ans else 0.0,
            "doc_acc_at_1_numerator": doc_hits_1,
            "doc_acc_at_1_denominator": num_ans,
            "doc_acc_at_5": round(doc_hits_5 / num_ans, 4) if num_ans else 0.0,
            "doc_acc_at_5_numerator": doc_hits_5,
            "doc_acc_at_5_denominator": num_ans,
        },
        "chunk_recall": {
            "recall_at_1": round(chunk_hits_1 / chunk_eval_eligible, 4) if chunk_eval_eligible else 0.0,
            "recall_at_1_numerator": chunk_hits_1,
            "recall_at_1_denominator": chunk_eval_eligible,
            "recall_at_3": round(chunk_hits_3 / chunk_eval_eligible, 4) if chunk_eval_eligible else 0.0,
            "recall_at_3_numerator": chunk_hits_3,
            "recall_at_3_denominator": chunk_eval_eligible,
            "recall_at_5": round(chunk_hits_5 / chunk_eval_eligible, 4) if chunk_eval_eligible else 0.0,
            "recall_at_5_numerator": chunk_hits_5,
            "recall_at_5_denominator": chunk_eval_eligible,
            "chunk_mrr": round(float(np.mean(chunk_rr_list)), 4) if chunk_rr_list else 0.0,
        },
        "abstention_metrics": {
            "true_abstentions": true_abstentions,
            "false_abstentions": false_abstentions,
            "missed_abstentions": missed_abstentions,
            "precision": round(abstention_precision, 4),
            "recall": round(abstention_recall, 4),
            "f1_score": round(abstention_f1, 4),
        },
        "latency_statistics_ms": {
            "warmup_latency_ms": warmup_latency_ms,
            "steady_state_mean_ms": round(float(np.mean(lat_arr)), 2),
            "steady_state_p50_ms": round(float(np.percentile(lat_arr, 50)), 2),
            "steady_state_p95_ms": round(float(np.percentile(lat_arr, 95)), 2),
            "steady_state_p99_ms": round(float(np.percentile(lat_arr, 99)), 2),
        },
        "questions": question_records,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate and compare BM25, Semantic, and Hybrid retrieval.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieved candidates per question")
    parser.add_argument(
        "--output-path",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "hybrid_comparison_report.json",
        help="Path to save consolidated comparison report JSON",
    )
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("STARTING RETRIEVAL COMPARATIVE EVALUATION (BM25 vs SEMANTIC vs HYBRID)")
    logger.info("=" * 80)

    # 1. Load canonical corpus
    t0 = time.perf_counter()
    chunks, source_info, excluded = collect_eligible_corpus_chunks()
    indexed_cids = {c.chunk_id for c in chunks}
    logger.info(f"Loaded {len(chunks):,} eligible chunks across {len(source_info)} reports in {time.perf_counter()-t0:.2f}s.")

    # 2. Initialize BM25 Index
    t_bm25 = time.perf_counter()
    bm25_index = Layer4BM25Index(chunks=chunks, abstention_threshold=14.5, min_term_coverage=0.40)
    logger.info(f"BM25 Index initialized in {time.perf_counter()-t_bm25:.2f}s (N={bm25_index.N:,}).")

    # 3. Load Persistent Vector Index
    t_sem = time.perf_counter()
    sem_index = PersistentVectorIndex(index_dir=settings.VECTOR_INDEX_DIR)
    if not sem_index.load(strict=True):
        raise RuntimeError("Persistent vector index failed integrity verification.")
    logger.info(f"Persistent Vector Index loaded in {time.perf_counter()-t_sem:.2f}s ({sem_index.total_chunks:,} vectors, dim={sem_index.embedding_dimension}).")

    # 4. Initialize Hybrid Retriever
    hybrid_retriever = HybridRetriever(
        bm25_index=bm25_index,
        semantic_index=sem_index,
        rrf_k=60,
        default_bm25_depth=50,
        default_semantic_depth=50,
    )
    logger.info("Hybrid Retriever initialized (RRF k=60, candidate depths: bm25=50, semantic=50).")

    # 5. Load Benchmarks
    multi_q_path = PROJECT_ROOT / "evaluation" / "data" / "multi_report_evaluation_questions.jsonl"
    single_q_path = PROJECT_ROOT / "evaluation" / "data" / "evaluation_questions.jsonl"

    with open(multi_q_path, "r", encoding="utf-8") as f:
        multi_questions = [json.loads(line) for line in f if line.strip()]

    with open(single_q_path, "r", encoding="utf-8") as f:
        single_questions = [json.loads(line) for line in f if line.strip()]

    logger.info(f"Loaded {len(multi_questions)} multi-report benchmark questions from {multi_q_path.name}.")
    logger.info(f"Loaded {len(single_questions)} single-report benchmark questions from {single_q_path.name}.")

    retrievers = [
        ("BM25 Baseline", bm25_index),
        ("Semantic Dense", sem_index),
        ("Hybrid RRF (k=60)", hybrid_retriever),
    ]

    report: Dict[str, Any] = {
        "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_statistics": {
            "total_chunks_indexed": len(chunks),
            "eligible_reports_count": len(source_info),
            "eligible_reports": sorted(list(source_info.keys())),
            "excluded_reports": excluded,
        },
        "multi_report_benchmark": {},
        "single_report_benchmark": {},
    }

    # Evaluate Multi-Report Benchmark
    logger.info("\n" + "=" * 50 + " RUNNING MULTI-REPORT BENCHMARK " + "=" * 50)
    for r_name, r_inst in retrievers:
        logger.info(f"Evaluating {r_name} on multi-report benchmark...")
        res = evaluate_retriever_on_benchmark(r_name, r_inst, multi_questions, indexed_cids, top_k=args.top_k)
        report["multi_report_benchmark"][r_name] = res
        logger.info(
            f"  {r_name}: Page R@1={res['page_recall']['recall_at_1']:.1%} ({res['page_recall']['recall_at_1_numerator']}/{res['page_recall']['recall_at_1_denominator']}), "
            f"Page R@5={res['page_recall']['recall_at_5']:.1%}, Doc Acc@1={res['document_accuracy']['doc_acc_at_1']:.1%}, "
            f"Page MRR={res['page_recall']['page_mrr']:.4f}, Latency(p50)={res['latency_statistics_ms']['steady_state_p50_ms']}ms"
        )

    # Evaluate Single-Report Benchmark
    logger.info("\n" + "=" * 50 + " RUNNING SINGLE-REPORT BENCHMARK (ar26) " + "=" * 50)
    for r_name, r_inst in retrievers:
        logger.info(f"Evaluating {r_name} on single-report benchmark...")
        res = evaluate_retriever_on_benchmark(r_name, r_inst, single_questions, indexed_cids, top_k=args.top_k)
        report["single_report_benchmark"][r_name] = res
        logger.info(
            f"  {r_name}: Page R@1={res['page_recall']['recall_at_1']:.1%} ({res['page_recall']['recall_at_1_numerator']}/{res['page_recall']['recall_at_1_denominator']}), "
            f"Page R@5={res['page_recall']['recall_at_5']:.1%}, Doc Acc@1={res['document_accuracy']['doc_acc_at_1']:.1%}, "
            f"Page MRR={res['page_recall']['page_mrr']:.4f}, Latency(p50)={res['latency_statistics_ms']['steady_state_p50_ms']}ms"
        )

    # Save output report
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"\nSuccessfully wrote consolidated comparison report to: {args.output_path}")


if __name__ == "__main__":
    main()
