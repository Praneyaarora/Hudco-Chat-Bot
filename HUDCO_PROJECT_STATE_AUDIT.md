# HUDCO Enterprise Conversational AI — Comprehensive Repository Audit & State Documentation

**Document Title**: HUDCO Project State Audit & Technical Baseline  
**Auditor Role**: Senior AI/ML Engineer, RAG Architect, Data Engineer & Technical Auditor  
**Audit Date**: October 19, 2026  
**Target Repository**: `c:\Users\Praneya Arora\Desktop\Hudco`  
**Document Status**: Authoritative Technical Living Reference  

---

## 1. Executive Summary

The **Housing and Urban Development Corporation Limited (HUDCO)** RAG project is conceived as an enterprise-grade conversational knowledge layer over official HUDCO annual reports, housing finance guidelines (such as PMAY-U 2.0), circulars, forms, website pages, and office directory listings.

This technical audit conducted an exhaustive inspection of the current workspace, source code, data artifacts, historical run manifests, test suites, schemas, and architecture blueprints. The primary conclusion is:

> **Current State Summary**: The project possesses an **exceptionally well-engineered, verified, and operational Stage 1 Ingestion and Document Segmentation Pipeline**, capable of streaming PDF acquisition, single-pass SHA-256 deduplication, structural bookmark quality evaluation, fallback Table of Contents (TOC) page discovery, printed-to-physical page offset calculation, and memory-safe sub-document PDF splitting.  
> 
> However, **Stages 2, 3, 4, and 5 exist only as isolated modules, foundational schemas, or architectural designs**. They lack end-to-end orchestration scripts, have not processed real data into downstream knowledge chunks or vector collections, and have their required runtime dependencies commented out in `requirements.txt`. Furthermore, critical data-integrity flaws exist in Stage 1—notably the omission of PDF front matter (pages 1–19) and page boundary shifts due to document-wide offset generalization.

### Key Audit Findings at a Glance

| Pipeline Subsystem | Implementation Status | Verification Level | Critical Evidence & Artifacts |
|---|---|---|---|
| **Stage 1: Ingestion & Segmentation** | **Implemented & Operational** | **Verified with Production Data & Unit Tests** | `pipeline/stage_1_ingestion/` (404-line CLI `run_stage1.py`), 12 unit tests passing, successfully processed 520-page `ar26.pdf` into 19 section PDFs. |
| **Stage 2: Hybrid Parsing & Cleaning** | **Partially Implemented (Skeleton)** | **Unverified / No Orchestrator** | `pipeline/stage_2_parsing/` contains `TextCleaner`, `TableExtractor`, and `HTMLCrawler`. No CLI/runner exists; dependencies commented out; 0 markdown files output. |
| **Stage 3: Structuring & Intent Tagging**| **Partially Implemented (Schemas Only)**| **Unverified / No Chunks Generated** | `pipeline/stage_3_structuring/` defines master Pydantic `UnifiedChunk` schema and rule-based keyword classifier. No text chunker or LLM integration exists; `data/output_chunks/` empty. |
| **Stage 4: Dual Storage Architecture** | **Partially Implemented (Model Level)** | **Unverified / No Active DB or Index**| `pipeline/stage_4_storage/` defines `ChromaVectorLoader` and SQLAlchemy models. Chroma DB and PostgreSQL have 0 active records; `chromadb`, `sentence-transformers`, `sqlalchemy` commented out. |
| **Stage 5: API & Retrieval Runtime** | **Documented Only / Not Implemented** | **Non-Existent on Disk** | Documented in `README_ARCHITECTURE_AND_PLANNING.md` (FastAPI, Redis, hybrid dense+BM25 retrieval). Directory `pipeline/stage_5_api/` does not exist. |

---

## 2. Audit Scope, Method, and Limitations

### 2.1 Scope of Inspection
The audit encompasses all files within the repository workspace:
- Configuration and settings (`config/`)
- All pipeline stages (`pipeline/stage_1_ingestion/`, `stage_2_parsing/`, `stage_3_structuring/`, `stage_4_storage/`)
- Test suites (`tests/test_stage1.py`)
- Persistent data stores, raw inputs, intermediate splits, and historical run logs (`data/`)
- Architecture blueprints and documentation (`README_ARCHITECTURE_AND_PLANNING.md`, `docs/`, stage READMEs)
- Dependency specifications (`requirements.txt`)

### 2.2 Audit Methodology
1. **Source Code Static Analysis**: Line-by-line inspection of classes, functions, error traps, regex patterns, and data contracts.
2. **Artifact & Manifest Forensic Cross-Check**: Deep inspection of `data/document_registry.json`, `data/intermediate/ingestion_runs/run_20260923_212152/` (`stage1_manifest.json`, `stage1_run_report.md`, `toc_analysis.json`), and disk verification of the 19 generated section PDFs.
3. **Documentation Discrepancy Reconciliation**: Rigorous comparison of README architectural claims against actual working code.
4. **Non-Invasive Protocol**: Adhering strictly to mandatory operating rules, no code was executed, no network requests or crawls were initiated, and no source files or datasets were modified.

### 2.3 Operating Constraints & Limitations
- **No Active Virtualenv Execution**: Test suite results and pipeline executions are evaluated from historical reports and static code structures rather than live execution.
- **External Network Inaccessibility**: External HUDCO URLs (`https://hudco.org.in/...`) were audited via existing local downloads and manifest logs without initiating live HTTP probes.
- **Dependency Inactivity**: Dependencies for Stages 2–4 are commented out in `requirements.txt`. Code referencing `pdfplumber`, `trafilatura`, `bs4`, `chromadb`, and `sqlalchemy` is audited statically.

---

## 3. Current Project Status and Completion Matrix

To prevent conflating architectural intent with implemented code, all components are classified into six distinct operational states:

1. **Implemented and Verified**: Code exists, executes, produces verified artifacts, and is backed by test coverage or operational logs.
2. **Implemented but Not Verified**: Code exists in Python files, but has no orchestrator, no unit tests, and has not produced verified disk artifacts.
3. **Partially Implemented**: Code exists for subsets of the feature (e.g., schemas or utility helpers), but critical logic (e.g., chunk splitting, LLM structuring) is missing.
4. **Documented but Not Implemented**: Feature is detailed in architecture diagrams or READMEs but has no corresponding codebase.
5. **Blocked or Broken**: Feature is impeded by missing dependencies, structural page omissions, or broken contract assumptions.
6. **Proposed or Future Work**: Explicitly recorded as a future enhancement.

### Component Completion Matrix

| Component / Subsystem | Current State | File Reference | Primary Evidence & Notes |
|---|---|---|---|
| **Streaming PDF Downloader** | Implemented and Verified | [`pipeline/stage_1_ingestion/downloader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py) | 64KB chunked stream, `.part` staging, magic byte check, retries (Lines 87–240). Unit Tests A, E, F pass. |
| **Single-Pass SHA-256 Hashing** | Implemented and Verified | [`pipeline/stage_1_ingestion/downloader.py:125-142`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py#L125-L142) | Incremental hash computed during byte streaming; avoids secondary disk read. Unit Test B passes. |
| **Document Content Deduplication** | Implemented and Verified | [`pipeline/stage_1_ingestion/downloader.py:165-185`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py#L165-L185) | Checked against `document_registry.json`. Verified in `run_20260923_212152` (`is_duplicate: true`). Unit Test C passes. |
| **Filename Collision Protection** | Implemented and Verified | [`pipeline/stage_1_ingestion/downloader.py:186-218`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py#L186-L218) | Appends `_{sha8}` if distinct file has identical filename. Unit Test D passes. |
| **Local File Intake** | Implemented and Verified | [`pipeline/stage_1_ingestion/downloader.py:241-292`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py#L241-L292) | Validates magic bytes, computes SHA-256, registers locally without downloading. |
| **Deterministic Fingerprinting** | Implemented and Verified | [`pipeline/stage_1_ingestion/fingerprint.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/fingerprint.py) | Derives `document_id`, fiscal year, content title, flags filename vs content conflicts (Lines 20–135). |
| **Native Bookmark Quality Gate** | Implemented and Verified | [`pipeline/stage_1_ingestion/segmenter.py:90-140`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L90-L140) | Correctly classified `ar26.pdf` bookmarks as `WEAK` due to uninformative titles ("1", "2", "Final_Final..."). Unit Test H passes. |
| **TOC Page Discovery Fallback** | Implemented and Verified | [`pipeline/stage_1_ingestion/segmenter.py:142-232`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L142-L232) | Scans first 35 pages, parses 19 section entries via regex on physical page 5. |
| **Printed-to-Physical Page Mapping** | Implemented and Verified (with Known Defect) | [`pipeline/stage_1_ingestion/segmenter.py:234-317`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L234-L317) | Offset voting heuristic applied dominant offset (+2). **Defect**: Misses front matter (pages 1–19) and skews sections where offset is 0. |
| **Non-Overlapping Section Splitting**| Implemented and Verified | [`pipeline/stage_1_ingestion/segmenter.py:392-443`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L392-L443) | Generated 19 standalone sub-PDFs in `data/intermediate/sections/`. Verified page accounting. |
| **Stage 1 CLI Runner & Audit Gen** | Implemented and Verified | [`pipeline/stage_1_ingestion/run_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/run_stage1.py) | Generates `stage1_manifest.json`, `stage1_run_report.md`, and `toc_analysis.json`. |
| **Text Normalization & Boilerplate Filter** | Implemented but Not Verified | [`pipeline/stage_2_parsing/text_cleaner.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/text_cleaner.py) | Standalone class with regex header/footer removal and proxy form filter. No tests, no orchestrator. |
| **Financial Table Markdown Extractor** | Implemented but Not Verified | [`pipeline/stage_2_parsing/table_extractor.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/table_extractor.py) | `matrix_to_markdown` and `extract_tables_from_pdf` (via `pdfplumber`). Unverified; `pdfplumber` commented out. |
| **HTML Web & FAQ Scraper** | Implemented but Not Verified | [`pipeline/stage_2_parsing/html_crawler.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/html_crawler.py) | Scrapes pages via `trafilatura` and FAQ accordions via `bs4`. Unverified; dependencies commented out. |
| **Stage 2 Orchestrator** | Documented but Not Implemented | `pipeline/stage_2_parsing/` | Missing `run_stage2.py`. No intermediate clean markdown files exist. |
| **Unified Knowledge Chunk Schema** | Implemented and Verified (Syntactically) | [`pipeline/stage_3_structuring/schemas.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/schemas.py) | Full Pydantic v2 model hierarchy (`UnifiedChunk`, `SourceMetadata`, `ClassificationMetadata`, etc.). |
| **Domain Intent Taxonomy** | Implemented but Not Verified | [`pipeline/stage_3_structuring/intent_classifier.py:24-38`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py#L24-L38)| 13 hardcoded intent categories defined. |
| **Rule-Based Intent Classifier** | Implemented but Not Verified | [`pipeline/stage_3_structuring/intent_classifier.py:46-70`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py#L46-L70)| Keyword-based heuristic. Lacks confidence scoring, multi-label tagging, or fallback review thresholds. |
| **LLM-Assisted Structuring** | Documented but Not Implemented | [`pipeline/stage_3_structuring/intent_classifier.py:1-4`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py#L1-L4)| Mentioned in module docstrings, but 0 LLM API calls or prompt chains exist. |
| **Semantic & Windowed Chunking** | Documented but Not Implemented | `pipeline/stage_3_structuring/` | No code breaks text into 150–2500 character chunks. `data/output_chunks/` has only `.gitkeep`. |
| **ChromaDB Vector Loader** | Implemented but Not Verified | [`pipeline/stage_4_storage/chroma_loader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/chroma_loader.py) | Standalone class for embedding and upserting `UnifiedChunk`. `chromadb` commented out; `data/chroma_db/` empty. |
| **Relational Schema (SQLAlchemy)**| Implemented but Not Verified | [`pipeline/stage_4_storage/db_registry.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/db_registry.py) | Defines `DocumentRegistry`, `ChunkRegistry`, `OfficeDirectory`. No engine, migrations, or active DB. |
| **BM25 Keyword Hybrid Search** | Documented but Not Implemented | `pipeline/stage_4_storage/`, `README_ARCHITECTURE_AND_PLANNING.md` | Claimed in architecture doc, but no `rank-bm25` code is implemented. |
| **RAG Runtime & Chatbot API** | Documented but Not Implemented | `pipeline/stage_5_api/` | Architecture blueprint specifies FastAPI, Redis session cache, Gemini prompt grounding. Directory does not exist. |
| **Website Discovery & URL Crawler**| Documented but Not Implemented | Root / Pipeline | Pipeline accepts single URLs via CLI; no automated crawler or link discovery module exists. |

---

## 4. Repository Structure and File Inventory

### 4.1 Directory Tree

```
c:\Users\Praneya Arora\Desktop\Hudco\
├── README_ARCHITECTURE_AND_PLANNING.md          # [Doc] Global blueprint, architecture diagrams, schemas (22 KB)
├── requirements.txt                             # [Config] Python dependencies (active: pypdf, requests, pydantic) (362 B)
├── config/
│   ├── __init__.py                              # [Code] Package marker (79 B)
│   └── settings.py                              # [Code] Pydantic BaseSettings: paths, limits, model names (3.4 KB)
├── docs/
│   └── README_ARCHITECTURE_AND_PLANNING.md      # [Doc] Mirror copy of root architecture document (22 KB)
├── pipeline/
│   ├── stage_1_ingestion/
│   │   ├── __init__.py                          # [Code] Exports downloader, segmenter, fingerprinter (502 B)
│   │   ├── downloader.py                        # [Code] Streaming downloader, SHA-256, deduplication (12.1 KB)
│   │   ├── fingerprint.py                       # [Code] Content & filename identity resolver (5.3 KB)
│   │   ├── segmenter.py                         # [Code] TOC parser, page offset mapper, PDF splitter (18.3 KB)
│   │   ├── run_stage1.py                        # [Code] CLI runner & audit manifest generator (16.2 KB)
│   │   └── README_STAGE_1_INGESTION.md          # [Doc] Stage 1 design specs, acceptance test log (13.0 KB)
│   ├── stage_2_parsing/
│   │   ├── __init__.py                          # [Code] Exports cleaner, table extractor, html crawler (319 B)
│   │   ├── text_cleaner.py                      # [Code] Regex header/footer cleaner & boilerplate detector (1.8 KB)
│   │   ├── table_extractor.py                   # [Code] Markdown table formatter & pdfplumber interface (2.6 KB)
│   │   ├── html_crawler.py                      # [Code] Trafilatura & BeautifulSoup web page/FAQ scraper (1.9 KB)
│   │   └── README_STAGE_2_EXTRACTION.md         # [Doc] Stage 2 component overview (978 B)
│   ├── stage_3_structuring/
│   │   ├── __init__.py                          # [Code] Exports UnifiedChunk and IntentClassifier (460 B)
│   │   ├── schemas.py                           # [Code] Pydantic models for Unified Knowledge Schema (2.8 KB)
│   │   ├── intent_classifier.py                 # [Code] Taxonomy definition & rule-based classifier (5.0 KB)
│   │   └── README_STAGE_3_INTENT_TAGGING.md     # [Doc] Stage 3 overview and schema reference (968 B)
│   └── stage_4_storage/
│       ├── __init__.py                          # [Code] Exports ChromaVectorLoader and DB models (402 B)
│       ├── chroma_loader.py                     # [Code] ChromaDB persistent client & embedder interface (4.0 KB)
│       ├── db_registry.py                       # [Code] SQLAlchemy models for PostgreSQL (2.4 KB)
│       └── README_STAGE_4_STORAGE_AND_RAG.md    # [Doc] Dual storage architecture summary (2.2 KB)
├── tests/
│   └── test_stage1.py                           # [Test] 12 unit tests (Tests A–L) for Stage 1 ingestion (11.3 KB)
└── data/
    ├── document_registry.json                   # [Manifest] Local JSON registry tracking ingested files/hashes (1.1 KB)
    ├── raw/
    │   ├── annual_reports/
    │   │   ├── .gitkeep                         # Git directory keep
    │   │   └── ar26.pdf                         # [Source Data] Ingested HUDCO 56th Annual Report 2025-26 (11.76 MB)
    │   ├── circulars/
    │   │   └── .gitkeep                         # [Empty] Unpopulated directory for schemes/circulars
    │   └── web_pages/
    │       └── .gitkeep                         # [Empty] Unpopulated directory for scraped web pages
    ├── intermediate/
    │   ├── ingestion_runs/
    │   │   ├── run_20260923_212106/             # [Historical Run 1: First ingestion of ar26.pdf]
    │   │   │   ├── stage1_manifest.json         # Machine manifest (is_duplicate: false) (14.5 KB)
    │   │   │   ├── stage1_run_report.md         # Markdown audit report (6.3 KB)
    │   │   │   └── toc_analysis.json            # Outline evaluation & page offset diagnostics (6.0 KB)
    │   │   └── run_20260923_212152/             # [Historical Run 2: Idempotent rerun / deduplication test]
    │   │       ├── stage1_manifest.json         # Machine manifest (is_duplicate: true) (14.5 KB)
    │   │       ├── stage1_run_report.md         # Markdown audit report (6.3 KB)
    │   │       └── toc_analysis.json            # Identical TOC diagnostics (6.0 KB)
    │   └── sections/                            # [Intermediate Output] 19 discrete section PDFs
    │       ├── .gitkeep
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_01_Reference_Information.pdf (284 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_02_Board_of_Directors.pdf (296 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_03_Chairman_s_Message.pdf (719 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_04_Notice_of_AGM.pdf (394 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_05_Directors_Report.pdf (853 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_06_Management_Discussion_Analysis_Report.pdf (214 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_07_Corporate_Governance_Report.pdf (702 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_08_Business_Responsibility_Sustainability_Report.pdf (800 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_09_Independent_Reasonable_Assurance_Report_on_BRSR_Co.pdf (267 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_10_Secretarial_Audit_Report.pdf (368 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_11_Annual_Report_on_Corporate_Social_Responsibility_A.pdf (396 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_12_Management_Reply_to_Independent_Auditor_s_Report.pdf (127 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_13_Comments_of_the_CAG_on_Standalone_Financial_Statem.pdf (250 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_14_Comments_of_the_CAG_on_Consolidated_Financial_Stat.pdf (644 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_15_Standalone_Financial_Statements.pdf (2.41 MB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_16_Consolidated_Financial_Statements.pdf (1.92 MB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_17_Information_on_Sanctions_Releases.pdf (160 KB)
    │       ├── HUDCO_AR_2025_26_c412ce14_sec_18_Management_Team.pdf (396 KB)
    │       └── HUDCO_AR_2025_26_c412ce14_sec_19_HUDCO_Offices.pdf (560 KB)
    ├── output_chunks/                           # [Final Output Store] Empty (Contains only .gitkeep)
    └── chroma_db/                               # [Vector Store] Empty directory (No SQLite or binary indices)
```

### 4.2 Comprehensive Source File Inventory

| File Path | Functional Responsibility | Key Classes / Functions | Inputs | Outputs | Dependencies |
|---|---|---|---|---|---|
| [`config/settings.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/config/settings.py) | Global configuration singleton managing paths, limits, model names, and DB strings. | `class Settings(BaseSettings)`, `init_directories()` | `.env` file, Environment variables | Initialized directories, `settings` object | `pydantic-settings`, `pydantic`, `pathlib` |
| [`pipeline/stage_1_ingestion/downloader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py) | Stream acquisition, magic byte validation, single-pass SHA-256 calculation, and registry deduplication. | `class DocumentDownloader`: `download_file()`, `ingest_local_file()`, `compute_sha256_of_file()` | URL or local file path | Stored raw PDF, `.part` cleanup, metadata dict | `requests`, `hashlib`, `json`, `config.settings` |
| [`pipeline/stage_1_ingestion/fingerprint.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/fingerprint.py) | Content-derived and filename-derived identity resolution; conflict detection. | `class DocumentFingerprinter`: `fingerprint()` | Raw PDF path, received filename, SHA-256 | Identity dictionary, `document_id`, conflict flags | `pypdf.PdfReader`, `re`, `logging` |
| [`pipeline/stage_1_ingestion/segmenter.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py) | Structural inspection, outline validation, TOC regex parsing, page offset mapping, and PDF splitting. | `class PDFSegmenter`: `inspect_structure()`, `validate_outline_quality()`, `discover_and_parse_toc()`, `map_printed_to_physical_pages()`, `build_section_plan()`, `split_pdf()` | Raw PDF, output directory | Section plan, split section PDFs on disk | `pypdf.PdfReader`, `pypdf.PdfWriter`, `gc`, `collections.Counter` |
| [`pipeline/stage_1_ingestion/run_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/run_stage1.py) | End-to-end Stage 1 CLI orchestrator; validation checks; generates audit reports and manifests. | `run_stage_1()`, `generate_run_report_markdown()` | CLI flags (`--url`, `--file`, `--document-type`) | `stage1_manifest.json`, `stage1_run_report.md`, `toc_analysis.json` | `downloader`, `fingerprint`, `segmenter`, `argparse` |
| [`pipeline/stage_2_parsing/text_cleaner.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/text_cleaner.py) | Regex-based cleaning of running headers, footers, page numbers, and proxy voting boilerplate. | `class TextCleaner`: `clean_text()`, `is_boilerplate()` | Raw extracted text strings | Cleaned normalized text, boolean boilerplate flag | `re`, `typing` |
| [`pipeline/stage_2_parsing/table_extractor.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/table_extractor.py) | Formats 2D cell matrices into GitHub Markdown tables; interfaces with `pdfplumber`. | `class TableExtractor`: `matrix_to_markdown()`, `extract_tables_from_pdf()` | Section PDF file path | List of table dictionaries with markdown strings | `pdfplumber` (optional/uninstalled), `pathlib` |
| [`pipeline/stage_2_parsing/html_crawler.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/html_crawler.py) | Scrapes HUDCO web pages using Trafilatura and extracts FAQ accordions using BeautifulSoup. | `class HTMLCrawler`: `crawl_page()` | Webpage URL | Dictionary containing title, core article markdown, and FAQ list | `requests`, `bs4`, `trafilatura` (uninstalled) |
| [`pipeline/stage_3_structuring/schemas.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/schemas.py) | Master data contract for atomic chunks with provenance citations, tables, and taxonomy metadata. | `UnifiedChunk`, `SourceMetadata`, `ClassificationMetadata`, `ContentPayload`, `ChunkMetadata`, `TableItem` | Raw chunk dictionaries | Validated Pydantic models | `pydantic` (v2), `datetime` |
| [`pipeline/stage_3_structuring/intent_classifier.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py) | Maps text to HUDCO domain intents using keyword heuristics; instantiates `UnifiedChunk`. | `class IntentClassifier`: `classify_rule_based()`, `create_unified_chunk()` | Title, text content, tables, metadata | Validated `UnifiedChunk` instance | `hashlib`, `datetime`, `schemas` |
| [`pipeline/stage_4_storage/chroma_loader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/chroma_loader.py) | Vector database client embedding chunks via SentenceTransformers and upserting into ChromaDB. | `class ChromaVectorLoader`: `load_chunks()`, `query_semantic()` | List of `UnifiedChunk` instances, query string | Chroma upsert counts, semantic query results | `chromadb`, `sentence_transformers` (uninstalled) |
| [`pipeline/stage_4_storage/db_registry.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/db_registry.py) | Declarative relational database models for PostgreSQL tracking documents, chunks, and offices. | `DocumentRegistry`, `ChunkRegistry`, `OfficeDirectory` | Relational database engine | SQLAlchemy ORM mapped tables | `sqlalchemy` (uninstalled) |
| [`tests/test_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/tests/test_stage1.py) | Unit test suite covering Tests A through L for Stage 1. | `class TestStage1Ingestion(unittest.TestCase)` | Synthetic in-memory/temp PDFs | 12 test assertions verifying download, hash, dedup, and splitting | `unittest`, `unittest.mock`, `pypdf`, `tempfile` |

### 4.3 Redundant, Orphaned, or Incomplete Components
1. **Redundant Documentation**: [`docs/README_ARCHITECTURE_AND_PLANNING.md`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/docs/README_ARCHITECTURE_AND_PLANNING.md) is an exact duplicate (byte-for-byte, 22,066 bytes) of [`README_ARCHITECTURE_AND_PLANNING.md`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/README_ARCHITECTURE_AND_PLANNING.md) in the project root.
2. **Missing Stage Orchestrators**: No `run_stage2.py`, `run_stage3.py`, or `run_stage4.py` exist.
3. **Empty Output Stores**:
   - `data/output_chunks/` has only `.gitkeep`.
   - `data/chroma_db/` is completely empty.
   - `data/raw/circulars/` and `data/raw/web_pages/` contain only `.gitkeep`.
4. **Missing Directory**: `pipeline/stage_5_api/` is documented in architecture diagrams but absent from the file system.

---

## 5. Actual End-to-End Pipeline

To establish what the codebase actually does versus what is documented, each of the 20 lifecycle stages is audited below:

### Stage-by-Stage Forensic Audit

```
[Stages 1-7: VERIFIED] ──► [Stage 8: VERIFIED FALLBACK] ──► [Stage 9: PARTIAL] ──► [Stages 10-20: UNVERIFIED / NOT IMPLEMENTED]
```

#### 1. Official HUDCO Website URL and Link Discovery
- **Status**: **Documented but Not Implemented**.
- **Implementation**: No web scraper or link discovery crawler exists to traverse `https://hudco.org.in`.
- **Actual Behavior**: The user must manually supply URLs (e.g. `--url https://hudco.org.in/writereaddata/ar26.pdf`) via CLI arguments to [`pipeline/stage_1_ingestion/run_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/run_stage1.py).

#### 2. HTML Page Collection and Parsing
- **Status**: **Partially Implemented (Skeleton)**.
- **Implementation**: [`pipeline/stage_2_parsing/html_crawler.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/html_crawler.py) defines `HTMLCrawler.crawl_page()`.
- **Actual Behavior**: Uses `requests.get()`, `trafilatura.extract()`, and `bs4.BeautifulSoup`. However, it has never been invoked in an end-to-end run. `data/raw/web_pages/` contains only `.gitkeep`.

#### 3. PDF Link Discovery and Document Identification
- **Status**: **Documented but Not Implemented**.
- **Implementation**: No dynamic PDF discovery. Identification occurs only after an explicit URL or file is fed into the system.

#### 4. Document Catalogue Creation and Maintenance
- **Status**: **Implemented and Verified (JSON-based)**.
- **Implementation**: [`pipeline/stage_1_ingestion/downloader.py:42-76`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py#L42-L76).
- **Actual Behavior**: Reads and updates [`data/document_registry.json`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/document_registry.json), maintaining dual lookup maps: `documents[file_name]` and `hashes[sha256]`. (Note: The PostgreSQL catalogue documented in README is not implemented).

#### 5. Document Selection, Filtering, and Approval
- **Status**: **Not Implemented**.
- **Implementation**: None. Ingestion executes immediately upon CLI invocation without any human-in-the-loop approval or filtering stage.

#### 6. Downloading, Local Intake, Deduplication, and Fingerprinting
- **Status**: **Implemented and Verified**.
- **Implementation**: [`pipeline/stage_1_ingestion/downloader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py) and [`fingerprint.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/fingerprint.py).
- **Actual Behavior**: Streams files to temporary `.part` paths, validates `%PDF-` magic bytes, calculates SHA-256 incrementally, deduplicates against `document_registry.json`, handles filename collisions (`{name}_{sha8}.pdf`), extracts metadata title/author, and generates canonical ID (e.g. `HUDCO_AR_2025_26_c412ce14`).

#### 7. PDF Triage (Page Count, File Size, Native Text, Scan Detection)
- **Status**: **Partially Implemented**.
- **Implementation**: [`pipeline/stage_1_ingestion/segmenter.py:43-89`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L43-L89).
- **Actual Behavior**: Accurately counts physical pages (520) and inspects PDF metadata. **Limitation**: Does not perform native text ratio calculations or image-density scan detection. Purely scanned PDFs will fail downstream extraction silently.

#### 8. Table of Contents & Outline Detection
- **Status**: **Implemented and Verified**.
- **Implementation**: [`pipeline/stage_1_ingestion/segmenter.py:90-232`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L90-L232).
- **Actual Behavior**: Implements a two-tier strategy. First inspects PDF outline bookmarks (`reader.outline`) and evaluates quality (entry count, title substance, monotonicity). If bookmarks are `WEAK` or `INVALID` (as was true for `ar26.pdf`), it automatically triggers fallback TOC page discovery scanning the first 35 pages for "Contents/Table of Contents" headings and regex matching section rows (`title ... page`).

#### 9. PDF Text Extraction, Page Mapping, and OCR
- **Status**: **Partially Implemented (Text only / OCR Absent)**.
- **Implementation**: Page mapping implemented in [`segmenter.py:234-317`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L234-L317).
- **Actual Behavior**: Mapping infers offset between printed page numbers and physical PDF pages via keyword verification on target pages. Text extraction is performed using `pypdf.PageObject.extract_text()`. OCR is not implemented anywhere in the repository.

#### 10. HTML Text Extraction and DOM Cleanup
- **Status**: **Partially Implemented (Skeleton)**.
- **Implementation**: [`pipeline/stage_2_parsing/html_crawler.py:34-45`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/html_crawler.py#L34-L45).
- **Actual Behavior**: Trafilatura cleans main article body and strips navbars. BeautifulSoup parses accordion questions. Unexecuted on production data.

#### 11. Noise Removal, Normalization, and Content Cleaning
- **Status**: **Partially Implemented (Unit Level)**.
- **Implementation**: [`pipeline/stage_2_parsing/text_cleaner.py:30-46`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/text_cleaner.py#L30-L46).
- **Actual Behavior**: Regex patterns strip repeated corporation headers, annual report footers, and solitary line numbers. Collapses multiple whitespace.

#### 12. Section Extraction and Segmentation
- **Status**: **Implemented and Verified**.
- **Implementation**: [`pipeline/stage_1_ingestion/segmenter.py:392-443`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L392-L443).
- **Actual Behavior**: Uses `pypdf.PdfWriter` to slice physical page ranges, creating 19 standalone section PDFs in `data/intermediate/sections/`. Enforces garbage collection (`gc.collect()`) after each write to keep memory flat.

#### 13. Document-Type and Knowledge-Tier Classification
- **Status**: **Implemented and Verified (Document Level)**.
- **Implementation**: [`pipeline/stage_1_ingestion/fingerprint.py:56-85`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/fingerprint.py#L56-L85).
- **Actual Behavior**: Tags document as `annual_report` and assigns authority tier (1 for official annual report, default tier in `schemas.py`).

#### 14. Intent Taxonomy and Intent-Based Labeling
- **Status**: **Partially Implemented (Rule-Based Only)**.
- **Implementation**: [`pipeline/stage_3_structuring/intent_classifier.py:46-70`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py#L46-L70).
- **Actual Behavior**: Evaluates text against keyword lists to assign 1 of 13 primary intents (e.g., `FINANCIAL_RESULTS`, `PMAY_SCHEMES`). No confidence scoring, no secondary intent generation, and no ambiguity handling.

#### 15. Chunk Construction and Metadata Attachment
- **Status**: **Partially Implemented (Schema Helper Only)**.
- **Implementation**: [`pipeline/stage_3_structuring/intent_classifier.py:71-135`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py#L71-L135).
- **Actual Behavior**: `create_unified_chunk()` builds a single `UnifiedChunk` object from pre-supplied text. However, no sliding-window, token-based, or heading-based text chunker exists to divide large sections into compliant chunks.

#### 16. Structured JSON/JSONL Generation and Validation
- **Status**: **Documented but Not Implemented**.
- **Implementation**: [`schemas.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/schemas.py) provides Pydantic validation models.
- **Actual Behavior**: No serialization loop or file-writing utility exists for chunks. `data/output_chunks/` contains no JSON or JSONL files.

#### 17. Human Review, Overrides, and Approval Controls
- **Status**: **Not Implemented**.
- **Implementation**: None. No review flags, quarantine states, or approval metadata schemas exist.

#### 18. Embedding Generation and Vector Indexing
- **Status**: **Implemented but Not Verified**.
- **Implementation**: [`pipeline/stage_4_storage/chroma_loader.py:46-94`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/chroma_loader.py#L46-L94).
- **Actual Behavior**: Code embeds `UnifiedChunk` instances using `SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')` and upserts to ChromaDB. However, dependencies are uninstalled and `data/chroma_db/` is completely empty.

#### 19. Keyword Retrieval, Database Storage, and Hybrid Retrieval
- **Status**: **Partially Implemented (Relational Models Only / Retrieval Absent)**.
- **Implementation**: [`pipeline/stage_4_storage/db_registry.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/db_registry.py) defines tables.
- **Actual Behavior**: BM25 hybrid search is not implemented. PostgreSQL database connection is unconfigured and inactive.

#### 20. RAG Integration, Context Assembly, and Response Generation
- **Status**: **Documented but Not Implemented**.
- **Implementation**: None. No API layer, no Gemini LLM prompt orchestration, no session management, and no citation assembly exist in code.

---

## 6. Data Sources and Feeding Mechanisms

### 6.1 Supported vs Documented Intake Channels

| Intake Channel | Implementation Status | Supported Operations | Execution Method |
|---|---|---|---|
| **Remote Annual Report PDF** | **Verified Operational** | Stream download, retry, magic byte check, deduplication, TOC split. | `python -m pipeline.stage_1_ingestion.run_stage1 --url <URL> --document-type annual_report` |
| **Local Pre-downloaded PDF** | **Verified Operational** | Ingest existing file on disk, SHA-256 compute, deduplication, TOC split. | `python -m pipeline.stage_1_ingestion.run_stage1 --file <PATH> --document-type annual_report` |
| **Circulars / Notifications**| **Partially Operational** | Download/local intake supported by `downloader.py`; routing to `data/raw/circulars/`. | Supported by CLI (`--document-type circular`), but no TOC logic tailored to circulars. |
| **Website HTML Pages** | **Code Skeleton Only** | `HTMLCrawler.crawl_page()` exists in isolation. | Not wired to any runner or automated CLI. |
| **Website FAQs / Accordions**| **Code Skeleton Only** | BeautifulSoup CSS selector logic (`.accordion-header`, `dt`). | Not wired to any runner or storage module. |
| **Batch Directory Ingestion** | **Not Implemented** | Only single-file/single-URL arguments accepted. | Proposed future enhancement. |
| **Incremental Website Crawling**| **Not Implemented** | No change detection via sitemaps or `Last-Modified` HTTP headers. | Documented in blueprint only. |

### 6.2 Deduplication and State Transition Logic

Knowledge state transition follows a strict deterministic flow governed by [`pipeline/stage_1_ingestion/downloader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py):

```
                        INGRESS REQUEST
                               │
                               ▼
                   Is source a URL or Local Path?
                     ├── Local Path ──► Validate %PDF- ──► Compute SHA-256
                     └── URL ─────────► Stream .part ──► Check %PDF- ──► Incremental SHA-256
                                                               │
                                                               ▼
                                               Query data/document_registry.json
                                                               │
                              ┌────────────────────────────────┴────────────────────────────────┐
                              ▼                                                                 ▼
                   [ Hash Match Found ]                                              [ Hash Not Found ]
                              │                                                                 │
                              ▼                                                                 ▼
                    Status = DUPLICATE                                                Status = NEW / DOWNLOADED
                 - Delete .part file                                                - Rename .part -> final filename
                 - Return existing metadata                                         - (If collision: append _{sha8})
                 - Set is_duplicate: true                                           - Register in document_registry.json
```

---

## 7. Annual Report and PDF Processing

### 7.1 Production Case Study: HUDCO 56th Annual Report 2025-26
The system was validated using the official HUDCO 2025-26 Annual Report:
- **Raw File**: [`data/raw/annual_reports/ar26.pdf`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/raw/annual_reports/ar26.pdf)
- **Source URL**: `https://hudco.org.in/writereaddata/ar26.pdf`
- **File Size**: 12,335,105 bytes (11.76 MB)
- **Total Physical Pages**: 520
- **Cryptographic Fingerprint (SHA-256)**:  
  `c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41`
- **Canonical Document ID**: `HUDCO_AR_2025_26_c412ce14`

### 7.2 Outline Quality Gate Failure & TOC Discovery
The source PDF has native PDF bookmarks, but they are corrupted and uninformative. The audit log in [`toc_analysis.json`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/intermediate/ingestion_runs/run_20260923_212152/toc_analysis.json) records:

```json
{
  "raw_outline": [
    {"title": "1", "destination_page_index": 0, "physical_page": 1},
    {"title": "2", "destination_page_index": 1, "physical_page": 2},
    {"title": "Final_Final_ANNUAL REPORT HUDCO 2026", "destination_page_index": 2, "physical_page": 3},
    {"title": "3", "destination_page_index": 518, "physical_page": 519},
    {"title": "4", "destination_page_index": 519, "physical_page": 520}
  ],
  "outline_quality": "WEAK",
  "outline_validation_issues": [
    "High proportion of meaningless titles (5/5)."
  ]
}
```

Because `outline_quality` was evaluated as `WEAK`, [`segmenter.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py) activated the fallback **TOC Page Discovery Strategy**:
1. Scanned physical pages 1 to 35 for `CONTENTS` headings and line regex patterns.
2. Discovered the printed contents page on **physical page 5**.
3. Parsed 19 distinct section titles and printed page numbers via regex:  
   `r"^(?P<title>[A-Za-z0-9\s,&’'\-\/\(\)\.]{3,}?)(?:[\.\s\t_]{2,}|\s{2,}|\t|\s+)(?P<page>\d{1,4})\s*$"`

### 7.3 Printed-to-Physical Page Allocation & Critical Integrity Findings

The 19 generated section PDFs on disk are detailed below:

| Sec ID | Section Title | Physical PDF Pages | Printed Report Pages | File Size | Output Artifact Name | Offset Findings |
|---|---|---|---|---|---|---|
| `sec_01` | Reference Information | 20 – 21 (2 pp) | 18 – 19 | 284 KB | `...sec_01_Reference_Information.pdf` | Inferred offset = 2 |
| `sec_02` | Board of Directors | 22 – 23 (2 pp) | 20 – 21 | 296 KB | `...sec_02_Board_of_Directors.pdf` | Inferred offset = 2 |
| `sec_03` | Chairman’s Message | 24 – 36 (13 pp) | 22 – 34 | 719 KB | `...sec_03_Chairman_s_Message.pdf` | **Conflict**: Heading matched at physical page 22 (offset 0), but mapped to 24 |
| `sec_04` | Notice of AGM | 37 – 49 (13 pp) | 35 – 47 | 394 KB | `...sec_04_Notice_of_AGM.pdf` | Inferred offset = 2 |
| `sec_05` | Directors’ Report | 50 – 79 (30 pp) | 48 – 77 | 853 KB | `...sec_05_Directors_Report.pdf` | Inferred offset = 2 |
| `sec_06` | Management Discussion & Analysis Report | 80 – 83 (4 pp) | 78 – 81 | 214 KB | `...sec_06_Management_Discussion_Analysis_Report.pdf` | Heading matched at 79 (offset 1), mapped to 80 |
| `sec_07` | Corporate Governance Report | 84 – 103 (20 pp) | 82 – 101 | 702 KB | `...sec_07_Corporate_Governance_Report.pdf` | **Conflict**: Heading matched at 82 (offset 0), mapped to 84 |
| `sec_08` | Business Responsibility & Sustainability Report | 104 – 154 (51 pp) | 102 – 152 | 800 KB | `...sec_08_Business_Responsibility_Sustainability_Report.pdf`| **Conflict**: Heading matched at 102 (offset 0), mapped to 104 |
| `sec_09` | Independent Assurance Report on BRSR Core | 155 – 159 (5 pp) | 153 – 157 | 267 KB | `...sec_09_Independent_Reasonable_Assurance_Report_on_BRSR_Co.pdf` | Inferred offset = 2 |
| `sec_10` | Secretarial Audit Report | 160 – 163 (4 pp) | 158 – 161 | 368 KB | `...sec_10_Secretarial_Audit_Report.pdf` | Inferred offset = 2 |
| `sec_11` | Annual Report on CSR Activities | 164 – 182 (19 pp) | 162 – 180 | 396 KB | `...sec_11_Annual_Report_on_Corporate_Social_Responsibility_A.pdf` | Inferred offset = 2 |
| `sec_12` | Management Reply to Auditor’s Report | 183 – 183 (1 p) | 181 – 181 | 127 KB | `...sec_12_Management_Reply_to_Independent_Auditor_s_Report.pdf` | Single page section |
| `sec_13` | CAG Comments on Standalone Statements | 184 – 184 (1 p) | 182 – 182 | 250 KB | `...sec_13_Comments_of_the_CAG_on_Standalone_Financial_Statem.pdf` | Single page section |
| `sec_14` | CAG Comments on Consolidated Statements | 185 – 207 (23 pp) | 183 – 205 | 644 KB | `...sec_14_Comments_of_the_CAG_on_Consolidated_Financial_Stat.pdf` | Inferred offset = 2 |
| `sec_15` | Standalone Financial Statements | 208 – 361 (154 pp) | 206 – 359 | 2.41 MB | `...sec_15_Standalone_Financial_Statements.pdf` | Inferred offset = 2 |
| `sec_16` | Consolidated Financial Statements | 362 – 511 (150 pp) | 360 – 509 | 1.92 MB | `...sec_16_Consolidated_Financial_Statements.pdf` | **Conflict**: Heading matched at 360 (offset 0), mapped to 362 |
| `sec_17` | Information on Sanctions/Releases | 512 – 515 (4 pp) | 510 – 513 | 160 KB | `...sec_17_Information_on_Sanctions_Releases.pdf` | **Conflict**: Heading matched at 510 (offset 0), mapped to 512 |
| `sec_18` | Management Team | 516 – 516 (1 p) | 514 – 514 | 396 KB | `...sec_18_Management_Team.pdf` | Inferred offset = 2 |
| `sec_19` | HUDCO Offices | 517 – 520 (4 pp) | 515 – null | 560 KB | `...sec_19_HUDCO_Offices.pdf` | Extends to document physical end |

### 7.4 Verified Defects in Current PDF Processing

> [!WARNING]
> **Defect 1: Total Omission of Front Matter (Physical Pages 1–19)**  
> The section plan begins at `sec_01` (Physical Page 20 / Printed Page 18). **Physical pages 1 through 19 are completely dropped from the segmentation plan and do not exist in any intermediate PDF.** These omitted pages contain:
> - Front cover and corporate identity declarations
> - Vision, Mission, and Core Objectives
> - Financial and Operational Highlights (5-year comparative charts)
> - Awards, accolades, and key corporate disclosures
> - The printed Table of Contents itself (Page 5)

> [!WARNING]
> **Defect 2: Offset Generalization Causes Boundary Misalignment**  
> `toc_analysis.json` reveals that the heading keyword search found **5 sections with offset 0**, **1 section with offset 1**, and **6 sections with offset 2**.  
> The voting counter (`dominant_offset = 2`) generalized `+2` across the entire document. Consequently, sections where the text actually began at physical page = printed page (such as Chairman's Message, Corporate Governance Report, and BRSR) have their start pages shifted by +2. As a result, the first two pages of these sections contain the ending pages of the previous section, and their own ending pages are truncated!

---

## 8. HTML Extraction and Cleaning

### 8.1 Implementation Analysis: `html_crawler.py`
The HTML crawling subsystem is located at [`pipeline/stage_2_parsing/html_crawler.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/html_crawler.py).

```python
# Core extraction snippet from html_crawler.py
extracted_text = trafilatura.extract(
    html_content,
    include_links=True,
    include_tables=True,
    output_format="txt"
)
```

#### Capabilities and Strengths
- **Trafilatura Integration**: Utilizes Trafilatura's robust text extraction algorithms to bypass sidebars, footers, headers, and navigation menus.
- **Accordion FAQ Parser**: Targets `.accordion-header`, `.faq-question`, and `<dt>` tags to pair questions with sibling answer nodes.

#### Deficiencies and Blockers
1. **Uninstalled Dependencies**: `trafilatura>=1.6.0` and `beautifulsoup4>=4.12.0` are commented out in `requirements.txt`. Importing this module currently raises `ModuleNotFoundError`.
2. **No Rate Limiting or Anti-Scraping Defenses**: Uses a basic `requests.Session` with a static user agent header (`HUDCO-Enterprise-AI-Pipeline/1.0`). Has no exponential backoff, rate limiting, proxy handling, or retry logic.
3. **No Sitemaps or URL Discovery**: Crawls single target URLs provided manually; cannot discover schemes, circulars, or news links dynamically.

---

## 9. Current Data Formats and Schemas

This section documents the actual, verified data contracts currently defined or generated in the workspace.

### 9.1 Local Document Registry Schema (`document_registry.json`)
- **Path**: [`data/document_registry.json`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/document_registry.json)
- **Format**: JSON
- **Role**: Intermediate/Source tracking registry for deduplication.
- **Top-Level Structure**:
  - `documents`: Object mapping received filenames to metadata records.
  - `hashes`: Object mapping SHA-256 strings to identical metadata records.

#### Sanitized Real Example:
```json
{
  "documents": {
    "ar26.pdf": {
      "status": "DOWNLOADED",
      "is_duplicate": false,
      "received_filename": "ar26.pdf",
      "file_path": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\raw\\annual_reports\\ar26.pdf",
      "file_name": "ar26.pdf",
      "sha256": "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41",
      "size_bytes": 12335105,
      "source_url": "https://hudco.org.in/writereaddata/ar26.pdf",
      "elapsed_seconds": 8.41,
      "http_status": 200,
      "content_type": "application/pdf"
    }
  },
  "hashes": {
    "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41": {
      "status": "DOWNLOADED",
      "is_duplicate": false,
      "received_filename": "ar26.pdf",
      "file_path": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\raw\\annual_reports\\ar26.pdf",
      "file_name": "ar26.pdf",
      "sha256": "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41",
      "size_bytes": 12335105,
      "source_url": "https://hudco.org.in/writereaddata/ar26.pdf",
      "elapsed_seconds": 8.41,
      "http_status": 200,
      "content_type": "application/pdf"
    }
  }
}
```

### 9.2 Machine Run Manifest Schema (`stage1_manifest.json`)
- **Path**: [`data/intermediate/ingestion_runs/run_20260923_212152/stage1_manifest.json`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/intermediate/ingestion_runs/run_20260923_212152/stage1_manifest.json)
- **Format**: JSON
- **Role**: Intermediate audit manifest produced at completion of Stage 1.
- **Top-Level Keys**: `run_id`, `status`, `started_at`, `completed_at`, `source`, `document`, `identity`, `pdf_structure`, `sections`, `validation`, `artifacts`, `errors`, `warnings`.

#### Sanitized Real Example:
```json
{
  "run_id": "run_20260923_212152",
  "status": "COMPLETED_SUCCESS",
  "started_at": "2026-09-23T21:21:52.256072Z",
  "completed_at": "2026-09-23T21:22:12.450766Z",
  "source": {
    "url": "https://hudco.org.in/writereaddata/ar26.pdf",
    "received_filename": "ar26.pdf",
    "stored_filename": "ar26.pdf",
    "source_type": "annual_report",
    "is_duplicate": true
  },
  "document": {
    "document_id": "HUDCO_AR_2025_26_c412ce14",
    "document_type": "annual_report",
    "title_hint": "Annual Report 2025-26",
    "fiscal_year_hint": "2025-26",
    "pdf_metadata_title": "",
    "sha256": "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41",
    "size_bytes": 12335105,
    "page_count": 520
  },
  "identity": {
    "filename_hints": {
      "received_filename": "ar26.pdf",
      "url_filename": "ar26.pdf",
      "suggested_type": "annual_report",
      "suggested_year": "26"
    },
    "identity_conflict": false,
    "conflicts": []
  },
  "pdf_structure": {
    "outline_present": true,
    "outline_entry_count": 5,
    "outline_quality": "WEAK",
    "toc_detection_method": "toc_page_discovery",
    "toc_pages": [5],
    "page_mapping_method": "printed_page_offset",
    "page_mapping_confidence": "high"
  },
  "sections": {
    "section_count": 19,
    "output_directory": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\intermediate\\sections",
    "items": [
      {
        "section_id": "sec_01",
        "title": "Reference Information",
        "output_file": "HUDCO_AR_2025_26_c412ce14_sec_01_Reference_Information.pdf",
        "output_path": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\intermediate\\sections\\HUDCO_AR_2025_26_c412ce14_sec_01_Reference_Information.pdf",
        "physical_page_start": 20,
        "physical_page_end": 21,
        "printed_page_start": 18,
        "printed_page_end": 19,
        "pages_count": 2,
        "size_bytes": 291077,
        "segmentation_method": "toc_page_discovery",
        "confidence": "high"
      }
    ]
  },
  "validation": {
    "overlap_check": true,
    "range_check": true,
    "output_file_check": true,
    "page_count_check": true
  },
  "artifacts": {
    "manifest_path": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\intermediate\\ingestion_runs\\run_20260923_212152\\stage1_manifest.json",
    "run_report_path": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\intermediate\\ingestion_runs\\run_20260923_212152\\stage1_run_report.md",
    "toc_analysis_path": "C:\\Users\\Praneya Arora\\Desktop\\Hudco\\data\\intermediate\\ingestion_runs\\run_20260923_212152\\toc_analysis.json"
  },
  "errors": [],
  "warnings": []
}
```

### 9.3 Unified Knowledge Chunk Schema (`schemas.py`)
- **Path**: [`pipeline/stage_3_structuring/schemas.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/schemas.py)
- **Format**: Pydantic v2 Models (`BaseModel`)
- **Role**: Target canonical contract for atomic knowledge chunks.

#### Code Specification & Schema Hierarchy:
```python
class SourceMetadata(BaseModel):
    title: str
    document_type: str                  # annual_report, circular, faq, web_page
    url: Optional[str] = None
    fiscal_year: Optional[str] = None   # e.g. "2025-26"
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    authority_tier: int = Field(default=1, ge=1, le=3)
    is_latest: bool = True

class ClassificationMetadata(BaseModel):
    department: str
    section_title: str
    primary_intent: str                 # 1 of 13 taxonomies
    secondary_intents: List[str] = []
    entities_covered: List[str] = []

class TableItem(BaseModel):
    table_id: str
    title: Optional[str] = None
    markdown: str

class ContentPayload(BaseModel):
    summary: str
    text_content: str
    tables: List[TableItem] = []

class ChunkMetadata(BaseModel):
    char_count: int
    token_estimate: int
    sha256: str
    created_at: datetime
    version: int = 1

class UnifiedChunk(BaseModel):
    chunk_id: str
    document_id: str
    source: SourceMetadata
    classification: ClassificationMetadata
    content: ContentPayload
    metadata: ChunkMetadata
```

#### Sanitized Realistic Chunk JSON Instance (Contract Conforming):
```json
{
  "chunk_id": "HUDCO_AR_2025_26_c412ce14_SEC15_P208_C01",
  "document_id": "HUDCO_AR_2025_26_c412ce14",
  "source": {
    "title": "56th Annual Report 2025-26",
    "document_type": "annual_report",
    "url": "https://hudco.org.in/writereaddata/ar26.pdf",
    "fiscal_year": "2025-26",
    "page_start": 208,
    "page_end": 209,
    "authority_tier": 1,
    "is_latest": true
  },
  "classification": {
    "department": "Finance & Accounts",
    "section_title": "Standalone Financial Statements",
    "primary_intent": "FINANCIAL_RESULTS",
    "secondary_intents": ["LOAN_DISBURSEMENTS"],
    "entities_covered": ["Profit After Tax", "NPA", "Net Worth"]
  },
  "content": {
    "summary": "Standalone balance sheet highlights and profit summary for FY 2025-26.",
    "text_content": "During the fiscal year 2025-26, the company posted record operational achievements across housing finance and social infrastructure loan sanctions.",
    "tables": [
      {
        "table_id": "P208_T01",
        "title": "Summary of Financial Performance",
        "markdown": "| Particulars | FY 2025-26 (Rs. Cr) | FY 2024-25 (Rs. Cr) |\n|---|---|---|\n| Total Revenue | 10,420 | 8,950 |\n| Profit After Tax | 2,810 | 2,450 |"
      }
    ]
  },
  "metadata": {
    "char_count": 310,
    "token_estimate": 77,
    "sha256": "4a7d1ed8a25d2c88276f7cbe32a4e4776104f7b2c0d8926065538e4a9e52c803",
    "created_at": "2026-09-24T00:00:00Z",
    "version": 1
  }
}
```

---

## 10. Classification and Intent Architecture

### 10.1 Document-Level vs Chunk-Level Classification
The repository currently implements two completely separate classification concepts:

1. **Document-Level Identity & Type Classification**:
   - Implemented in [`pipeline/stage_1_ingestion/fingerprint.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/fingerprint.py).
   - Scans the first 5 pages and metadata to extract `document_type` (`annual_report`, `circular`, `unknown`), `content_title_hint`, and `fiscal_year_hint`.
   - Runs deterministically with regular expressions (`FY_REGEX`, `EDITION_REGEX`, `AR_TITLE_REGEX`).

2. **Chunk-Level Intent Labeling**:
   - Implemented in [`pipeline/stage_3_structuring/intent_classifier.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py).
   - Evaluates chunk text against 13 static intent taxonomies.

### 10.2 Domain Taxonomy Audit

| Intent Tag | Domain Category | Rule Keywords Detected | Downstream RAG Purpose |
|---|---|---|---|
| `RETAIL_HOUSING_LOAN` | Housing Finance | `home loan`, `housing loan`, `individual borrower`, `margin money` | Directs borrower eligibility queries. |
| `PMAY_SCHEMES` | Housing Finance | `pmay`, `pradhan mantri awas`, `clss`, `interest subsidy` | Government subsidized housing inquiries. |
| `STAFF_HOUSING` | Housing Finance | Keyword rule missing from classifier | Institutional and employee loan schemes. |
| `INFRA_PROJECT_FINANCING` | Urban Infrastructure | `water supply`, `sewerage`, `smart city`, `infrastructure financing`, `urban transport`| Large public works / municipal finance. |
| `CONSULTANCY_SERVICES` | Urban Infrastructure | Keyword rule missing from classifier | Technical advisory and disaster planning. |
| `FINANCIAL_RESULTS` | Financial Disclosures | `profit after tax`, `pat`, `npa`, `balance sheet`, `net worth`, `disbursement` | Audited financial metrics and balance sheets. |
| `BONDS_AND_BORROWINGS` | Financial Disclosures | `tax-free bond`, `54ec`, `capital gains bond`, `borrowings`, `debenture` | Retail and institutional bond investors. |
| `ANNUAL_REPORTS` | Financial Disclosures | Default catch-all fallback | Narrative reports, MD&A, Director speeches. |
| `LOCATE_OFFICE` | Direct Utilities | `regional office`, `branch office`, `head office`, `telephone`, `email`, `address`| Physical addresses and contact directories. |
| `DOWNLOAD_FORMS` | Direct Utilities | `form`, `download`, `kyc format`, `application format` | KYC, application checklists, circular downloads. |
| `FAQ_LOOKUP` | Direct Utilities | Keyword rule missing from classifier | Official website Q&A items. |
| `VIGILANCE_POLICY` | Governance | `vigilance`, `whistle blower`, `complaint portal` | Anti-corruption, whistleblower guidelines. |
| `BOARD_MEMBERS` | Governance | `board of directors`, `director`, `kmp`, `management team` | Key management profiles and committees. |

### 10.3 Identified Gaps in Intent Architecture
- **Missing Keyword Rules**: Although 13 intents are defined in `TAXONOMY_INTENTS`, the rule-based logic in `classify_rule_based()` only checks for 9 of them. `STAFF_HOUSING`, `CONSULTANCY_SERVICES`, and `FAQ_LOOKUP` have no keyword rules and inevitably fall back to `ANNUAL_REPORTS`.
- **Absence of Confidence Scoring**: The classifier returns a bare string. No numerical probability, confidence margin, or distance metric is computed.
- **Single-Label Restriction**: Only a single `primary_intent` is assigned. `secondary_intents` is hardcoded to an empty list (`[]`) in `create_unified_chunk()`.
- **No Ambiguity Handling**: If multiple contradictory topics appear on a single page (e.g. CSR Activities mentioning Water Supply and Balance Sheet numbers), only the first matched `if/elif` branch wins.
- **No Query-Time Intent Classification**: The classification code is written exclusively for chunk creation. There is no runtime query-intent classifier to route user prompts.

---

## 11. Chunking and RAG Readiness

### 11.1 Chunk Existence and Storage State
- **Actual Chunk Count on Disk**: **0 chunks**.
- **Inspection Finding**: `data/output_chunks/` contains only `.gitkeep`.
- **Last Completed Stage**: Stage 1 Section Splitting (19 PDFs in `data/intermediate/sections/`).

### 11.2 Chunking Implementation State
The repository **does not possess an active chunking engine**:
- In [`config/settings.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/config/settings.py), chunk limits are declared (`MIN_CHUNK_CHAR_LEN = 150`, `MAX_CHUNK_CHAR_LEN = 2500`).
- However, no text-chunking algorithm (e.g. recursive character splitting, sentence tokenizer, markdown header hierarchy parser) is implemented in `pipeline/stage_3_structuring/` or elsewhere.
- [`intent_classifier.py:create_unified_chunk()`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py#L71) accepts already-segmented text and produces a single `UnifiedChunk`. If fed a 150-page section PDF directly, it would attempt to create an un-embeddable 300,000-character chunk.

### 11.3 RAG Readiness Assessment
The repository is **not currently RAG-ready**:
1. Sections must be extracted to plain text and clean markdown tables first (Stage 2).
2. A section-aware chunker must be implemented to segment large sections into 500–1,500 token windows while keeping Markdown tables intact.
3. Chunks must be validated against `UnifiedChunk` and serialized to JSONL.

---

## 12. Storage, Retrieval, and Chatbot Integration

### 12.1 ChromaDB Vector Store (`chroma_loader.py`)
- **Status**: Implemented in code, but unverified and empty.
- **Storage Location**: `data/chroma_db/` (Directory exists, 0 bytes).
- **Target Collection**: `hudco_knowledge_chunks`.
- **Target Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional dense vectors).
- **Embedded Document Composition**:
  ```python
  combined_doc = (
      f"Document: {chunk.source.title} (FY {chunk.source.fiscal_year or 'N/A'})\n"
      f"Section: {chunk.classification.section_title}\n"
      f"Intent: {chunk.classification.primary_intent}\n"
      f"Summary: {chunk.content.summary}\n"
      f"Content: {chunk.content.text_content}\n"
      f"{tbl_text}"
  )
  ```
- **Filter Capabilities**: Supports exact dictionary metadata filtering on `primary_intent`.

### 12.2 Relational Store (`db_registry.py`)
- **Status**: Declarative SQLAlchemy models defined; no active database connection.
- **Connection String in Settings**: `postgresql+asyncpg://hudco_admin:hudco_pass@localhost:5432/hudco_db`
- **Models Defined**:
  1. `DocumentRegistry`: Tracks parent documents, SHA-256 hashes, total pages, and status (`PENDING`, `INGESTED`, `INDEXED`, `ERROR`).
  2. `ChunkRegistry`: Maps chunk IDs to parent document IDs, intent tags, page ranges, and full JSON content payload.
  3. `OfficeDirectory`: Relational schema for HUDCO regional/head offices, addresses, cities, emails, and phones.

### 12.3 Chatbot Runtime & Orchestration Layer (Stage 5)
- **Status**: Completely unwritten.
- The `pipeline/stage_5_api/` directory does not exist.
- No FastAPI app, Redis session TTL cache, BM25 ranker, or Gemini ground-generation prompt exists on disk.

---

## 13. Tests, Quality Controls, and Known Issues

### 13.1 Unit Test Suite Analysis (`tests/test_stage1.py`)
Stage 1 is equipped with a comprehensive, well-structured unit test suite consisting of 12 tests:

```
Test A: test_a_streaming_download_success         ──► Verifies streaming download and file creation
Test B: test_b_sha256_matches_content             ──► Verifies SHA-256 accuracy on synthetic PDF
Test C: test_c_duplicate_detection                ──► Verifies duplicate flag on identical content
Test D: test_d_collision_protection_different_con  ──► Verifies _{sha8} disambiguation on collision
Test E: test_e_invalid_magic_bytes_rejected       ──► Verifies rejection of non-%PDF- streams
Test F: test_f_incomplete_download_cleanup        ──► Verifies .part file deletion on socket abort
Test G: test_g_outline_extraction_normalized      ──► Verifies PDF bookmark structural inspection
Test H: test_h_invalid_outline_quality_gate       ──► Verifies rejection of single-digit/junk outlines
Test I: test_i_printed_physical_page_mapping_sepa  ──► Verifies printed vs physical page separation
Test J: test_j_section_ranges_non_overlapping     ──► Verifies strict boundary monotonicity
Test K: test_k_fixed_window_fallback_labeling     ──► Verifies fallback labeling and low confidence
Test L: test_l_pdf_splitting_creates_files        ──► Verifies physical section PDF file creation
```

### 13.2 Quality Control Auditing in Historical Run Reports
Inspection of `data/intermediate/ingestion_runs/run_20260923_212152/stage1_run_report.md` shows that Stage 1 ran automated programmatic validations:
- **Non-Overlapping Ranges**: PASSED (`overlap_check: true`)
- **Page Bounds Check**: PASSED (`range_check: true`, all sections within [1, 520])
- **Artifact Output Verification**: PASSED (`output_file_check: true`, all 19 files created on disk)
- **Total Page Accounting**: PASSED (`page_count_check: true`)

### 13.3 Matrix of Confirmed Defects vs Potential Risks

| Issue Identifier | Classification | Description & Root Cause | Affected Files | Severity |
|---|---|---|---|---|
| **ISSUE-01** | **Confirmed Defect** | **Omission of Front Matter (Pages 1–19)**. The section planner begins at section 1 (page 20), dropping corporate governance overviews, 5-year financials, vision/mission, and cover pages. | [`pipeline/stage_1_ingestion/segmenter.py:320-390`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L320-L390) | **P0 (Data Loss)** |
| **ISSUE-02** | **Confirmed Defect** | **Document-Wide Page Offset Generalization**. Choosing a single dominant offset (+2) shifts boundaries by 2 pages for sections where offset was 0 (e.g. Chairman's Message, BRSR, Consolidated Financials). | [`pipeline/stage_1_ingestion/segmenter.py:288-317`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L288-L317) | **P0 (Content Skew)**|
| **ISSUE-03** | **Confirmed Defect** | **Commented Out Dependencies**. 9 required packages are commented out in `requirements.txt`. Stages 2–4 fail on import. | [`requirements.txt:9-18`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/requirements.txt#L9-L18) | **P1 (Runtime Blocker)**|
| **ISSUE-04** | **Confirmed Defect** | **Missing Section Chunker**. No logic divides sections into 150–2,500 char chunks. `data/output_chunks/` is empty. | `pipeline/stage_3_structuring/` | **P1 (Pipeline Blocker)**|
| **ISSUE-05** | **Historical Inconsistency** | **PostgreSQL Deduplication Claim**. README states deduplication runs in PostgreSQL; actual implementation uses `data/document_registry.json`. | [`README_ARCHITECTURE_AND_PLANNING.md:37`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/README_ARCHITECTURE_AND_PLANNING.md#L37) vs [`downloader.py:42`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py#L42) | **P2 (Doc Drift)** |
| **ISSUE-06** | **Potential Risk** | **Missing Scanned PDF / OCR Support**. Text extraction relies strictly on embedded fonts. Scanned circulars will extract as blank strings without error. | [`pipeline/stage_1_ingestion/segmenter.py:46`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L46) | **P2 (Robustness Risk)**|
| **ISSUE-07** | **Potential Risk** | **Zero Automated Tests for Stages 2–4**. Only Stage 1 has unit test coverage (`test_stage1.py`). | `tests/` | **P2 (Quality Risk)** |

---

## 14. Existing Decisions and Documented Future Plans

The project's architectural decisions and documented plans—extracted from [`README_ARCHITECTURE_AND_PLANNING.md`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/README_ARCHITECTURE_AND_PLANNING.md)—are catalogued below to ensure technical continuity:

### 14.1 Key Architecture Decisions (ADRs) Preserved
1. **Streaming PDF Slicing Prior to Parsing (ADR-01)**:
   - *Rationale*: HUDCO annual reports range from 150MB to 300MB+ (400–600+ pages). Loading full binary PDF trees into memory causes Out-Of-Memory (OOM) failures in containerized runtimes. Slicing into standalone section PDFs keeps memory usage flat.
   - *Status*: **Implemented and Verified in Stage 1**.
2. **Deterministic Cryptographic Identity over Filenames (ADR-02)**:
   - *Rationale*: Filenames on government portals are frequently generic (e.g. `ar26.pdf`, `report.pdf`, `final.pdf`). Cryptographic SHA-256 hashes combined with content-derived fiscal year regexes form immutable IDs (e.g. `HUDCO_AR_2025_26_c412ce14`).
   - *Status*: **Implemented and Verified in Stage 1**.
3. **Structured Tabular Markdown Preservation (ADR-03)**:
   - *Rationale*: Flattening financial tables (balance sheets, NPA ratios, state-wise disbursements) into raw text destroys column-row alignments, leading to severe LLM hallucinations. Tables must be extracted as GitHub-flavored Markdown matrices.
   - *Status*: **Implemented in `TableExtractor`, but unverified**.
4. **Dual Storage Architecture (ADR-04)**:
   - *Rationale*: Dense vector similarity search alone is inadequate for public-sector finance queries requiring exact numerical figures or office contacts. The system pairs ChromaDB (semantic vectors) with PostgreSQL (exact facts, office directories, document lifecycle).
   - *Status*: **Models defined, unindexed**.
5. **Hierarchical Intent Routing & Hybrid Search (ADR-05)**:
   - *Rationale*: General queries like *"Tell me about loans"* confuse generic vector retrieval. Queries must be routed into 5 domain categories (Housing, Infrastructure, Investors, Utilities, Governance) using hybrid dense + BM25 search.
   - *Status*: **Taxonomy defined, runtime unwritten**.

---

## 15. Current-State Architecture Diagrams

### Diagram 1: Actual Implemented vs Documented System Architecture
Solid lines indicate verified, implemented components; dashed lines indicate unverified, partially implemented, or missing components.

```mermaid
graph TD
    classDef verified fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef partial fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    classDef missing fill:#f8d7da,stroke:#dc3545,stroke-width:2px,stroke-dasharray: 5 5;

    subgraph INGRESS["Document Ingress & Triage"]
        URL["Remote URL CLI"]:::verified
        LOCAL["Local PDF File"]:::verified
        WEB_DISC["Automated URL Discovery"]:::missing
        DL["DocumentDownloader<br/>(64KB Stream, .part, SHA-256)"]:::verified
        DEDUP["Registry Deduplication<br/>(document_registry.json)"]:::verified
        FP["DocumentFingerprinter<br/>(Identity hints & conflicts)"]:::verified
    end

    subgraph SEGMENTATION["Stage 1: PDF Segmentation"]
        QUAL["Outline Quality Gate<br/>(Monotonicity & substance)"]:::verified
        TOC["TOC Page Discovery<br/>(Physical Page 5 scan)"]:::verified
        OFFSET["Printed-to-Physical Offset<br/>(+2 offset voting)"]:::verified
        SPLIT["PDFSegmenter.split_pdf<br/>(Writes 19 Section PDFs)"]:::verified
        REPORTS["Audit Manifest & Report<br/>(stage1_manifest.json)"]:::verified
    end

    subgraph EXTRACTION["Stage 2: Parsing & Cleaning"]
        CLEAN["TextCleaner<br/>(Regex headers/footers)"]:::partial
        TBL["TableExtractor<br/>(pdfplumber to Markdown)"]:::partial
        HTML_C["HTMLCrawler<br/>(Trafilatura & BS4)"]:::partial
        S2_RUN["Stage 2 Runner"]:::missing
    end

    subgraph STRUCTURING["Stage 3: Structuring & Chunks"]
        SCHEMAS["UnifiedChunk Schema<br/>(Pydantic Models)"]:::verified
        TAX["Intent Taxonomy<br/>(13 Categories)"]:::partial
        CHUNKER["Section-Aware Chunker"]:::missing
        OUT_JSON["Output Chunk JSONL Store"]:::missing
    end

    subgraph STORAGE["Stage 4 & 5: Storage & RAG"]
        CHROMA["ChromaDB Loader<br/>(all-MiniLM-L6-v2)"]:::partial
        POSTGRES["PostgreSQL Registry<br/>(SQLAlchemy Models)"]:::partial
        API["FastAPI Chat Runtime<br/>(Redis, Hybrid BM25, Gemini)"]:::missing
    end

    URL --> DL
    LOCAL --> DL
    WEB_DISC -.-> DL
    DL --> DEDUP
    DEDUP --> FP
    FP --> QUAL
    QUAL -->|Weak / Invalid| TOC
    TOC --> OFFSET
    OFFSET --> SPLIT
    SPLIT --> REPORTS
    SPLIT --> CLEAN
    SPLIT --> TBL
    HTML_C -.-> S2_RUN
    CLEAN -.-> S2_RUN
    TBL -.-> S2_RUN
    S2_RUN -.-> CHUNKER
    CHUNKER -.-> SCHEMAS
    CHUNKER -.-> TAX
    TAX -.-> OUT_JSON
    OUT_JSON -.-> CHROMA
    OUT_JSON -.-> POSTGRES
    CHROMA -.-> API
    POSTGRES -.-> API
```

### Diagram 2: Actual Document & Data Flow to Latest Implemented Output
Shows the exact path traversed by `ar26.pdf` to produce the 19 section PDFs.

```mermaid
sequenceDiagram
    autonumber
    actor CLI as Operator / CLI
    participant DL as DocumentDownloader
    participant REG as document_registry.json
    participant FP as DocumentFingerprinter
    participant SEG as PDFSegmenter
    participant DISK as data/intermediate/sections/

    CLI->>DL: run_stage1.py --file ar26.pdf
    DL->>DL: Check %PDF- magic bytes & stream compute SHA-256
    DL->>REG: Lookup SHA-256 (c412ce14...)
    REG-->>DL: Found / Not Found
    DL->>REG: Register document metadata
    DL->>FP: fingerprint(pdf_path, received_filename, sha256)
    FP-->>DL: Canonical ID: HUDCO_AR_2025_26_c412ce14
    DL->>SEG: inspect_structure(ar26.pdf)
    SEG-->>SEG: Extract 5 outline entries -> Evaluated as WEAK
    SEG->>SEG: discover_and_parse_toc() -> Discovered on Page 5 (19 entries)
    SEG->>SEG: map_printed_to_physical_pages() -> Offset = +2
    SEG->>SEG: build_section_plan() -> 19 non-overlapping ranges (p20-p520)
    SEG->>DISK: split_pdf() -> Write 19 Sub-Document PDFs
    SEG-->>CLI: Write stage1_manifest.json & stage1_run_report.md
```

### Diagram 3: Classification and Intent Decision Flow

```mermaid
flowchart TD
    classDef rule fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef missing fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray: 5 5;

    INPUT["Section Title + Text Content"] --> CLASSIFY{"Keyword Heuristic Match"}:::rule

    CLASSIFY -->|"pmay / interest subsidy"| PMAY["PMAY_SCHEMES"]
    CLASSIFY -->|"home loan / margin money"| HOUSING["RETAIL_HOUSING_LOAN"]
    CLASSIFY -->|"pat / npa / balance sheet"| FIN["FINANCIAL_RESULTS"]
    CLASSIFY -->|"bond / 54ec / debenture"| BOND["BONDS_AND_BORROWINGS"]
    CLASSIFY -->|"regional office / telephone"| OFFICE["LOCATE_OFFICE"]
    CLASSIFY -->|"water supply / smart city"| INFRA["INFRA_PROJECT_FINANCING"]
    CLASSIFY -->|"board of directors / kmp"| BOARD["BOARD_MEMBERS"]
    CLASSIFY -->|"vigilance / whistle blower"| VIGILANCE["VIGILANCE_POLICY"]
    CLASSIFY -->|"kyc format / form"| FORM["DOWNLOAD_FORMS"]
    CLASSIFY -->|No Keyword Hit| DEFAULT["ANNUAL_REPORTS (Default Fallback)"]

    PMAY --> CHUNK["create_unified_chunk()"]
    HOUSING --> CHUNK
    FIN --> CHUNK
    BOND --> CHUNK
    OFFICE --> CHUNK
    INFRA --> CHUNK
    BOARD --> CHUNK
    VIGILANCE --> CHUNK
    FORM --> CHUNK
    DEFAULT --> CHUNK

    CONF["Confidence Scoring"]:::missing -.-> CHUNK
    MULTI["Secondary Intent Extraction"]:::missing -.-> CHUNK
    LLM_TAG["LLM Zero-Shot Disambiguation"]:::missing -.-> CHUNK
```

---

## 16. Gaps, Risks, and Inconsistencies

### 16.1 Critical Data Integrity Gaps
1. **Dropped Pages (Front Matter)**: The current pipeline discards physical pages 1–19. These pages contain vital corporate identity information, five-year financial charts, mission statements, and awards that will be completely invisible to the RAG chatbot unless recovered.
2. **Boundary Drift in Section Slicing**: Applying a single static offset (+2) across all 520 pages shifts the physical start and end pages for sections where offset is 0. Downstream chunking will inherit these shifted boundaries, contaminating section-level context windows.
3. **Missing Trailing Printed Page**: `sec_19` (HUDCO Offices) terminates with `printed_page_end: null` because the printed report omits a page number for the final directory page. Downstream schema validation requiring integer page ranges will fail.

### 16.2 Codebase & Architectural Inconsistencies
1. **PostgreSQL vs JSON Registry**: Architecture documentation asserts that deduplication and master cataloguing are handled by PostgreSQL. In reality, the entire system relies on `data/document_registry.json`. No PostgreSQL database has been initialized.
2. **Missing Stage 2 Runner**: `pipeline/stage_2_parsing/` contains three standalone classes (`TextCleaner`, `TableExtractor`, `HTMLCrawler`), but no script coordinates their execution or processes the 19 section PDFs.
3. **Empty Output Stores**: Although documentation implies that chunks and vector indices exist, `data/output_chunks/` and `data/chroma_db/` are empty.
4. **Duplicate Documentation**: `README_ARCHITECTURE_AND_PLANNING.md` exists identically in the project root and `docs/`, creating documentation maintenance overhead.

---

## 17. Prioritized Implementation Roadmap

Based on the verified current state and documented architecture plans, the following staged roadmap outlines the path to a production-quality HUDCO RAG knowledge pipeline:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       STAGED IMPLEMENTATION ROADMAP                         │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────────────────┤
│   PHASE A   │   PHASE B   │   PHASE C   │   PHASE D   │       PHASE E       │
│  Stabilize  │  Canonical  │  RAG-Ready  │  Retrieval  │     Production      │
│  Ingestion  │  Contracts  │   Chunks    │  & Grounding│      Hardening      │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────────────────┘
```

### Phase A — Stabilize Existing Ingestion & Data Integrity (P0)

> **Objective**: Eliminate verified data-loss and boundary-misalignment defects in Stage 1 before building downstream components.

#### Task A.1: Front Matter Section Recovery
- **Priority**: **P0 (Urgent)**
- **Why Needed**: Recover physical pages 1–19 (covers, vision/mission, 5-year financial highlights, awards, and TOC).
- **Files Affected**: [`pipeline/stage_1_ingestion/segmenter.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py), [`run_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/run_stage1.py)
- **Implementation**: In `build_section_plan()`, if `mapped_entries[0]["physical_page_start"] > 1`, prepend a synthesized `sec_00_Front_Matter` covering `[1, mapped_entries[0]["physical_page_start"] - 1]`.
- **Acceptance Criteria**: 20 section PDFs produced; 100% of physical pages (1–520) accounted for without gaps.

#### Task A.2: Per-Section Heading Verification (Fix Offset Generalization)
- **Priority**: **P0 (Urgent)**
- **Why Needed**: Fix the 2-page boundary shift affecting Chairman's Message, Governance Report, and BRSR.
- **Files Affected**: [`pipeline/stage_1_ingestion/segmenter.py:234-317`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L234-L317)
- **Implementation**: Instead of taking a single `dominant_offset` across the entire document, perform localized physical page searches `[pr_page - 2 .. pr_page + 10]` for each section title. Use the verified physical page where the title heading actually appears.
- **Acceptance Criteria**: Section boundaries match exact heading locations; `sec_03` starts at physical page 22 (where Chairman's Message actually begins).

#### Task A.3: Trailing Printed Page Null Handling
- **Priority**: **P1**
- **Why Needed**: Ensure `sec_19` produces a valid integer `printed_page_end`.
- **Files Affected**: [`pipeline/stage_1_ingestion/segmenter.py:371-374`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py#L371-L374)
- **Implementation**: Calculate `printed_page_end = printed_page_start + (physical_page_end - physical_page_start)` when missing.
- **Acceptance Criteria**: All section records contain non-null integer printed and physical page ranges.

---

### Phase B — Establish Canonical Dependencies & Extraction Pipeline (P1)

> **Objective**: Uncomment and pin dependencies, and build the missing Stage 2 orchestration engine.

#### Task B.1: Dependency Pinning & Environment Normalization
- **Priority**: **P0**
- **Why Needed**: Enable execution of `pdfplumber`, `trafilatura`, `bs4`, `chromadb`, and `sqlalchemy`.
- **Files Affected**: [`requirements.txt`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/requirements.txt)
- **Acceptance Criteria**: Clean `pip install -r requirements.txt` succeeds without conflicts.

#### Task B.2: Implement Stage 2 Orchestrator (`run_stage2.py`)
- **Priority**: **P1**
- **Why Needed**: Connect Stage 1 output sections to text cleaning, table extraction, and intermediate Markdown persistence.
- **Files Affected**: Create `pipeline/stage_2_parsing/run_stage2.py`
- **Implementation**: Read `stage1_manifest.json`, iterate through the 20 section PDFs, execute `TextCleaner.clean_text()`, extract Markdown tables via `TableExtractor`, and persist clean Markdown files in `data/intermediate/sections/`.
- **Acceptance Criteria**: 20 corresponding `.md` section files generated with preserved tables.

---

### Phase C — Section-Aware Chunking & Intent Enrichment (P1)

> **Objective**: Implement text chunking, attach metadata citations, and generate validated JSONL chunks.

#### Task C.1: Implement Section-Aware & Table-Preserving Text Chunker
- **Priority**: **P1**
- **Why Needed**: Large sections (up to 150 pages) cannot be ingested into vector embeddings without chunking.
- **Files Affected**: `pipeline/stage_3_structuring/chunker.py` (New), [`schemas.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/schemas.py)
- **Implementation**: Recursive character splitting (1,000–1,500 chars, 200 char overlap) that treats Markdown tables as indivisible atomic units.
- **Acceptance Criteria**: Chunks conform strictly to `MIN_CHUNK_CHAR_LEN` (150) and `MAX_CHUNK_CHAR_LEN` (2500).

#### Task C.2: Multi-Label Intent Tagging & Confidence Scoring
- **Priority**: **P2**
- **Why Needed**: Provide confidence thresholds and multi-intent support for ambiguous chunks.
- **Files Affected**: [`pipeline/stage_3_structuring/intent_classifier.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py)
- **Acceptance Criteria**: Chunks output `primary_intent`, `secondary_intents`, and a `confidence_score` (0.0 to 1.0).

#### Task C.3: Deterministic JSONL Chunk Serializer (`run_stage3.py`)
- **Priority**: **P1**
- **Why Needed**: Serialize validated `UnifiedChunk` instances to disk for downstream storage.
- **Files Affected**: Create `pipeline/stage_3_structuring/run_stage3.py`
- **Acceptance Criteria**: Generates `data/output_chunks/HUDCO_AR_2025_26_c412ce14_chunks.jsonl`. 100% pass Pydantic validation.

---

### Phase D — Dual Storage Loading & Vector Indexing (P2)

> **Objective**: Load validated chunks into ChromaDB and populate the relational registry.

#### Task D.1: ChromaDB Vector Upsert & Indexing Runner (`run_stage4.py`)
- **Priority**: **P1**
- **Why Needed**: Create queryable semantic embeddings.
- **Files Affected**: Create `pipeline/stage_4_storage/run_stage4.py`, [`chroma_loader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/chroma_loader.py)
- **Acceptance Criteria**: Chroma collection `hudco_knowledge_chunks` populated; `query_semantic()` returns relevant results with metadata.

#### Task D.2: PostgreSQL Master Cataloguing & Office Directory
- **Priority**: **P2**
- **Why Needed**: Fulfill architectural dual-storage mandate for structured SQL queries.
- **Files Affected**: [`pipeline/stage_4_storage/db_registry.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/db_registry.py)
- **Acceptance Criteria**: Database initialization script creates tables and registers chunks.

---

### Phase E — RAG Serving, Grounded Answers & Hardening (P3)

> **Objective**: Build the user-facing retrieval and grounded generation layer.

#### Task E.1: Hybrid Retrieval Orchestrator (BM25 + Dense Vectors)
- **Priority**: **P2**
- **Why Needed**: Ensure exact numerical facts and circular numbers are retrieved accurately alongside semantic queries.
- **Files Affected**: Create `pipeline/stage_5_api/retriever.py`

#### Task E.2: Grounded Citations & Anti-Hallucination Guardrails
- **Priority**: **P2**
- **Why Needed**: Enforce strict public-sector compliance. Every answer must cite `document_id`, `page_start`, and `url`. Fall back gracefully if confidence < 0.65.
- **Files Affected**: Create `pipeline/stage_5_api/generator.py`

#### Task E.3: FastAPI Chat Service & Redis Session Cache
- **Priority**: **P3**
- **Why Needed**: Expose asynchronous REST endpoints for chat interfaces.
- **Files Affected**: Create `pipeline/stage_5_api/main.py`

---

## 18. Recommended Next Step

The single most impactful immediate action is:

> **Execute Phase A (Stabilize Stage 1 Ingestion Integrity)** before implementing any Stage 2 extraction or Stage 3 chunking.
>
> 1. Modify [`pipeline/stage_1_ingestion/segmenter.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py) to automatically capture front matter (pages 1–19) as `sec_00_Front_Matter.pdf`.
> 2. Replace document-wide offset generalization with per-section physical heading verification to fix the 2-page boundary shift.
> 3. Re-run `pipeline/stage_1_ingestion/run_stage1.py` on `ar26.pdf` to produce a 100% complete, properly aligned set of 20 section PDFs.

Addressing these data integrity flaws now ensures that all subsequent parsing, table extraction, chunking, and embeddings are built upon an accurate, gapless foundation.

---

## 19. Glossary and Important File References

### Technical Glossary
- **Authority Tier**: Priority ranking for source documents: Tier 1 (Official Annual Reports, Gazette Notifications), Tier 2 (Official Website Pages), Tier 3 (FAQs and Public Summaries).
- **Canonical Document ID**: Deterministic identifier format `{ORGANIZATION}_{TYPE}_{FISCAL_YEAR}_{SHA256[:8]}` (e.g. `HUDCO_AR_2025_26_c412ce14`).
- **Dominant Offset**: The most frequent difference between a physical PDF page index and its printed report page label.
- **Front Matter**: Preliminary document pages preceding chapter 1 (covers, highlights, vision statements, awards, Table of Contents).
- **Magic Bytes**: The initial 4–8 bytes of a file used to identify format (`%PDF-` for PDFs).
- **Single-Pass Hashing**: Computing cryptographic hashes incrementally within the streaming network read loop, avoiding a second disk I/O pass.
- **Unified Knowledge Schema**: Master Pydantic model (`UnifiedChunk`) specifying source provenance, taxonomy classification, markdown tables, clean text, and technical metadata.

### Essential File References
- Global Settings: [`config/settings.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/config/settings.py)
- Dependency Manifest: [`requirements.txt`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/requirements.txt)
- Architecture Blueprint: [`README_ARCHITECTURE_AND_PLANNING.md`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/README_ARCHITECTURE_AND_PLANNING.md)
- Ingestion Downloader: [`pipeline/stage_1_ingestion/downloader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/downloader.py)
- Document Fingerprinter: [`pipeline/stage_1_ingestion/fingerprint.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/fingerprint.py)
- PDF Segmenter: [`pipeline/stage_1_ingestion/segmenter.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/segmenter.py)
- Stage 1 Orchestrator: [`pipeline/stage_1_ingestion/run_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_1_ingestion/run_stage1.py)
- Text Cleaner: [`pipeline/stage_2_parsing/text_cleaner.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/text_cleaner.py)
- Table Extractor: [`pipeline/stage_2_parsing/table_extractor.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/table_extractor.py)
- HTML Crawler: [`pipeline/stage_2_parsing/html_crawler.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_2_parsing/html_crawler.py)
- Unified Chunk Schema: [`pipeline/stage_3_structuring/schemas.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/schemas.py)
- Intent Classifier: [`pipeline/stage_3_structuring/intent_classifier.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_3_structuring/intent_classifier.py)
- ChromaDB Vector Loader: [`pipeline/stage_4_storage/chroma_loader.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/chroma_loader.py)
- Database Registry Models: [`pipeline/stage_4_storage/db_registry.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/pipeline/stage_4_storage/db_registry.py)
- Stage 1 Test Suite: [`tests/test_stage1.py`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/tests/test_stage1.py)
- Local Document Registry: [`data/document_registry.json`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/document_registry.json)
- Verified Production Run Manifest: [`data/intermediate/ingestion_runs/run_20260923_212152/stage1_manifest.json`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/data/intermediate/ingestion_runs/run_20260923_212152/stage1_manifest.json)
