# HUDCO Minimal Local RAG Evaluation Harness

> [!NOTE]
> **Production vs. Experimental Evaluation Notice**:  
> The modules in this directory (`evaluation/extractor.py`, `evaluation/chunker.py`, `evaluation/retriever_bm25.py`, `evaluation/run_evaluation.py`) served as the initial, standalone Phase 0/1 evaluation testbed.  
> The **production Layer 4 retrieval engine** is implemented in [`pipeline/retrieval/`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/retrieval/), and production retrieval benchmarking is orchestrated via [`scripts/run_retrieval_eval.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/scripts/run_retrieval_eval.py) and [`scripts/run_pipeline.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/scripts/run_pipeline.py) using the 20 audited ground-truth benchmark questions in [`evaluation/data/evaluation_questions.jsonl`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/evaluation/data/evaluation_questions.jsonl).

This directory contains a lightweight, inspectable, local evaluation harness designed to test text extraction, page grounding, and retrieval performance over official HUDCO documents without requiring production databases, heavy frameworks, or cloud APIs.

```
                              EVALUATION PIPELINE
  ┌────────────────────────────────────────────────────────────────────────┐
  │  data/raw/annual_reports/ar26.pdf (520 physical pages)                 │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      ▼
                      [ evaluation/extractor.py ]
         - Page-by-page extraction (Physical P.1 to P.520)
         - Detects printed page labels from headers (e.g. "18 | ANNUAL REPORT")
         - Captures Front Matter (Pages 1-19) as sec_00
         - Flags empty pages, short divider spreads, and financial tables
                                      │
                                      ▼
                      [ evaluation/chunker.py ]
         - Paragraph-aware, section-bound chunking (500 - 1,500 chars)
         - Preserves Physical Page, Printed Page, Section ID, & Table Flag
         - Deterministic IDs: HUDCO_AR_2025_26_c412ce14_secXX_pXXX_cXX
                                      │
                                      ▼
                   [ evaluation/retriever_bm25.py ]
         - Pure-Python BM25Okapi baseline (k1=1.5, b=0.75)
         - Per-term score explanations and matched keyword inspection
                                      │
                                      ▼
                  [ evaluation/run_evaluation.py ]
         - Evaluates curated questions from evaluation_questions.jsonl
         - Computes Recall@1, Recall@3, Recall@5, MRR on verified ground truth
         - Outputs Markdown audit report, JSONL results, and CSV exports
```

---

## 1. Quickstart & Execution Commands

### Prerequisites
Activate the isolated virtual environment:
```powershell
# In project root:
.\.venv\Scripts\Activate.ps1
```

### Command 1: Prepare Documents (Page Extraction & Chunking)
Extracts all 520 physical pages from `ar26.pdf` (including front matter pages 1–19) and builds validated, page-grounded evaluation chunks:
```powershell
.\.venv\Scripts\python -m evaluation.run_evaluation --prepare --mode retrieval
```

### Command 2: Run Retrieval-Only Evaluation (BM25 Baseline)
Runs the 12 curated benchmark questions against the indexed chunks, measures Recall@5 and MRR, and produces an inspectable Markdown report:
```powershell
.\.venv\Scripts\python -m evaluation.run_evaluation --mode retrieval
```

### Command 3: Custom Top-K Candidates or Custom Questions
```powershell
.\.venv\Scripts\python -m evaluation.run_evaluation --top-k 10 --questions evaluation/data/evaluation_questions.jsonl
```

### Command 4: Optional Local LLM Evaluation (Requires Ollama)
If you install Ollama and run a model locally (e.g. `ollama run qwen2.5:7b`), run in full mode:
```powershell
.\.venv\Scripts\python -m evaluation.run_evaluation --mode full
```

---

## 2. Directory Layout & Artifacts

```
evaluation/
├── config.py                     # Path definitions, thresholds, and parameters
├── schemas.py                    # Strict Pydantic models for chunks, queries, and reports
├── extractor.py                  # Page-by-page extractor with table & printed page detection
├── chunker.py                    # Section-aware windowed chunker
├── retriever_bm25.py             # Self-contained BM25Okapi lexical retriever
├── generator_ollama.py           # Optional Ollama answer generator & citation validator
├── run_evaluation.py             # CLI runner orchestrating evaluation runs
├── data/
│   └── evaluation_questions.jsonl# Benchmark questions with verified ground-truth pages
├── extracted/                    # Output from --prepare
│   ├── extracted_pages.jsonl     # 520 page extraction records with quality flags
│   ├── evaluation_chunks.jsonl   # Generated evaluation chunks
│   └── extraction_summary.json   # Diagnostic counts of empty/table pages
└── runs/                         # Output from evaluation runs
    └── run_<timestamp>/
        ├── evaluation_run_report.md   # Human-readable evaluation audit report
        ├── evaluation_run_report.json # Complete machine-readable results
        └── retrieval_results.csv      # Tabular CSV with hit status per candidate
```

---

## 3. Data Formats & Schemas

### Evaluation Question Schema (`evaluation_questions.jsonl`)
```json
{
  "question_id": "Q01",
  "question": "Who is the Chairman and Managing Director (CMD) of HUDCO and when did he assume charge?",
  "category": "direct_fact",
  "expected_answer": "Shri Sanjay Kulshrestha, aged 57 years, assumed charge as the Chairman & Managing Director (CMD) of HUDCO on 16th October 2023.",
  "expected_source_document": "HUDCO_AR_2025_26_c412ce14",
  "expected_pdf_pages": [22],
  "expected_printed_pages": [20],
  "expected_relevant_chunk_ids": [],
  "answerability": "answerable",
  "evaluation_notes": "Section 02 (Board of Directors), physical page 22, printed page 20."
}
```

### Evaluation Chunk Schema (`evaluation_chunks.jsonl`)
```json
{
  "chunk_id": "HUDCO_AR_2025_26_c412ce14_sec_02_p022_c00",
  "document_id": "HUDCO_AR_2025_26_c412ce14",
  "source_filename": "ar26.pdf",
  "section_id": "sec_02",
  "section_title": "Board of Directors",
  "physical_page": 22,
  "printed_page": 20,
  "chunk_index": 0,
  "char_count": 1250,
  "token_estimate": 312,
  "has_table": false,
  "content": "Brief Profile of Directors\nShri Sanjay Kulshrestha, aged 57 years...",
  "sha256": "4b9e7..."
}
```

---

## 4. Grounding & Page-Integrity Verification

1. **Physical PDF Pages vs Printed Report Pages**:
   - `physical_page`: Exact 1-based index in the PDF file (1 to 520).
   - `printed_page`: Extracted directly from running headers (`ANNUAL REPORT ... | XX` or `XX | ANNUAL REPORT`).
   - If a page has no printed number (e.g. covers, divider graphics), `printed_page` is set to `null` while `physical_page` is always preserved.
2. **Front Matter Inclusion**:
   - Pages 1–19 (omitted by the earlier Stage 1 slice) are extracted directly from `ar26.pdf` and assigned to `sec_00 (Front Matter & Contents)`.
3. **Empty & Photographic Spreads**:
   - Blank or photo-only pages (e.g. physical pages 1, 2, 4, 6–19, 24) are recorded in `extraction_summary.json` with quality warnings and do not create empty chunks.

---

## 5. Evaluation Metrics

- **Recall@K (K=1, 3, 5)**: Proportion of eligible questions where at least one verified ground-truth physical page was retrieved in the top K positions.
- **MRR (Mean Reciprocal Rank)**: $\frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$ of the first retrieved chunk from an expected physical page.
- **Zero-Retrieval Queries**: Count of queries where BM25 matched zero tokens in the corpus.
- **Abstention Precision**: For unanswerable queries (e.g. cryptocurrency or non-existent overseas branches), checks if the response correctly abstains (`INSUFFICIENT_EVIDENCE`).
- **Citation Precision**: In full mode, measures $\frac{\text{Verified Chunk Citations}}{\text{Total Chunk Citations}}$.

---

## 6. Testing Instructions

Unit tests are located in [`tests/test_evaluation.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/tests/test_evaluation.py).  
*In accordance with project restrictions, tests are written but not executed until explicitly requested.*  
To run when authorized:
```powershell
.\.venv\Scripts\python -m unittest tests.test_evaluation
```
