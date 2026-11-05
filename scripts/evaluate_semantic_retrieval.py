"""
Evaluation runner for Persistent Semantic Vector Retrieval Layer.
File: scripts/evaluate_semantic_retrieval.py

Evaluates PersistentVectorIndex on 22,607 canonical chunks across
evaluation/data/multi_report_evaluation_questions.jsonl and
evaluation/data/evaluation_questions.jsonl.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SemanticEval")

from config.settings import settings
from pipeline.retrieval.embedding import LocalEmbeddingEngine
from pipeline.retrieval.semantic_search import PersistentVectorIndex
from pipeline.retrieval.contracts import RetrievalFilter


def evaluate_semantic_benchmark(
    index_dir: Path = settings.VECTOR_INDEX_DIR,
    questions_path: Path = PROJECT_ROOT / "evaluation" / "data" / "multi_report_evaluation_questions.jsonl",
    output_path: Path = PROJECT_ROOT / "data" / "vector_index" / "semantic_retrieval_eval_report.json",
    top_k: int = 5,
) -> Dict[str, Any]:
    logger.info(f"Loading persistent vector index from {index_dir}...")
    index = PersistentVectorIndex(index_dir=index_dir)
    if not index.load():
        raise RuntimeError(f"Failed to load vector index from {index_dir}")
    logger.info(f"Loaded {index.total_chunks:,} vectors (dimension={index.embedding_dimension}).")

    if not questions_path.exists():
        raise FileNotFoundError(f"Questions file not found: {questions_path}")

    with open(questions_path, "r", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]

    logger.info(f"Evaluating {len(questions)} multi-report questions (top_k={top_k})...")

    answerable_total = 0
    page_hits_1 = 0
    page_hits_3 = 0
    page_hits_5 = 0
    doc_hits_1 = 0
    doc_hits_5 = 0

    chunk_hits_1 = 0
    chunk_hits_3 = 0
    chunk_hits_5 = 0

    reciprocal_ranks_page = []
    query_latencies_ms = []
    question_results = []

    for q in questions:
        qid = q.get("question_id", "Q")
        query_text = q.get("question", "")
        answerability = q.get("answerability", "answerable")
        expected_pages = set(q.get("expected_pdf_pages", []))
        expected_doc = q.get("expected_source_document", "")
        expected_chunks = set(q.get("expected_relevant_chunk_ids", []))

        if answerability != "answerable" or not expected_pages:
            continue

        answerable_total += 1
        t0 = time.perf_counter()
        response = index.search(query=query_text, top_k=top_k)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        query_latencies_ms.append(elapsed_ms)

        retrieved_items = response.results
        retrieved_pages = [item.physical_page for item in retrieved_items]
        retrieved_docs = [item.document_id for item in retrieved_items]
        retrieved_chunk_ids = [item.chunk_id for item in retrieved_items]

        # Document accuracy
        doc_hit_1 = bool(retrieved_docs and retrieved_docs[0] == expected_doc) if expected_doc else True
        doc_hit_5 = bool(expected_doc in retrieved_docs[:5]) if expected_doc else True
        if doc_hit_1:
            doc_hits_1 += 1
        if doc_hit_5:
            doc_hits_5 += 1

        # Page recall
        p_hit_1 = any(p in expected_pages for p in retrieved_pages[:1])
        p_hit_3 = any(p in expected_pages for p in retrieved_pages[:3])
        p_hit_5 = any(p in expected_pages for p in retrieved_pages[:5])

        if p_hit_1:
            page_hits_1 += 1
        if p_hit_3:
            page_hits_3 += 1
        if p_hit_5:
            page_hits_5 += 1

        # MRR calculation
        rr = 0.0
        for rank, p in enumerate(retrieved_pages, start=1):
            if p in expected_pages:
                rr = 1.0 / rank
                break
        reciprocal_ranks_page.append(rr)

        # Chunk recall (where ground truth chunks are defined)
        if expected_chunks:
            c_hit_1 = any(c in expected_chunks for c in retrieved_chunk_ids[:1])
            c_hit_3 = any(c in expected_chunks for c in retrieved_chunk_ids[:3])
            c_hit_5 = any(c in expected_chunks for c in retrieved_chunk_ids[:5])
            if c_hit_1:
                chunk_hits_1 += 1
            if c_hit_3:
                chunk_hits_3 += 1
            if c_hit_5:
                chunk_hits_5 += 1

        top1_item = retrieved_items[0] if retrieved_items else None
        question_results.append({
            "question_id": qid,
            "query": query_text,
            "expected_doc": expected_doc,
            "expected_pages": sorted(list(expected_pages)),
            "top1_score": round(top1_item.score, 4) if top1_item else 0.0,
            "top1_doc": top1_item.document_id if top1_item else None,
            "top1_page": top1_item.physical_page if top1_item else None,
            "page_hit_1": p_hit_1,
            "page_hit_5": p_hit_5,
            "latency_ms": round(elapsed_ms, 2),
        })

    mrr = sum(reciprocal_ranks_page) / len(reciprocal_ranks_page) if reciprocal_ranks_page else 0.0
    mean_lat = sum(query_latencies_ms) / len(query_latencies_ms) if query_latencies_ms else 0.0

    eval_summary = {
        "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_corpus_chunks": index.total_chunks,
        "embedding_model": index.embedding_model,
        "embedding_dimension": index.embedding_dimension,
        "total_questions_evaluated": len(questions),
        "answerable_questions_evaluated": answerable_total,
        "metrics": {
            "page_recall_at_1": round(page_hits_1 / answerable_total, 4) if answerable_total else 0.0,
            "page_recall_at_3": round(page_hits_3 / answerable_total, 4) if answerable_total else 0.0,
            "page_recall_at_5": round(page_hits_5 / answerable_total, 4) if answerable_total else 0.0,
            "doc_accuracy_at_1": round(doc_hits_1 / answerable_total, 4) if answerable_total else 0.0,
            "doc_accuracy_at_5": round(doc_hits_5 / answerable_total, 4) if answerable_total else 0.0,
            "mrr_page": round(mrr, 4),
            "mean_query_latency_ms": round(mean_lat, 2),
            "p95_query_latency_ms": round(sorted(query_latencies_ms)[int(0.95 * len(query_latencies_ms))], 2) if query_latencies_ms else 0.0,
        },
        "question_results": question_results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(eval_summary, f, indent=2)

    print("\n" + "=" * 80)
    print("PERSISTENT SEMANTIC VECTOR RETRIEVAL EVALUATION REPORT")
    print("=" * 80)
    print(f"Total Chunks Scored per Query : {index.total_chunks:,}")
    print(f"Embedding Model               : {index.embedding_model} (dim={index.embedding_dimension})")
    print(f"Answerable Queries Evaluated  : {answerable_total}")
    print("-" * 80)
    print(f"Page Recall@1                 : {eval_summary['metrics']['page_recall_at_1']:.1%}")
    print(f"Page Recall@3                 : {eval_summary['metrics']['page_recall_at_3']:.1%}")
    print(f"Page Recall@5                 : {eval_summary['metrics']['page_recall_at_5']:.1%}")
    print(f"Document Accuracy@1           : {eval_summary['metrics']['doc_accuracy_at_1']:.1%}")
    print(f"Document Accuracy@5           : {eval_summary['metrics']['doc_accuracy_at_5']:.1%}")
    print(f"MRR (Page Provenance)         : {eval_summary['metrics']['mrr_page']:.4f}")
    print(f"Mean Query Latency            : {eval_summary['metrics']['mean_query_latency_ms']} ms")
    print(f"P95 Query Latency             : {eval_summary['metrics']['p95_query_latency_ms']} ms")
    print("=" * 80 + "\n")

    return eval_summary


if __name__ == "__main__":
    evaluate_semantic_benchmark()
