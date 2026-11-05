"""
Command-Line Runner for HUDCO Evaluation Harness.
Supports independent execution modes:
  - Mode A: Retrieval-only evaluation (BM25 lexical baseline)
  - Mode B: Retrieval plus local LLM answer generation and citation verification (Ollama)
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from evaluation.config import (
    EVALUATION_CHUNKS_FILE,
    DEFAULT_QUESTIONS_FILE,
    EVAL_RUNS_DIR,
    DEFAULT_TOP_K,
    init_eval_directories,
)
from evaluation.schemas import (
    EvaluationChunk,
    EvaluationQuestion,
    QuestionRetrievalEvaluation,
    EvaluationRunReport,
)
from evaluation.extractor import EvaluationDocumentExtractor
from evaluation.chunker import EvaluationChunker
from evaluation.retriever_bm25 import BM25Retriever
from evaluation.generator_ollama import OllamaAnswerGenerator, check_ollama_available

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EvaluationRunner")


def load_evaluation_questions(filepath: Path) -> List[EvaluationQuestion]:
    """Loads benchmark questions from a JSONL file."""
    if not filepath.exists():
        raise FileNotFoundError(f"Questions file not found at: {filepath}")

    questions: List[EvaluationQuestion] = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                questions.append(EvaluationQuestion.model_validate_json(line_str))
    return questions


def generate_markdown_report(report: EvaluationRunReport, output_file: Path) -> None:
    """Renders a comprehensive, inspectable Markdown report for an evaluation run."""
    ts_str = report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Metrics display
    r1_str = f"{report.recall_at_1 * 100:.1f}%" if report.recall_at_1 is not None else "N/A"
    r3_str = f"{report.recall_at_3 * 100:.1f}%" if report.recall_at_3 is not None else "N/A"
    r5_str = f"{report.recall_at_5 * 100:.1f}%" if report.recall_at_5 is not None else "N/A"
    mrr_str = f"{report.mrr:.4f}" if report.mrr is not None else "N/A"

    q_rows = []
    for q in report.questions:
        pages_str = ", ".join(str(p) for p in q.expected_pdf_pages) if q.expected_pdf_pages else "None (Unanswerable)"
        top_chunk = q.retrieved_items[0].chunk_id if q.retrieved_items else "NONE"
        top_page = f"P.{q.retrieved_items[0].physical_page}" if q.retrieved_items else "-"
        top_score = f"{q.retrieved_items[0].score:.3f}" if q.retrieved_items else "0.0"

        if q.has_ground_truth:
            hit_str = "**HIT**" if q.hit_at_5 else "MISS"
            rank_str = f"Rank {int(1.0 / q.reciprocal_rank)}" if (q.reciprocal_rank and q.reciprocal_rank > 0) else "None"
        else:
            hit_str = "N/A (Unanswerable)"
            rank_str = "-"

        q_rows.append(
            f"| `{q.question_id}` | {q.category} | {q.question[:65]}... | {pages_str} | `{top_chunk}` ({top_page}) | {top_score} | {hit_str} ({rank_str}) |"
        )

    q_table = "\n".join(q_rows)

    # Detailed passage inspection section
    detail_sections = []
    for q in report.questions:
        items_md = []
        for itm in q.retrieved_items[:3]:
            pr_str = f", Printed P.{itm.printed_page}" if itm.printed_page else ""
            tbl_tag = " [TABLE]" if itm.has_table else ""
            items_md.append(
                f"- **Rank {itm.rank}** (`{itm.chunk_id}` | Physical P.{itm.physical_page}{pr_str}{tbl_tag} | Score: {itm.score})\n"
                f"  - *Terms Matched*: {itm.matched_terms}\n"
                f"  - *Passage Snippet*: `{itm.text[:220].replace(chr(10), ' ')}...`"
            )
        items_block = "\n".join(items_md) if items_md else "*(No passages retrieved)*"

        gen_block = ""
        if q.generated_answer:
            citations_str = ", ".join(q.cited_chunk_ids) if q.cited_chunk_ids else "None"
            abstain_str = f" (Abstention Correct: {q.abstention_correct})" if q.abstention_correct is not None else ""
            gen_block = (
                f"\n**Generated Answer**:\n> {q.generated_answer}\n\n"
                f"- *Cited Chunk IDs*: `{citations_str}`\n"
                f"- *Citations Valid*: {q.citation_validity.get('is_abstention') if q.citation_validity else 'N/A'}{abstain_str}\n"
            )

        detail_sections.append(
            f"### Question `{q.question_id}` ({q.category.upper()})\n"
            f"**Question**: {q.question}\n\n"
            f"**Expected Ground Truth Physical Page(s)**: {q.expected_pdf_pages or 'None (Unanswerable)'}\n\n"
            f"**Top Retrieved Evidence Passages**:\n{items_block}\n"
            f"{gen_block}"
        )

    details_str = "\n---\n".join(detail_sections)

    md_content = f"""# HUDCO RAG Evaluation Report: {report.run_id}

**Run Identifier**: `{report.run_id}`  
**Execution Timestamp**: `{ts_str}`  
**Evaluation Mode**: `{report.mode.upper()}`  
**Retriever**: BM25Okapi ($k_1=1.5, b=0.75$)  

---

## 1. Executive Evaluation Summary

| Metric | Measured Value | Scope / Description |
|---|---|---|
| **Total Evaluation Questions** | **{report.total_questions}** | All queries evaluated in benchmark |
| **Answerable Questions** | **{report.answerable_questions}** | Questions with verified source facts in `ar26.pdf` |
| **Unanswerable Questions** | **{report.unanswerable_questions}** | Questions testing appropriate abstention |
| **Eligible Ground-Truth Queries** | **{report.eligible_evaluation_questions}** | Questions with verified target physical pages |
| **Recall@1 (Top-1 Hit Rate)** | **{r1_str}** | Verified passage ranked at position 1 |
| **Recall@3 (Top-3 Hit Rate)** | **{r3_str}** | Verified passage within top 3 candidates |
| **Recall@5 (Top-5 Hit Rate)** | **{r5_str}** | Verified passage within top 5 candidates |
| **Mean Reciprocal Rank (MRR)** | **{mrr_str}** | Average reciprocal rank of first relevant chunk |
| **Zero-Retrieval Queries** | **{report.zero_retrieval_count}** | Queries with 0 matching lexical tokens |

> **Note on Evaluation Methodology**: Metrics are computed exclusively over questions with verified ground-truth physical pages ({report.eligible_evaluation_questions} of {report.total_questions} questions). Unanswerable questions are evaluated separately for abstention behavior.

---

## 2. Retrieval Summary Table

| ID | Category | Question | Expected Page(s) | Top Retrieved Chunk (Page) | BM25 Score | Hit @ 5 |
|---|---|---|---|---|---|---|
{q_table}

---

## 3. Question-by-Question Retrieval & Evidence Inspection

{details_str}

---

## 4. Corpus & Index Diagnostics

- **Total Physical Pages Extracted**: {report.corpus_stats.get('total_pages_extracted', 'N/A')}
- **Total Valid Evaluation Chunks**: {report.corpus_stats.get('total_chunks_indexed', 'N/A')}
- **Empty / Scanned Pages Detected**: {report.corpus_stats.get('empty_pages', 'N/A')}
- **Suspiciously Short Pages (<100 chars)**: {report.corpus_stats.get('short_pages', 'N/A')}
- **Pages Containing Tables**: {report.corpus_stats.get('table_pages', 'N/A')}
"""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)


def export_csv_results(report: EvaluationRunReport, output_file: Path) -> None:
    """Exports tabular CSV evaluation results for downstream analysis."""
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "question_id", "category", "answerability", "question",
            "expected_pages", "rank", "retrieved_chunk_id", "physical_page",
            "printed_page", "bm25_score", "has_table", "is_page_hit"
        ])
        for q in report.questions:
            expected_set = set(q.expected_pdf_pages)
            for itm in q.retrieved_items:
                is_hit = itm.physical_page in expected_set
                writer.writerow([
                    q.question_id, q.category, q.answerability, q.question,
                    ";".join(str(p) for p in q.expected_pdf_pages),
                    itm.rank, itm.chunk_id, itm.physical_page,
                    itm.printed_page or "", itm.score, itm.has_table, is_hit
                ])


def run_evaluation(
    mode: str = "retrieval",
    prepare_documents: bool = False,
    top_k: int = DEFAULT_TOP_K,
    questions_file: Path = DEFAULT_QUESTIONS_FILE,
    output_dir: Optional[Path] = None,
) -> EvaluationRunReport:
    """
    Executes the complete evaluation workflow.
    """
    init_eval_directories()
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    target_run_dir = output_dir or (EVAL_RUNS_DIR / run_id)
    target_run_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"=== Starting HUDCO Evaluation Run: {run_id} (Mode: {mode.upper()}) ===")

    # Step 1: Document Preparation if requested or chunks missing
    if prepare_documents or not EVALUATION_CHUNKS_FILE.exists():
        logger.info("Extracting and chunking source documents...")
        extractor = EvaluationDocumentExtractor()
        pages = extractor.extract_all()
        chunker = EvaluationChunker()
        chunks = chunker.chunk_pages(pages)
    else:
        logger.info(f"Loading existing chunks from {EVALUATION_CHUNKS_FILE}...")
        chunks = EvaluationChunker.load_chunks(EVALUATION_CHUNKS_FILE)

    logger.info(f"Loaded {len(chunks)} evaluation chunks.")

    # Step 2: Build BM25 Index
    logger.info("Building in-memory BM25 index...")
    retriever = BM25Retriever(chunks=chunks)

    # Step 3: Load Questions
    questions = load_evaluation_questions(questions_file)
    logger.info(f"Loaded {len(questions)} evaluation questions from {questions_file}.")

    # Step 4: Optional Ollama Generator setup
    generator = None
    if mode == "full":
        is_ollama_up, ollama_msg = check_ollama_available()
        logger.info(f"Ollama status: {ollama_msg}")
        if is_ollama_up:
            generator = OllamaAnswerGenerator()
        else:
            logger.warning("Ollama is not running. Falling back to retrieval evaluation.")

    # Step 5: Execute Queries & Measure Metrics
    question_evals: List[QuestionRetrievalEvaluation] = []
    eligible_count = 0
    hit1_count = 0
    hit3_count = 0
    hit5_count = 0
    rr_sum = 0.0
    zero_retrieval_count = 0

    for q in questions:
        retrieved_items = retriever.retrieve(q.question, top_k=top_k)
        if not retrieved_items:
            zero_retrieval_count += 1

        has_ground_truth = len(q.expected_pdf_pages) > 0 and q.answerability == "answerable"
        expected_pages_set = set(q.expected_pdf_pages)

        hit_1 = False
        hit_3 = False
        hit_5 = False
        rr = 0.0

        if has_ground_truth:
            eligible_count += 1
            for idx, item in enumerate(retrieved_items):
                if item.physical_page in expected_pages_set:
                    if idx == 0:
                        hit_1 = True
                    if idx < 3:
                        hit_3 = True
                    if idx < 5:
                        hit_5 = True
                    if rr == 0.0:
                        rr = 1.0 / (idx + 1)

            if hit_1:
                hit1_count += 1
            if hit_3:
                hit3_count += 1
            if hit_5:
                hit5_count += 1
            rr_sum += rr

        # Optional Answer Generation
        gen_answer = None
        citations_eval = None
        abstain_correct = None

        if generator:
            gen_res = generator.generate_grounded_answer(q.question, retrieved_items)
            gen_answer = gen_res.get("answer")
            citations_eval = gen_res.get("citation_validity")
            if q.answerability == "unanswerable" and citations_eval:
                abstain_correct = citations_eval.get("is_abstention", False)

        q_eval = QuestionRetrievalEvaluation(
            question_id=q.question_id,
            question=q.question,
            category=q.category,
            answerability=q.answerability,
            has_ground_truth=has_ground_truth,
            expected_pdf_pages=q.expected_pdf_pages,
            expected_chunk_ids=q.expected_relevant_chunk_ids,
            retrieved_items=retrieved_items,
            hit_at_1=hit_1 if has_ground_truth else None,
            hit_at_3=hit_3 if has_ground_truth else None,
            hit_at_5=hit_5 if has_ground_truth else None,
            reciprocal_rank=rr if has_ground_truth else None,
            zero_retrieval=(len(retrieved_items) == 0),
            generated_answer=gen_answer,
            cited_chunk_ids=citations_eval.get("cited_chunk_ids", []) if citations_eval else [],
            citation_validity=citations_eval,
            abstention_correct=abstain_correct,
            notes=[q.evaluation_notes] if q.evaluation_notes else [],
        )
        question_evals.append(q_eval)

    # Compute aggregate metrics
    recall_1 = (hit1_count / eligible_count) if eligible_count > 0 else None
    recall_3 = (hit3_count / eligible_count) if eligible_count > 0 else None
    recall_5 = (hit5_count / eligible_count) if eligible_count > 0 else None
    mrr = (rr_sum / eligible_count) if eligible_count > 0 else None

    # Load corpus stats
    corpus_stats = {"total_chunks_indexed": len(chunks)}
    summary_path = target_run_dir.parent.parent / "extracted" / "extraction_summary.json"
    if summary_path.exists():
        with open(summary_path, "r", encoding="utf-8") as f:
            corpus_stats.update(json.load(f))

    report = EvaluationRunReport(
        run_id=run_id,
        timestamp=datetime.utcnow(),
        mode=mode,
        total_questions=len(questions),
        answerable_questions=sum(1 for q in questions if q.answerability == "answerable"),
        unanswerable_questions=sum(1 for q in questions if q.answerability == "unanswerable"),
        eligible_evaluation_questions=eligible_count,
        recall_at_1=recall_1,
        recall_at_3=recall_3,
        recall_at_5=recall_5,
        mrr=mrr,
        zero_retrieval_count=zero_retrieval_count,
        questions=question_evals,
        corpus_stats=corpus_stats,
    )

    # Save artifacts
    report_json_path = target_run_dir / "evaluation_run_report.json"
    report_md_path = target_run_dir / "evaluation_run_report.md"
    results_csv_path = target_run_dir / "retrieval_results.csv"

    with open(report_json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    generate_markdown_report(report, report_md_path)
    export_csv_results(report, results_csv_path)

    logger.info(f"Evaluation complete! Artifacts saved to: {target_run_dir}")
    logger.info(f"Recall@5: {r5_str if (r5_str := f'{recall_5*100:.1f}%' if recall_5 else 'N/A') else 'N/A'}, MRR: {mrr:.4f if mrr else 'N/A'}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HUDCO Local RAG Evaluation Runner")
    parser.add_argument(
        "--mode",
        choices=["retrieval", "full"],
        default="retrieval",
        help="Evaluation mode: 'retrieval' (lexical BM25 only) or 'full' (with Ollama generation)",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Extract and chunk raw PDF pages before running evaluation",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Number of retrieved candidates per question (default 5)",
    )
    parser.add_argument(
        "--questions",
        type=str,
        default=str(DEFAULT_QUESTIONS_FILE),
        help="Path to questions JSONL file",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Custom run output directory",
    )

    args = parser.parse_args()
    q_path = Path(args.questions)
    out_p = Path(args.output_dir) if args.output_dir else None

    run_evaluation(
        mode=args.mode,
        prepare_documents=args.prepare,
        top_k=args.top_k,
        questions_file=q_path,
        output_dir=out_p,
    )
