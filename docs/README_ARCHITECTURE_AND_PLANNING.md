# HUDCO Enterprise Conversational AI: Architecture & Data Pipeline Blueprint

## 1. Executive Summary & Problem Formulation
The **Housing and Urban Development Corporation Limited (HUDCO)** is a premier public sector financial institution (under the Ministry of Housing and Urban Affairs, Government of India) dedicated to housing finance, social housing implementation (such as PMAY-U 2.0), and comprehensive urban infrastructure financing across India.

This project delivers an enterprise-grade, grounded conversational knowledge layer over:
1. **Official HUDCO Annual Reports** (FY 2021-22 to FY 2025-26+).
2. **Scheme Guidelines, Forms, Circulars, and Notifications**.
3. **Official Website Content, Directory Information, and FAQs**.

```
   ┌───────────────────────────────────────────────────────────────────────────┐
   │             HUDCO CONVERSATIONAL KNOWLEDGE INFRASTRUCTURE                 │
   │   High Accuracy • Exact Tabular Preservation • Multi-Intent Grounding    │
   └───────────────────────────────────────────────────────────────────────────┘
```

### The Core Challenges & Architectural Solutions

| Challenge | Impact on Generic RAG | HUDCO Enterprise AI Solution |
|---|---|---|
| **Document Scale & Bloat** | Annual reports are 150MB–300MB+ (400–600+ pages), causing OOM errors and chunk pollution with proxy forms, notices, and repetitive boilerplate. | **TOC-Guided Streaming Ingestion & Segmentation** (`stage_1_ingestion`): Splits giant PDFs into isolated, domain-tagged logical sub-documents with SHA-256 deduplication before parsing. |
| **Numerical & Tabular Integrity** | Financial tables (NPA ratios, balance sheets, disbursement breakdowns) get mangled when flattened into raw text, leading to hallucinated or misattributed metrics. | **Structured Table Preservation** (`stage_2_parsing`): Markdown table extraction maintaining row-column matrix coherence, headers, unit declarations (Rs. in Crore), and fiscal year alignments. |
| **Strict Anti-Hallucination Mandate** | Public sector lending guidelines, eligibility rules, and rates cannot tolerate speculative or hallucinated LLM responses. | **Unified Knowledge Chunk Schema & Dual Storage** (`stage_3_structuring` + `stage_4_storage`): Enforces Pydantic chunk metadata, pre-assigned intents, provenance citations (page numbers, URLs, authority tiers), and hybrid vector + SQL verification. |
| **Broad & Ambiguous Queries** | General user prompts like *"Tell me about loans"* or *"What are the rates?"* confuse standard vector search across disparate annual report and retail scheme contexts. | **Hierarchical Intent Routing & Hybrid Search** (`stage_5_api`): Maps user intents across 5 primary categories (Housing, Infrastructure, Investors, Utilities, Governance) to route to dense + BM25 indices. |

---

## 2. Global Architecture Diagram

```
                             [ RAW DATA SOURCES ]
      HUDCO Annual Reports (PDF)  │  Website HTML / FAQs  │  Circulars & Forms
                                   │
                                   ▼
                    [ STAGE 1: INGESTION & TRIAGE ]
      - SHA-256 Deduplication Registry (PostgreSQL)
      - PDF Table of Contents (TOC) Extraction & Logical Splitting
      - Document Cataloguing (Authority Tiering & Date Stamping)
      - Stream-based Processing (Low Memory Footprint for 300MB+ files)
                                   │
                                   ▼
                   [ STAGE 2: PARSING & EXTRACTION ]
      - High-Speed Text: pypdf / pdfplumber / fitz fallback
      - Financial Tables: Markdown table extraction (Preserving column structure)
      - Web Cleaner: BeautifulSoup4 + Trafilatura (Scraping core article blocks)
      - Boilerplate Filter: Regex-based header, footer, & proxy form elimination
                                   │
                                   ▼
               [ STAGE 3: SKILL-BASED STRUCTURING & INTENT ]
      - Schema Enforcement via Pydantic & Gemini Structured Outputs
      - Pre-computed Intent Assignment (e.g., FINANCIAL_RESULTS, HOUSING_SCHEMES)
      - Entity Extraction (Monetary units, years, schemes, departments)
      - Citation Provenance Metadata Attachment
                                   │
                                   ▼
                   [ STAGE 4: DUAL STORAGE ARCHITECTURE ]
        ┌──────────────────────────┴──────────────────────────┐
        ▼                                                     ▼
  [ Vector Store: ChromaDB ]                            [ PostgreSQL Database ]
  - Chunk Embeddings (Sentence-Transformers)            - Relational Document Registry
  - Semantic Similarity Search                          - Exact Key-Value Facts & Metrics
  - Hybrid Lexical / BM25 Search (rank-bm25)            - Office Contacts & Scheme Rules
        │                                                     │
        └──────────────────────────┬──────────────────────────┘
                                   ▼
                       [ FASTAPI RUNTIME LAYER ]
      - Redis Session Memory & Token Bucket Rate Limiter
      - Intent Router & Hybrid Retrieval Orchestrator (Dense + BM25)
      - Gemini Grounded Generation with Exact Provenance Citations
```

---

## 3. Technology Stack & Library Allocation

```
   ┌───────────────────────┬───────────────────────────────────┬──────────────────────────────────────────┐
   │ Subsystem             │ Selected Libraries                │ Architectural Responsibility             │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Ingestion & Web       │ requests, aiohttp, trafilatura,   │ Site discovery, clean article body       │
   │                       │ beautifulsoup4, htmldate          │ extraction, metadata extraction.         │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ PDF Processing        │ pypdf, pdfplumber, fitz (PyMuPDF) │ TOC extraction, streaming segmentation,  │
   │                       │                                   │ tabular data preservation into Markdown. │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Schema Validation     │ pydantic (v2), jsonschema         │ Strict enforcement of JSON schemas       │
   │                       │                                   │ before database/vector persistence.      │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ AI & Structuring      │ google-generativeai, groq         │ Structured JSON chunk formatting,        │
   │                       │                                   │ intent classification, entity extraction.│
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Vector Search         │ chromadb, langchain-chroma,       │ Semantic similarity embeddings, hybrid   │
   │                       │ sentence-transformers             │ dense vector retrieval.                  │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Keyword Search        │ rank-bm25                         │ Exact match searches for financial terms,│
   │                       │                                   │ circular numbers, and section codes.     │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Structured Store      │ SQLAlchemy, PostgreSQL, asyncpg   │ Document registry, SHA-256 hashes, status│
   │                       │                                   │ tracking, structured factual records.    │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Backend & Serving     │ fastapi, uvicorn, starlette       │ High-throughput asynchronous REST API    │
   │                       │                                   │ for chat interface and admin ingestion.  │
   ├───────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
   │ Session & Config      │ redis, pydantic-settings          │ Session memory (TTL), sliding window     │
   │                       │                                   │ rate limiting, environment config.       │
   └───────────────────────┴───────────────────────────────────┴──────────────────────────────────────────┘
```

---

## 4. The Unified Knowledge Schema (JSON Chunk Specification)

Every piece of extracted knowledge—whether an entire HTML FAQ or a single table from an Annual Report—is normalized into the following atomic structure:

```json
{
  "chunk_id": "HUDCO_AR_2024-25_FIN_P084_C01",
  "document_id": "HUDCO_AR_2024-25",
  "source": {
    "title": "55th Annual Report 2024-25",
    "document_type": "annual_report",
    "url": "https://www.hudco.org.in/writereaddata/AnnualReport2024-25.pdf",
    "fiscal_year": "2024-25",
    "page_start": 84,
    "page_end": 85,
    "authority_tier": 1,
    "is_latest": true
  },
  "classification": {
    "department": "Finance & Accounts",
    "section_title": "Financial Performance & Profitability",
    "primary_intent": "FINANCIAL_RESULTS",
    "secondary_intents": ["LOAN_DISBURSEMENTS", "NET_PROFIT", "NPA_STATUS"],
    "entities_covered": ["Loan Sanctioned", "Loan Disbursed", "PAT", "Net Worth"]
  },
  "content": {
    "summary": "Key financial highlights of HUDCO for FY 2024-25 comparing disbursements, sanctions, and profit after tax against FY 2023-24.",
    "text_content": "During FY 2024-25, HUDCO achieved remarkable operational performance with total loan sanctions of Rs. 82,350 crore and Profit After Tax (PAT) standing at Rs. 2,450 crore.",
    "tables": [
      {
        "table_id": "T01_FIN_HIGHLIGHTS",
        "title": "Financial Indicators Comparison",
        "markdown": "| Particulars | FY 2024-25 (Rs. Cr) | FY 2023-24 (Rs. Cr) | Growth (%) |\n|---|---|---|---|\n| Loan Sanctions | 82,350 | 54,200 | +51.9% |\n| Loan Disbursements | 38,100 | 28,500 | +33.6% |\n| Profit After Tax (PAT) | 2,450 | 1,815 | +35.0% |"
      }
    ]
  },
  "metadata": {
    "char_count": 890,
    "token_estimate": 220,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "created_at": "2026-09-24T02:00:00Z",
    "version": 1
  }
}
```

---

## 5. Domain Taxonomy & Intent Hierarchy

To prevent the chatbot from getting confused by broad prompts (e.g., *"I want a loan"*), queries and documents are mapped to strict intent spaces:

### Category A: Housing Finance
* **`RETAIL_HOUSING_LOAN`**: Individual home loans, interest structures, guidelines, eligibility criteria.
* **`PMAY_SCHEMES`**: PMAY(U)-2.0, interest subsidy scheme (ISS), credit linked subsidy scheme (CLSS), beneficiary requirements.
* **`STAFF_HOUSING`**: Specific guidelines for institutional, public body, and staff loan schemes.

### Category B: Urban Infrastructure
* **`INFRA_PROJECT_FINANCING`**: Water supply, sewerage, drainage, solid waste management, roads, power, and urban transport financing.
* **`CONSULTANCY_SERVICES`**: Asset management, urban planning, disaster mitigation, and technical consultancy services.

### Category C: Investor & Financial Disclosures
* **`FINANCIAL_RESULTS`**: Quarterly/annual revenue, profit after tax (PAT), net worth, balance sheets, NPA ratios.
* **`BONDS_AND_BORROWINGS`**: Tax-free bonds, 54EC capital gains bonds, public issues, ECB borrowings.
* **`ANNUAL_REPORTS`**: Official yearly operating statements, chairman speeches, management discussion & analysis (MD&A), directors' reports.

### Category D: Navigation & Direct Utilities
* **`LOCATE_OFFICE`**: Regional office addresses, head office contacts, key contact persons, email/phone numbers.
* **`DOWNLOAD_FORMS`**: KYC forms, loan application forms, checklist downloads, circular links.
* **`FAQ_LOOKUP`**: Official website Q&A items, customer service procedures.

### Category E: Governance & Compliance
* **`VIGILANCE_POLICY`**: Whistleblower policies, anti-corruption mechanisms, vigilance complaint portal guidelines.
* **`BOARD_MEMBERS`**: Key management personnel, Board of Directors, leadership profiles, committee compositions.

---

## 6. Execution Pipeline & Development Stages

```
   ┌───────────────────────────────────────────────────────────────────────────┐
   │                       PIPELINE EXECUTION PHASES                           │
   └───────────────────────────────────────────────────────────────────────────┘
```

### Stage 1 — Ingestion & PDF Segmentation (`pipeline/stage_1_ingestion/`)
* **`downloader.py`**: Async download worker with SHA-256 integrity verification, deduplication, and local caching.
* **`segmenter.py`**: Stream-based Table of Contents (TOC) parsing to split 200MB–300MB PDFs into logical sub-documents (e.g., Director's Report, Financial Statements, MDA) preventing memory spikes.
* **Deliverables**: Ingested raw files, deduplicated registry in PostgreSQL, segment manifest.

### Stage 2 — Hybrid Extraction & Cleaning (`pipeline/stage_2_parsing/`)
* **`text_cleaner.py`**: Plain text extraction and cleaning with regex-based removal of running headers, footers, page numbers, and proxy voting boilerplate.
* **`table_extractor.py`**: Specialized tabular extraction retaining columns and converting complex financial matrices into GitHub-flavored Markdown tables.
* **`html_crawler.py`**: Web crawler powered by `trafilatura` and `BeautifulSoup4` for scraping official HUDCO web pages and FAQs.
* **Deliverables**: Clean Markdown content files with aligned tables in `data/intermediate/sections/`.

### Stage 3 — Skill Extraction & Intent Tagging (`pipeline/stage_3_structuring/`)
* **`schemas.py`**: Pydantic models enforcing schema constraints and data types for the Unified Knowledge Schema.
* **`intent_classifier.py`**: Zero-shot / Few-shot LLM structuring (Gemini Flash) with JSON structured outputs to tag primary/secondary intents and extract named entities.
* **Deliverables**: Validated JSON atomic chunks in `data/output_chunks/`.

### Stage 4 — Dual Database Load & Indexing (`pipeline/stage_4_storage/`)
* **`chroma_loader.py`**: Batch embedding generator using Sentence-Transformers (`all-MiniLM-L6-v2` / `bge-base-en-v1.5`) with ChromaDB persistent collection indexing and BM25 tokenization.
* **`db_registry.py`**: PostgreSQL / SQLAlchemy models for relational document metadata, chunk manifests, office directories, and exact key-value facts.
* **Deliverables**: Fully indexed ChromaDB collection and synchronized PostgreSQL knowledge registry.

### Stage 5 — Retrieval Orchestration & Chat API (`pipeline/stage_5_api/`)
* **Intent-Aware Hybrid Search**: Combines dense semantic vector retrieval (ChromaDB) with exact keyword matching (BM25).
* **Provenance Grounding**: Injects strict citation prompts into Gemini, formatting answers with exact page numbers, document links, and authority tiers.
* **FastAPI Backend**: Async endpoints with Redis-backed session memory and sliding-window rate limiters.

---

## 7. Project Directory Structure

```
hudco/
├── README_ARCHITECTURE_AND_PLANNING.md       # Root blueprint documentation
├── docs/
│   └── README_ARCHITECTURE_AND_PLANNING.md   # Synced docs copy
├── config/
│   ├── __init__.py
│   └── settings.py                           # Pydantic environment configuration
├── pipeline/
│   ├── stage_1_ingestion/
│   │   ├── __init__.py
│   │   ├── downloader.py                     # SHA-256 download worker & dedup
│   │   ├── segmenter.py                      # Memory-safe PDF TOC splitting
│   │   └── README_STAGE_1_INGESTION.md
│   ├── stage_2_parsing/
│   │   ├── __init__.py
│   │   ├── text_cleaner.py                   # Boilerplate/header/footer cleaner
│   │   ├── table_extractor.py                # Markdown tabular extraction
│   │   ├── html_crawler.py                   # Trafilatura web & FAQ scraper
│   │   └── README_STAGE_2_EXTRACTION.md
│   ├── stage_3_structuring/
│   │   ├── __init__.py
│   │   ├── schemas.py                        # Pydantic Unified Chunk Models
│   │   ├── intent_classifier.py              # LLM intent tagger & entity extractor
│   │   └── README_STAGE_3_INTENT_TAGGING.md
│   └── stage_4_storage/
│       ├── __init__.py
│       ├── chroma_loader.py                  # ChromaDB vector indexer + BM25
│       ├── db_registry.py                    # PostgreSQL / SQLAlchemy schema
│       └── README_STAGE_4_STORAGE_AND_RAG.md
└── data/
    ├── raw/
    │   ├── annual_reports/                   # Downloaded PDF reports
    │   ├── circulars/                        # Loan & PMAY circulars
    │   └── web_pages/                        # Scraped HTML pages
    ├── intermediate/
    │   └── sections/                         # Segmented PDF sections & MD tables
    └── output_chunks/                        # Validated JSON chunks ready for store
```

---

## 8. Memory Management & Scalability Strategy for 300MB+ PDFs

1. **Never load full binary PDFs into RAM as continuous byte arrays.**
2. **Page-by-Page Streaming & Iterator Processing:** Using `pypdf` / `fitz` iterators to stream 10–20 pages at a time into temporary section buffers.
3. **TOC Pre-scan:** Extract the outline tree in <100ms, mapping start/end page ranges for logical chapters (Directors' Report, Financial Statements, Auditor's Report, Governance).
4. **Isolated Sub-Document Extraction:** Write each chapter directly to disk at `data/intermediate/sections/{doc_id}_{section_slug}.pdf` before parsing.
5. **Garbage Collection & Explicit Buffer Release:** Call `del` and `gc.collect()` after processing heavy tabular sections.

---

## 9. Verification & Quality Assurance Protocols

1. **Schema Validation:** 100% of generated chunk JSONs must pass Pydantic schema parsing (`schemas.UnifiedChunk.model_validate(chunk)`).
2. **Table Consistency Check:** Extracted Markdown tables must have identical column counts across all rows and retain valid numerical values.
3. **Citation Provenance:** Every response returned by the chat layer must reference valid `source.document_id`, `source.page_start`, and `source.url`.
4. **Zero-Hallucination Fallback:** If retrieval similarity score falls below `0.65` or query is completely out-of-scope, the bot falls back to official contact directories and verified disclaimer templates.
