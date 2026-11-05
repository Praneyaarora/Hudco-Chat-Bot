# Clean Document Processing and Chunking Pipeline: Production Architecture Specification

**Document Identifier**: `HUDCO-DOCPROC-ARCH-2026-V2`  
**Target Path**: `docs/ARCHITECTURE.md`  
**Status**: Approved Phase 0B Architecture Blueprint (Extended for Automated Website-to-Knowledge Ingestion)  
**Author**: Senior RAG Architect & Data Systems Engineer  
**Scope**: Continuous Multi-Source Acquisition (Local Filesystem, Direct URLs, Configured Websites), Safe Network Fetching, Structural Decomposition, Canonical Representation, Section-Aware Chunking, and Provenance Auditing  
**Primary Target Formats**: PDF (Annual Reports, Policy Circulars) and HTML (Web Pages, FAQs)  
**Extensible Formats**: DOCX, Markdown, Plain Text (via format adapters)  

---

## 1. System Mission and Core Principles

The document processing system in this repository is designed as an automated, continuous, standalone document-ingestion and chunk-production pipeline. Its mission is to discover and acquire documents from local directories, direct URLs, and approved websites, verify their authenticity and change state, and convert them into high-fidelity, section-aware, provenance-grounded knowledge chunks accompanied by machine-readable quality manifests.

It is **not** a user-facing chatbot, conversational memory manager, or LLM response orchestrator. The implemented system encompasses **Layers 1 through 4**: safe multi-source acquisition, zero-loss extraction, section-aware chunking, and deterministic table-aware Okapi BM25 indexing and retrieval (`pipeline/retrieval/`). Downstream generation systems (LLMs, prompt synthesis, multi-turn dialogs) consume its ranked retrieval results and provenance citations via the public Python API.

```
+----------------------------------------------------------------------------------------+
|                        IMPLEMENTED PIPELINE BOUNDARY (LAYERS 1-4)                      |
|                                                                                        |
|  [Source: Local / URL / Web] ---> [Safe Connector] ---> [Format Adapter] ---> [Structure]
|                                                                                   |    |
|  [Run Manifest] <--- [Quality Gates] <--- [Chunk Generator] <--- [Canonical Doc] <--   |
|                                              |                                         |
|                                     [Canonical Chunks]                                 |
|                                              |                                         |
|                                              v                                         |
|                          [Layer 4 Table-Aware BM25 Index]                              |
|                          [Dual-Threshold Calibrated Abstention]                        |
+----------------------------------------------+-----------------------------------------+
                                               |
                                     [Ranked Results + Provenance]
                                               |
                                               v
                       +----------------------------------------------+
                       |     DOWNSTREAM CONSUMERS (LAYER 5 - CHATBOT) |
                       |    Prompt Synthesis * LLM * Dialog Manager   |
                       +----------------------------------------------+
```

### Core Design Principles

1. **Unified Downstream Convergence**: Documents from all three ingestion paths (local filesystem, direct URL, configured website crawl) converge into the exact same canonical extraction, structural inference, and chunking pipeline. There is no separate "website chunking pipeline".
2. **Format Agnosticism via Canonical Representation**: Raw formats (PDF, HTML, DOCX) are immediately translated into an intermediate `CanonicalDocument` tree composed of typed content blocks (headings, paragraphs, lists, tables). Downstream chunkers never inspect raw PDF streams or HTML DOM nodes.
3. **Decoupled Source Discovery vs. Content Extraction**: Resource discovery (crawling sitemaps, RSS, listing tables, pagination) is isolated in `pipeline/connectors/`. Content extraction (parsing pages, geometry, DOM nodes) is isolated in `pipeline/adapters/`.
4. **Zero Ingestion-Time Document Mutation (Virtual Segmentation)**: Physical PDF slicing (`PdfWriter`) is completely eliminated. The master source document remains untouched, and sections are tracked as logical ranges over canonical content blocks.
5. **Rigorous Dual-Page & Locator Provenance**: Physical PDF page numbers (1-based physical sheet index in the PDF stream) and printed page numbers (the page number stamped in the report layout) are tracked as distinct, non-conflated metadata attributes. HTML blocks carry canonical URLs, CSS locators, and heading breadcrumbs.
6. **First-Class Table Preservation**: Tables are treated as rich structural blocks with matrix coordinates, column headers, units of measure, and markdown renderings. When a table cannot be extracted cleanly, the system degrades gracefully and logs an explicit warning rather than emitting mangled plain text or claiming clean success.
7. **Multi-Strategy Structural Inference with Safe Fallback**: Logical sections are inferred through a strict 5-tier waterfall: (1) native PDF outlines (with semantic quality gate), (2) HTML heading tree, (3) printed Table of Contents (TOC) matching against verified printed page labels, (4) page-top heading typography signals, and (5) conservative document-level window fallback with explicit `LOW_CONFIDENCE_FALLBACK` audit warning.
8. **Strict Error Accounting and Four-Tier Statuses**: Every run produces an exhaustive run manifest. Processing statuses explicitly distinguish `SUCCESS`, `SUCCESS_WITH_WARNINGS`, `PARTIAL_SUCCESS` (or `PARTIAL_FAILURE`), and `FAILED`. A run with missing pages, unassigned block recovery, failed tables, or low confidence fallback is degraded to `PARTIAL_SUCCESS` and is never marked as a clean success.

---

## 2. Logical Pipeline Architecture

The pipeline consists of ten sequential, loosely coupled stages spanning acquisition, extraction, structuring, chunking, and auditing:

```
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                    STAGE 1: SOURCE DISCOVERY & SAFE ACQUISITION                     │
  │  Local Watcher • Direct URL Fetcher • Bounded Crawler (Sitemaps, Feeds, Listings)   │
  │  SSRF Guard • HTTPS Enforcement • Rate Limiter • Streaming Size Caps (250MB)        │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                 STAGE 2: CONTENT IDENTITY & INCREMENTAL REGISTRATION                │
  │  Streaming SHA-256 • ETag/Last-Modified • Version Lineage • Deduplication           │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                         STAGE 3: FORMAT ADAPTER EXTRACTION                          │
  │    Magic Byte Sniffing (%PDF-, <!DOCTYPE) ──► Dispatch to Adapter                   │
  │    [PDF Adapter: pypdf/pdfplumber]                 [HTML Adapter: bs4/trafilatura]  │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                       STAGE 4: STRUCTURAL ANALYSIS ENGINE                           │
  │  Native Bookmark Gate ─► Printed TOC Parser ─► Heading Hierarchy ─► Fallback Window │
  │  Section-by-section heading verification (No global offset; no hardcoded sections)  │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                 STAGE 5: CANONICAL DOCUMENT COMPOSITION                             │
  │  Assembly of CanonicalDocument: metadata, sections, typed content blocks, tables    │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                      STAGE 6: TABLE-SPECIFIC PROCESSING                             │
  │  Row/col matrices • Header hierarchy • Unit declarations • GFM Markdown generation   │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                    STAGE 7: SECTION-AWARE HIERARCHICAL CHUNKER                      │
  │  Paragraph-bounded windowing • Table encapsulation • Version-aware deterministic IDs │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                         STAGE 8: QUALITY AUDIT GATES                                │
  │  Acquisition check • Page coverage • Table integrity • Chunk distribution           │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                      STAGE 9: ARTIFACT PERSISTENCE & REPORTS                        │
  │  JSONL Chunks • Run Manifest JSON • Human-Readable Markdown Audit Report            │
  └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │
                                             ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                  STAGE 10: AUTOMATION, SCHEDULER & CLI ENTRYPOINTS                  │
  │  CLI: process-file / process-dir / crawl-source / run-scheduler                     │
  └─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Stage Specifications

### Stage 1: Source Discovery & Safe Acquisition

Operates via dedicated connectors under `pipeline/connectors/`. Full protocol and security details are documented in [`docs/SOURCE_CONNECTORS_AND_AUTOMATION.md`](file:///c:/Users/Praneya%20Arora/Desktop/Hudco/docs/SOURCE_CONNECTORS_AND_AUTOMATION.md).

- **Three Ingestion Entry Points**:
  1. *Local Filesystem Intake (`FilesystemConnector`)*: Scans incoming directories for `.pdf`, `.html`, etc., without network calls.
  2. *Direct URL Intake (`SafeHTTPFetcher`)*: Downloads a single specified URL with strict HTTP validation.
  3. *Configured Website Crawling (`WebsiteCrawler`)*: Follows approved sitemaps, RSS feeds, and HTML listing tables within `domain_allowlist` and `allowed_path_prefixes`. Enforces `max_depth` (default: 3) and `max_pages` (default: 50).
- **Security & Reliability Hardening**:
  - *SSRF Guard*: Resolves DNS hostnames and blocks internal/private IP ranges (`127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16`, `169.254.169.254`).
  - *Redirect Validation*: Max 5 redirects; every redirect target is checked against SSRF and allowlists.
  - *Streaming Limits*: Max 250 MB for PDF annual reports, 25 MB for HTML pages. Enforces 10:1 decompression ratio caps to prevent decompression bombs.
  - *Politeness*: Rate-limiting token bucket enforcing a minimum 1.5-second delay per host. Complies with `robots.txt`.
  - *Sanitization*: Strips authentication tokens, passwords, and sensitive cookies from all log outputs.

### Stage 2: Content Identity, Versioning, and Incremental Registration

- **Responsibility**: Tracks source assets across repeated runs, preventing wasteful re-processing and maintaining historical version lineage.
- **Entity Identity Hierarchy**:
  - `source_id`: Persistent identifier for an origin location (e.g. `src_hudco_ar26`).
  - `document_id`: Canonical asset identifier (e.g. `annual_report_ar26`).
  - `version_id`: Immutable content snapshot (e.g. `doc_ar26_v1_c412ce14`).
- **Change Detection Logic**:
  - Issues conditional HTTP `GET` with `If-None-Match` (ETag) or `If-Modified-Since`.
  - If HTTP 304, updates `last_checked_at` and bypasses download.
  - If HTTP 200, streams content through SHA-256 hasher. If SHA-256 matches active version, skips parsing.
  - If SHA-256 differs, creates `DocumentVersion(version_number = current + 1, is_current = True)`. Marks prior version `is_current = False` and flags old chunks as stale without destroying historical records.

### Stage 3: Format Detection and Format-Specific Extraction Adapters

The system sniffs content formats using magic bytes before dispatching to an adapter:
- PDF: `%PDF-` (`b"%PDF-"`) $\rightarrow$ `PDFDocumentAdapter`
- HTML: `<!DOCTYPE`, `<html` $\rightarrow$ `HTMLDocumentAdapter`

```python
class BaseDocumentAdapter(ABC):
    @abstractmethod
    def can_handle(self, mime_type: str, file_path: Path) -> bool: ...
    
    @abstractmethod
    def extract_raw_content(self, file_path: Path, config: AdapterConfig) -> RawExtractionPayload: ...
```

#### 3.1 PDF Adapter (`PDFDocumentAdapter`)
- Hybrid two-pass extraction:
  - *Pass 1 (Text & Geometry)*: `pypdf` streams text page-by-page, enumerates physical pages (1 to $N$), and extracts bookmarks.
  - *Pass 2 (Selective Table Extraction)*: `pdfplumber` extracts coordinate-aligned table matrices on pages flagged with tabular keywords.
- Zero page loss: Extracts physical pages 1 to $N$ completely, preserving front matter.
- Detects empty pages (`IS_BLANK_PAGE`) and scanned/image pages (`IS_SCANNED_PAGE`).

#### 3.2 HTML Adapter (`HTMLDocumentAdapter`)
- Strips non-content boilerplate: `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`, `<noscript>`.
- Preserves DOM heading hierarchy (`<h1>` to `<h6>`) as structural anchors.
- Extracts `<table>` structures into clean 2D lists of cell text, preserving `<th>` header semantics.
- Generates precise CSS selectors and heading breadcrumb locators.

---

### Stage 4: Structural Analysis Engine

The structural engine identifies logical section boundaries within the extracted document. It never uses hardcoded section counts or static page offsets.

#### Multi-Strategy Hierarchy
1. **Native Bookmark Quality Gate**: Inspects PDF outline bookmarks for minimum substantive count ($\ge 5$), valid destinations, and monotonicity.
2. **Printed Table of Contents (TOC) Discovery**: Scans initial 35 pages for `(?i)\b(contents|table of contents|index)\b` and regex-parsed section rows.
3. **Dual-Page Offset Resolver (Section-by-Section Verification)**: Rejects global offsets (e.g. `+2`). Matches section title tokens against candidate physical pages $[P_{\text{printed}} \dots P_{\text{printed}} + 25]$. Assigns locally verified physical boundaries to each section.
4. **Safe Document Fallback**: If structure cannot be verified, partitions document into fixed logical page blocks (e.g. 20–25 pages) labeled `Logical_Window_P001_P025` with an explicit `LOW_CONFIDENCE` warning.

---

### Stage 5: Canonical Document Representation

All format-specific outputs are normalized into an immutable, format-independent in-memory object hierarchy:

```
CanonicalDocument
 ├── DocumentMetadata (Source ID, Version ID, Document ID, Format, URLs, Timestamps)
 ├── QualityMetrics (Coverage, Warning List, Error List, Processing Status)
 └── Sections: List[CanonicalSection]
      ├── SectionMetadata (ID, Title, Level, Physical Page Range, Printed Page Range)
      └── Blocks: List[ContentBlock]
           ├── HeadingBlock (Text, Level, SourceLocator)
           ├── TextBlock (Text, ParagraphType, SourceLocator)
           ├── ListBlock (Items, IsOrdered, SourceLocator)
           └── TableBlock (StructuredTable, SourceLocator)
```

---

### Stage 6: Table-Specific Processing Engine

- **Extraction**: Extracts 2D string matrices `List[List[str]]` via coordinate line intersections.
- **Metadata Detection**: Extracts unit-of-measure declarations (e.g. `(₹ in Crore)`).
- **Markdown Normalization**: Generates clean GitHub-Flavored Markdown (GFM) tables, standardizing column delimiters and stripping internal linebreaks.
- **Oversized Tables**: Row-slices tables exceeding chunk limits, repeating the complete header row in every slice.
- **Graceful Degradation**: On jagged rows, logs `TABLE_MALFORMED` warning, pads cells with empty strings, and retains raw text alongside the matrix.

---

### Stage 7: Section-Aware Hierarchical Chunker

Operates over the `CanonicalDocument` block hierarchy:
1. **Section Boundaries are Hard Boundaries**: Chunks never cross section boundaries.
2. **Block-Aware Accumulation**: Groups sequential paragraphs up to `target_chunk_chars` (default: 1,200 chars). Breaks paragraphs only when exceeding `max_hard_chunk_chars` (default: 2,500 chars).
3. **Table Encapsulation**: Tables ($\le 2,000$ chars) form self-contained atomic chunks (`has_table = True`).
4. **Version-Aware Deterministic Chunk IDs**:
   - Formula: `{document_id}_v{version}_{hash8}_{section_id}_p{physical_page:03d}_c{chunk_index:02d}`
   - Example: `ar26_v1_c412ce14_sec_05_p052_c01`
   - Uniqueness: Stable across identical re-runs; distinct across document revisions.
5. **Configurable Sliding Overlap**: 150 chars applied only across continuous narrative text within the same section. Overlap is strictly prohibited across section or table boundaries.

---

### Stage 8: Automated Quality Audit Gates

Before artifacts are written to disk, the run is audited across both acquisition and extraction:

| Quality Gate | Description | Escalation Level |
|---|---|---|
| **Acquisition Gate** | Verifies HTTP status 200/304, SSL verification, and size caps. | Fatal error if download truncated. |
| **Page Coverage Gate** | Compares extracted physical pages against PDF trailer catalog count. | Fatal error if missing $> 0$ pages. |
| **Empty Content Gate** | Flags pages with 0 extracted characters. | Warning if $< 2\%$; Partial Failure if $> 5\%$. |
| **Suspiciously Short Content** | Flags non-blank pages with $< 100$ characters. | Warning logged with page number. |
| **Duplicate Chunk ID Gate** | Verifies global uniqueness of all generated chunk IDs. | Fatal error if collision detected. |
| **Provenance Integrity Gate** | Ensures every chunk has a valid physical page number / locator. | Fatal error if missing. |
| **Table Matrix Consistency** | Verifies uniform column counts across table rows. | Warning logged if jagged. |
| **TOC Range Sanity Gate** | Verifies non-overlapping and strictly monotonic section ranges. | Warning logged; clamped if invalid. |

#### Four-Tier Processing Status
1. `SUCCESS`: Flawless acquisition and extraction, 100% pages accounted for, all tables valid, high-confidence structure.
2. `SUCCESS_WITH_WARNINGS`: Completed, but non-fatal warnings occurred (e.g. blank pages, unaligned printed page offset in 1 section, single malformed table).
3. `PARTIAL_FAILURE`: Portions extracted, but significant anomalies occurred (e.g. $> 5\%$ unreadable pages, fallback windowing required).
4. `FAILED`: Fatal error halting processing (SSRF block, corrupt file, unreadable PDF, zero extractable content).

---

### Stage 9: Deterministic Artifact Persistence

The pipeline emits standard, versioned artifacts into dedicated directories:

```
data/
 ├── raw/
 │    └── {document_type}/                      # Immutable raw source assets
 ├── processed/
 │    └── chunks/
 │         └── {version_id}_chunks.jsonl        # Master JSONL chunk file
 └── manifests/
      └── runs/
           └── {run_id}/
                ├── run_manifest.json           # Machine-readable audit JSON
                └── run_report.md               # Human-readable Markdown summary
```

---

### Stage 10: Automation, Scheduler, & Unified CLI

The pipeline is driven by an intuitive CLI and local scheduler:

```bash
# Process a local file (PDF or HTML)
python -m pipeline.cli process-file --input data/raw/annual_reports/ar26.pdf --format pdf

# Process a directory of documents
python -m pipeline.cli process-dir --input-dir data/incoming/ --format pdf

# Ingest a direct URL
python -m pipeline.cli ingest-url --url https://hudco.org.in/writereaddata/ar26.pdf

# Crawl a configured website source
python -m pipeline.cli crawl-source --config config/sources/hudco_portal.json

# Run the automated background scheduler
python -m pipeline.cli run-scheduler --config config/scheduler.json
```

---

### Stage 11: Layer 4 Indexing & Retrieval Engine (`pipeline/retrieval/`)

The retrieval engine provides deterministic, table-aware lexical search and calibrated abstention over canonical chunks:
1. **Canonical Chunk Ingestion**: `load_canonical_chunks` validates canonical JSON schema, detects malformed JSON records, and rejects duplicate chunk IDs.
2. **Table-Aware Linearization**: `linearize_table` binds 2D cell values with row particulars, column headers, units of measure (`₹ in Crore`), and table captions into searchable text streams without mutating original chunk data.
3. **Financial Tokenizer**: `tokenize` normalizes fiscal year compounds (`2025-26`), strips commas from numerical values (`13,150.40`), normalizes Rupee symbols (`₹` -> `rs`), and filters grammatical stopwords (including pronouns) while retaining financial terms.
4. **Deterministic BM25Okapi**: `Layer4BM25Index` indexes chunks with inverted term postings, Robertson-Spärck Jones IDF, and calibrated length normalization ($b = 0.45$, $k_1 = 1.2$).
5. **Metadata Filtering**: Supports exact filtering on `document_id`, `version_id`, `section_id`, `min/max_physical_page`, and `has_table`. Stale (`is_stale=True`) records are excluded by default.
6. **Multi-Signal Calibrated Abstention**: Evaluates both score threshold ($\ge 12.0$) and query term coverage ($\ge 40\%$). Unanswerable queries reliably trigger `is_abstention = True` with diagnostic explanation.

---

## 4. Module Directory Structure

```
pipeline/
 ├── __init__.py
 ├── cli.py                        # Unified command-line interface
 ├── runner.py                     # EndToEndPipelineRunner & PipelineLock (orchestrator)
 ├── config.py                     # Global configuration & security thresholds
 ├── scheduler.py                  # Local interval runner and process file lock
 ├── connectors/                   # Stage 1: Discovery & Acquisition
 │    ├── __init__.py
 │    ├── base.py                  # BaseConnector abstract class
 │    ├── filesystem.py            # Local folder watcher & scanner
 │    ├── http_fetcher.py          # Safe HTTP fetcher with SSRF guards
 │    ├── crawler.py               # Bounded spider (sitemaps, RSS, listings)
 │    └── registry.py              # SourceRegistry & DocumentVersion ledger
 ├── adapters/                     # Stage 3: Format-Specific Parsers
 │    ├── __init__.py
 │    ├── base.py                  # BaseDocumentAdapter abstract class
 │    ├── pdf_adapter.py           # Hybrid pypdf + pdfplumber adapter
 │    ├── html_adapter.py          # BeautifulSoup + Trafilatura adapter
 │    ├── docx_adapter.py          # Future DOCX adapter placeholder
 │    └── markdown_adapter.py      # Future Markdown adapter placeholder
 ├── core/                         # Stages 2, 4-9: Canonical Pipeline Core
 │    ├── __init__.py
 │    ├── contracts.py             # Pydantic v2 schemas
 │    ├── canonical.py             # CanonicalDocument object model
 │    ├── structural.py            # TOC, bookmarks, heading resolver
 │    ├── chunker.py               # Hierarchical section-aware chunker
 │    ├── quality.py               # Quality gates, validators, metrics
 │    └── persistence.py           # JSONL, manifest, and report writers
 ├── retrieval/                    # Stage 11: Layer 4 Indexing & Retrieval
 │    ├── __init__.py
 │    ├── contracts.py             # RetrievalFilter, ResultItem, RetrievalResponse
 │    ├── loader.py                # Schema validation & duplicate chunk ID rejection
 │    ├── table_linearizer.py      # 2D table to row-column-unit search text
 │    ├── tokenizer.py             # Financial & numerical lexical tokenizer
 │    └── bm25.py                  # BM25Okapi index with filters & calibrated abstention
 └── utils/
      ├── __init__.py
      ├── security.py              # SSRF IP blacklists & DNS resolver
      ├── text_normalizer.py       # Non-destructive whitespace & unicode normalizer
      └── table_formatter.py       # GFM markdown table builder
```

---

## 5. Architectural Quality Attributes

- **Safety**: Multi-tier SSRF protection, strict HTTPS verification, domain allowlists, and streaming size limits ensure safe acquisition from untrusted public web sources.
- **Determinism**: Identical documents and configurations yield byte-identical chunk IDs, identical chunk boundaries, and identical manifest structures.
- **Memory Efficiency**: Ingestion and hashing utilize streaming buffers. Page-by-page extraction ensures that multi-hundred-page PDFs never cause Out-Of-Memory (OOM) exceptions.
- **Observability**: Every decision (selected TOC strategy, applied page offset, table degradation, chunk split) is explicitly recorded in `run_manifest.json`.
- **Fault Isolation**: An acquisition or extraction error on one page or document logs an isolated warning without crashing the entire run.
