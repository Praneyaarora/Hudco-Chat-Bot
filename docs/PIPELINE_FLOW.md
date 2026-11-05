# Pipeline Data Flow & Architecture Diagrams

**Document Identifier**: `HUDCO-DOCPROC-FLOWS-2026-V2`  
**Target Path**: `docs/PIPELINE_FLOW.md`  
**Status**: Approved Phase 0B Architecture Visualizations (Extended for Discovery & Versioning)  
**Scope**: Formal Mermaid diagrams illustrating multi-source acquisition, website crawling, SSRF mitigation, incremental change detection, adapter dispatch, structural inference decision trees, table degradation flows, and component sequence interactions.

---

## 1. Multi-Source Ingestion & Acquisition Flow

Illustrates how local files, direct URLs, and website crawls converge safely into the common extraction engine.

```mermaid
flowchart TD
    subgraph IntakeEntry["Ingestion Entry Points"]
        E1["Entry A: Local Filesystem<br/>Watch Dir Scanner"]
        E2["Entry B: Direct URL<br/>CLI / Automated Ingest"]
        E3["Entry C: Configured Website<br/>Seed URLs & Sitemaps"]
    end

    subgraph Acquisition["Acquisition & Safety Layer"]
        E1 --> F1["Streaming File Checksum<br/>data/incoming/"]
        E2 --> S1["SSRF Guard & Allowlist Check"]
        E3 --> C1["Bounded Spider & Crawler<br/>Sitemaps • Listings • Pagination"]
        C1 --> S1
        S1 --> S2{"Passes Security Gates?<br/>(Public IP, Valid Domain, SSL)"}
        S2 -- "No" --> S_Err["Abort Request<br/>Log SSRF_BLOCKED / DISALLOWED"]
        S2 -- "Yes" --> S3["Safe HTTP Fetcher<br/>Rate Limiter • Max 250MB Cap"]
        S3 --> S4{"HTTP Response Status"}
        S4 -- "HTTP 304 (Not Modified)" --> S_Skip["Update last_checked_at<br/>Skip Download (Unchanged)"]
        S4 -- "HTTP 200 (OK)" --> S5["Stream to Spool File<br/>Compute SHA-256"]
    end

    subgraph Registry["Source Registry & Change Detection"]
        F1 & S5 --> R1["Lookup SourceRecord & Active Version"]
        R1 --> R2{"Content SHA-256 Matches Active?"}
        R2 -- "Yes" --> R_Skip["Duplicate / Unchanged Content<br/>Skip Re-parsing"]
        R2 -- "No" --> R3["Create New DocumentVersion<br/>(version = current + 1)"]
        R3 --> R4["Mark Prior Version is_current=False<br/>Flag Prior Chunks is_stale=True"]
        R4 --> R5["Move to Managed Raw Storage<br/>data/raw/{type}/"]
    end

    subgraph FormatGate["Format Sniffer & Adapter Dispatch"]
        R5 --> M1["Magic Byte Sniffer<br/>(%PDF-, <!DOCTYPE html, PK\x03\x04)"]
        M1 -- "PDF Bytes" --> A_PDF["PDFDocumentAdapter<br/>(pypdf + pdfplumber)"]
        M1 -- "HTML Bytes" --> A_HTML["HTMLDocumentAdapter<br/>(bs4 + trafilatura)"]
    end

    subgraph CoreEngine["Common Canonical Core Pipeline"]
        A_PDF & A_HTML --> C_Doc["Assemble CanonicalDocument"]
        C_Doc --> C_Struct["Multi-Strategy Structural Engine"]
        C_Struct --> C_Chunk["Hierarchical Section-Aware Chunker"]
        C_Chunk --> C_Quality["Automated Quality Gates"]
        C_Quality --> C_Persist["Persist Versioned JSONL & Manifest"]
    end

    classDef success fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef warn fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    classDef fail fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    class C_Persist success;
    class S_Skip,R_Skip warn;
    class S_Err fail;
```

---

## 2. Website Discovery & Crawling Lifecycle

Shows how the bounded crawler traverses sitemaps, RSS feeds, and listing pages while respecting domain boundaries and pagination limits.

```mermaid
flowchart TD
    Start(["Start Website Crawl: SourceConfiguration"]) --> Init["Read robots.txt & Domain Allowlists"]
    Init --> CheckSitemap{"Sitemap XML Available?"}
    
    CheckSitemap -- "Yes" --> ParseSitemap["Parse /sitemap.xml<br/>Filter URLs against Path Prefixes"]
    CheckSitemap -- "No" --> SeedQueue["Queue Seed URLs"]
    ParseSitemap --> SeedQueue

    SeedQueue --> FetchPage["Pop Next URL from Queue<br/>Check Depth <= max_depth"]
    FetchPage --> RateLimit["Token Bucket Rate Limiter (Wait >= 1.5s)"]
    RateLimit --> FetchHTML["Safe HTTP Fetcher (HTML GET)"]
    
    FetchHTML --> CheckType{"Content-Type is HTML?"}
    CheckType -- "No (Direct Document)" --> RouteDoc["Queue for Document Ingestion"]
    CheckType -- "Yes" --> ParseDOM["Parse HTML DOM with BeautifulSoup"]

    ParseDOM --> ExtractLinks["Extract Anchor Links (<a href=...>)"]
    ExtractLinks --> FilterLinks["Apply Content vs Discard Filters<br/>(Strip tracking, ignore admin/css/js)"]
    
    FilterLinks --> ClassifyLinks{"Link Target Type"}
    ClassifyLinks -- "Downloadable File (.pdf)" --> RouteDoc
    ClassifyLinks -- "Listing / Sub-Page" --> EnqueueSubPage["Queue Sub-Page (Depth + 1)"]
    ClassifyLinks -- "Pagination Link (Next/Page 2)" --> EnqueuePage["Queue Next Page (Same Depth)"]
    ClassifyLinks -- "Disallowed / External" --> DiscardLink["Discard Link"]

    EnqueueSubPage & EnqueuePage --> CheckLimits{"Queue Empty OR Pages >= max_pages?"}
    CheckLimits -- "No" --> FetchPage
    CheckLimits -- "Yes" --> EmitCrawlManifest["Emit CrawlRunManifest<br/>(Pages Crawled, Docs Found)"]
    RouteDoc --> BatchIngest["Dispatch Discovered Documents to Common Pipeline"]
```

---

## 3. Safe HTTP Acquisition & SSRF Protection Sequence

Details the exact security checks performed on every network request before a single byte of body data is consumed.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Web Crawler / URL Ingest
    participant Guard as SSRFSecurityGuard
    participant DNS as System DNS Resolver
    participant Fetcher as SafeHTTPFetcher
    participant Server as Target Remote Host
    participant Spool as Local Spool Storage

    Caller->>Guard: validate_url(target_url)
    Guard->>Guard: Verify HTTPS scheme
    Guard->>Guard: Check host in domain_allowlist
    
    Guard->>DNS: resolve_ip(hostname)
    DNS-->>Guard: Resolved IP (e.g. 104.21.45.12)
    Guard->>Guard: Check IP against Blacklist<br/>(Rejects 127.0.0.1, 10.0.0.0/8, 169.254.169.254)
    
    alt IP is Private / Loopback / Metadata
        Guard-->>Caller: ABORT: SSRF_BLOCKED_ERROR
    else IP is Public & Allowed
        Guard-->>Fetcher: URL Validated
        Fetcher->>Server: HTTP HEAD / GET (stream=True, timeout=10s, headers=ETag)
        Server-->>Fetcher: HTTP 200 OK (Content-Length, Content-Type)
        
        Fetcher->>Fetcher: Check Content-Length <= max_download_bytes (250MB)
        alt Content-Length exceeds limit
            Fetcher-->>Caller: ABORT: MAX_SIZE_EXCEEDED
        else Within size limit
            Fetcher->>Spool: Open temporary spool file
            loop Stream Chunks (64 KB)
                Server-->>Fetcher: Body Chunk
                Fetcher->>Fetcher: Update Streaming SHA-256
                Fetcher->>Fetcher: Verify Cumulative Bytes <= max_download_bytes
                Fetcher->>Spool: Write Chunk
            end
            Fetcher->>Spool: Inspect first 16 bytes (Magic Bytes)
            Fetcher-->>Caller: FetchResult(SHA-256, spool_path, ETag, MIME)
        end
    end
```

---

## 4. Incremental Change Detection & Version Lineage State Machine

Illustrates how the pipeline tracks versions, detects modifications, and manages stale chunks without deleting historical compliance records.

```mermaid
stateDiagram-v2
    [*] --> Discovered: URL or File Identified
    
    Discovered --> CheckingRegistry: Query SourceRecord by URL
    
    CheckingRegistry --> NewDocument: URL Not Found in Registry
    CheckingRegistry --> ExistingDocument: URL Already Exists
    
    NewDocument --> IngestingV1: Create SourceRecord & Version 1
    
    ExistingDocument --> ConditionalFetch: Send If-None-Match / If-Modified-Since
    
    ConditionalFetch --> Unchanged: HTTP 304 OR Identical SHA-256
    Unchanged --> [*]: Update last_checked_at (Bypass Extraction)
    
    ConditionalFetch --> ChangedContent: HTTP 200 AND New SHA-256
    
    ChangedContent --> Superseding: Create Version (current + 1)
    Superseding --> IngestingNewVersion: Mark Old Version is_current=False
    
    IngestingNewVersion --> EmittingChunks: Tag Prior Chunks is_stale=True
    IngestingV1 --> EmittingChunks: Process Canonical Pipeline
    
    EmittingChunks --> Completed: Emit Master JSONL Chunks
    Completed --> [*]: Update SourceRecord current_version_id
    
    ExistingDocument --> UpstreamMissing: HTTP 404 / 410 (Confirmed)
    UpstreamMissing --> MarkedRemoved: Set status=UPSTREAM_REMOVED<br/>(Retain Historical Files & Manifests)
    MarkedRemoved --> [*]
```

---

## 5. PDF Structural Inference Decision Tree

Illustrates the exact four-tier hierarchy used to determine section boundaries without hardcoded configurations or unvalidated assumptions.

```mermaid
flowchart TD
    Start(["Input: Raw PDF Document"]) --> Step1["Step 1: Inspect Native Outline Bookmarks"]
    
    Step1 --> CheckOutline{"Outline Exists & Entries >= 5?"}
    CheckOutline -- "Yes" --> ValidateOutline["Validate Monotonicity, Destinations, & Title Quality"]
    CheckOutline -- "No" --> Step2["Step 2: Scan First 35 Pages for Printed TOC"]
    
    ValidateOutline --> QualityGate{"Passes Outline Quality Gate?"}
    QualityGate -- "Passed (HIGH Confidence)" --> UseOutline["Strategy: NATIVE_OUTLINE<br/>Direct Physical Page Assignment"]
    QualityGate -- "Failed (Weak/Meaningless Titles)" --> Step2
    
    Step2 --> MatchTOC{"TOC Heading & Line Patterns Found?"}
    MatchTOC -- "Yes (>= 3 Valid Rows)" --> ParseTOC["Parse Section Titles & Printed Page Numbers"]
    MatchTOC -- "No" --> Step3["Step 3: Heading Typography & Style Analysis"]
    
    ParseTOC --> ResolveOffset["Section-by-Section Heading Verification Window<br/>(Sample physical pages [printed .. printed + 25])"]
    ResolveOffset --> CheckOffsetMatch{"Heading Verified on Physical Page?"}
    CheckOffsetMatch -- "Yes (Matches Found)" --> AssignOffset["Strategy: TOC_PAGE_DISCOVERY<br/>Verified Local Offsets (HIGH Confidence)"]
    CheckOffsetMatch -- "No Clear Verification" --> ClusterOffset["Apply Dominant Cluster Offset<br/>Log UNCERTAIN_OFFSET Warning (MEDIUM Confidence)"]
    
    Step3 --> MatchHeadings{"Consistent Visual Headings Detected?"}
    MatchHeadings -- "Yes" --> AssignHeadingSections["Strategy: HEADING_HIERARCHY<br/>Physical Heading Anchors (MEDIUM Confidence)"]
    MatchHeadings -- "No" --> Step4["Step 4: Safe Document-Level Fallback Windowing"]
    
    Step4 --> FallbackWindow["Strategy: FIXED_WINDOW_FALLBACK<br/>Partition into 25-page logical blocks<br/>Log LOW_CONFIDENCE Warning"]
    
    UseOutline & AssignOffset & ClusterOffset & AssignHeadingSections & FallbackWindow --> FinalPlan["Emit Non-Overlapping CanonicalSection Hierarchy"]

    classDef highConf fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef medConf fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    classDef lowConf fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    class UseOutline,AssignOffset highConf;
    class ClusterOffset,AssignHeadingSections medConf;
    class FallbackWindow lowConf;
```

---

## 6. Table Extraction & Graceful Degradation Flow

Shows how financial tables are processed into markdown matrices, with automated detection and isolation of malformed cells.

```mermaid
flowchart TD
    T_In["Page Content with Tabular Structure Detected"] --> T1["pdfplumber Coordinate Line & Cell Boundary Scan"]
    T1 --> T2{"Table Matrix Extracted Successfully?"}
    
    T2 -- "Yes" --> T3["Detect Table Caption & Unit of Measure (e.g. Rs. in Crore)"]
    T2 -- "No (Parsing Error / Empty)" --> T_Raw["Preserve Raw Whitespace-Delimited Text"]
    
    T3 --> T4["Consolidate Multi-Line Header Rows"]
    T4 --> T5["Check Row-Column Dimension Uniformity"]
    
    T5 --> T6{"Are All Rows Uniform Column Length?"}
    T6 -- "Yes" --> T7["Build Clean GitHub-Flavored Markdown Table"]
    T6 -- "No (Jagged Columns)" --> T8["Pad Short Rows with Empty Strings<br/>Flag is_malformed = True<br/>Log TABLE_MALFORMED Warning"]
    
    T8 --> T7
    T7 --> T9{"Table Size <= Max Chunk Size (2,500 chars default)?"}
    T9 -- "Yes" --> T10["Encapsulate as Atomic Table Chunk (has_table=True)"]
    T9 -- "No (Oversized Financial Statement)" --> T11["Preserve Atomic Table or Slice Sub-Chunks<br/>Repeat Full Header Row in Every Slice"]
    
    T_Raw --> T12["Log TABLE_EXTRACTION_FAILED Warning<br/>Treat as Regular Text Block"]
    T10 & T11 & T12 --> T_Done["Emit to Canonical Section"]
```

---

## 7. Component Sequence Interaction Across the Complete Pipeline

Traces execution across all modules during a scheduled crawl of an annual report website.

```mermaid
sequenceDiagram
    autonumber
    actor Cron as Scheduler / CLI
    participant Spider as WebsiteCrawler
    participant Fetcher as SafeHTTPFetcher
    participant Reg as SourceRegistry
    participant Adapter as PDFDocumentAdapter
    participant Struct as StructuralAnalyzer
    participant Chunker as HierarchicalChunker
    participant Quality as QualityAuditor
    participant Storage as PersistenceManager

    Cron->>Spider: crawl_source(config)
    Spider->>Fetcher: fetch_html("https://hudco.org.in/reports.html")
    Fetcher-->>Spider: Listing HTML (Found link: "ar26.pdf")
    Spider->>Reg: check_resource("https://.../ar26.pdf")
    Reg-->>Spider: New resource detected
    
    Spider->>Fetcher: fetch_document("https://.../ar26.pdf")
    Fetcher->>Fetcher: SSRF Guard + Streaming Size Check
    Fetcher-->>Spider: FetchResult (spool_path, SHA-256 c412ce14)
    
    Spider->>Reg: register_version("src_ar26", SHA-256, v1)
    Reg-->>Spider: DocumentVersion(doc_ar26_v1_c412ce14)
    
    Spider->>Adapter: extract_raw_content(spool_path)
    Adapter-->>Spider: RawExtractionPayload (520 physical pages)
    
    Spider->>Struct: infer_structure(raw_payload)
    Struct-->>Spider: SectionPlan (19 logical sections, verified offsets)
    
    Spider->>Chunker: generate_chunks(canonical_doc)
    Note over Chunker: Generates deterministic chunks:<br/>doc_ar26_v1_c412ce14_sec_05_p052_c00
    Chunker-->>Spider: List[CanonicalChunk]
    
    Spider->>Quality: audit_run(canonical_doc, chunks)
    Quality-->>Spider: QualityReport (Status: SUCCESS_WITH_WARNINGS)
    
    Spider->>Storage: persist_artifacts(run_id, chunks, manifest)
    Storage->>Storage: Write data/processed/chunks/doc_ar26_v1_chunks.jsonl
    Storage->>Storage: Write data/manifests/runs/{run_id}/run_manifest.json
    Storage-->>Spider: Persistence complete
    Spider-->>Cron: CrawlRunManifest (1 doc ingested, 0 errors)
```

---

## 8. Layer 4 Indexing & Retrieval Flow

Illustrates how canonical chunks are loaded, linearized, indexed, filtered, and scored with dual-threshold calibrated abstention.

```mermaid
flowchart TD
    subgraph IngestionArtifacts["Canonical Chunk Store"]
        J1["chunks.jsonl<br/>(2,682 Canonical Chunks)"]
    end

    subgraph IndexConstruction["Layer 4 Index Build"]
        J1 --> L1["Chunk Loader<br/>(Pydantic Schema Validation)"]
        L1 --> L2{"Duplicate chunk_id?"}
        L2 -- "Yes" --> L_Err["Raise ChunkLoaderError<br/>Zero Tolerance"]
        L2 -- "No" --> T1["Table Linearizer<br/>Row + Header + Unit + Caption"]
        T1 --> T2["Financial Tokenizer<br/>FY 2025-26 • Rupee Symbol • Numbers"]
        T2 --> B1["Inverted Term Index<br/>Term Postings & Counter Frequencies"]
        B1 --> B2["Robertson-Spärck Jones IDF<br/>ln(1 + (N - df + 0.5) / (df + 0.5))"]
    end

    subgraph QueryExecution["Runtime Query Processing"]
        Q["User / Downstream Query"] --> QT["Financial Tokenizer"]
        QT --> Q_Check{"Tokens Empty?"}
        Q_Check -- "Yes" --> Q_Empty["Return is_abstention=True<br/>Reason: Empty Query"]
        Q_Check -- "No" --> Cands["Candidate Doc Fetch<br/>Via Inverted Index"]
        Cands --> F_Check{"Metadata Filters Applied?<br/>(Doc, Section, Page, Has_Table)"}
        F_Check -- "Filtered Out" --> Drop["Discard Candidate"]
        F_Check -- "Passes" --> Score["Okapi BM25 Scoring<br/>b = 0.45 • k1 = 1.2"]
        Score --> Rank["Sort Candidates Descending<br/>Take Top K (e.g. 5)"]
    end

    subgraph AbstentionCheck["Calibrated Dual-Threshold Gate"]
        Rank --> A1{"Top Candidate Score >= 14.5<br/>AND<br/>Term Coverage >= 40%?"}
        A1 -- "No" --> A_Abstain["Return is_abstention=True<br/>Diagnostic Abstention Reason"]
        A1 -- "Yes" --> A_Emit["Emit RetrievalResponse<br/>Ranked RetrievalResultItems<br/>(Provenance + Table Meta + Explanation)"]
    end

    classDef success fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef warn fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    classDef fail fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    class A_Emit success;
    class Q_Empty,A_Abstain warn;
    class L_Err fail;
```

---

## 9. End-to-End Orchestration & Acceptance Gate Sequence

Traces execution of `EndToEndPipelineRunner` during automated scheduling sweeps.

```mermaid
sequenceDiagram
    autonumber
    actor Runner as CLI / Scheduler
    participant Lock as PipelineLock
    participant Core as EndToEndPipelineRunner
    participant Disk as Artifact Store
    participant L4 as Layer4BM25Index
    participant Tests as TestSuite (125 Tests)
    participant Eval as RetrievalBenchmark (20 Qs)
    participant Pub as LatestApprovedPointer

    Runner->>Lock: acquire()
    Lock-->>Runner: Lock Acquired (.pipeline.lock)
    
    Runner->>Core: run()
    Core->>Core: Stage 1: Preflight checks (Python, Source, Dirs)
    Core->>Disk: Stage 2: Check Source SHA-256 (c412ce14...)
    Disk-->>Core: Source unchanged -> Re-use valid run_full_ar26_p1_520_v1
    
    Core->>Disk: Stage 3: Validate canonical chunks (0 duplicate IDs)
    Core->>L4: Stage 4: Construct BM25 Index (k1=1.2, b=0.45)
    L4-->>Core: Index ready (N=2,682, 11,288 terms)
    
    Core->>Tests: Stage 5a: Execute unittest discover
    Tests-->>Core: 125 passed, 0 failures, 0 errors
    
    Core->>Eval: Stage 5b: Evaluate benchmark questions
    Eval-->>Core: Page Recall@1: 88.2%, Recall@5: 100.0%, Abstention: 100%
    
    Core->>Core: Stage 6: Evaluate 6 Acceptance Gates
    Note over Core: All 6 Gates Evaluated: PASSED
    
    Core->>Disk: Stage 7: Emit pipeline_manifest.json & quality_report.md
    Core->>Pub: Update latest_approved_run.json
    Pub-->>Core: Approved Pointer Updated
    
    Core-->>Runner: Exit Code 0 (SUCCESS)
    Runner->>Lock: release()
    Lock-->>Runner: Lock Released (.pipeline.lock deleted)
```

---

## 10. Multi-Report Corpus Ingestion & Strict Identity Gating Lifecycle

Traces the ingestion and verification pipeline implemented in `run_full_corpus_ingestion.py` across `ar15.pdf` through `ar26.pdf`.

```mermaid
flowchart TD
    Start["Candidate PDF (arNN.pdf)"] --> DownloadGate{"Local File Exists & Valid?<br/>(Magic %PDF-, Size > 10KB, pypdf Readable)"}
    
    DownloadGate -- "No" --> StreamDown["Streaming Download with Bounded RAM<br/>Reject HTML Error Pages"]
    StreamDown --> DownloadGate
    
    DownloadGate -- "Yes" --> IdentGate["Strict Identity Verifier<br/>(parse_fiscal_year_interval & front-matter inspection)"]
    
    IdentGate --> CheckIdent{"Identity Status?"}
    
    CheckIdent -- "MISMATCH / OCR Blocked" --> Blocker["Record Blocker in Registry<br/>(e.g., ar20 Prepress Raster Proof: PROCESSING_BLOCKED_REQUIRES_OCR)"]
    
    CheckIdent -- "VERIFIED" --> ReuseCheck{"Existing Valid Run Directory & Manifest?<br/>(Matching Source SHA-256 & Unique Chunks)"}
    
    ReuseCheck -- "Yes" --> FastReuse["Validate Artifact Lineage<br/>Report Truthful None for Skipped Phases<br/>Record reuse_validation_seconds"]
    
    ReuseCheck -- "No" --> FreshExtract["Page-by-Page PDF Extraction<br/>(pdfplumber cache flush + curve-adaptive table search)"]
    FreshExtract --> Chunking["Structure Analysis & Canonical Chunking<br/>(Atomic Manifest Write to tmp -> replace)"]
    
    FastReuse --> SyncReg["Update Source Registry & Summary Record"]
    Chunking --> SyncReg
    Blocker --> SyncReg
    
    SyncReg --> FinalCorpus["Corpus Closeout<br/>11 Verified Reports (22,607 Chunks)<br/>1 Verified Blocker (ar20)"]

    classDef pass fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef warn fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    classDef fail fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    class FinalCorpus,FastReuse pass;
    class Blocker warn;
```

---

## 11. Persistent Semantic Vector Retrieval Lifecycle

Illustrates the vector indexing, incremental caching, and similarity search flow across canonical chunks.

```mermaid
flowchart TD
    subgraph Inputs["Authoritative Inputs"]
        C1["Canonical Chunks Directory<br/>data/output_chunks/run_full_ar*"]
        C2["Corpus Summary Manifest<br/>data/full_corpus_ingestion_summary.json"]
    end

    subgraph Gate["Corpus Eligibility & Integrity Gate"]
        C1 & C2 --> G1["Filter Officially Verified Reports<br/>(11 Verified Reports, 22,607 Chunks)"]
        G1 --> G2{"Is Report Blocked / Unverified?<br/>(e.g., ar20 pending OCR)"}
        G2 -- "Yes" --> G_Skip["Exclude from Index<br/>Record in skipped_reports"]
        G2 -- "No" --> G3["Load CanonicalChunk JSONs<br/>Validate Schema & Unique chunk_id"]
    end

    subgraph Caching["Incremental Embedding Engine"]
        G3 --> K1["Compute content_sha256 for Chunk"]
        K1 --> K2{"Chunk ID & Hash Match<br/>Existing Vector Cache?"}
        K2 -- "Yes (Cache Hit)" --> K3["Reuse Existing Embedding Vector<br/>(Zero recomputation)"]
        K2 -- "No (Cache Miss)" --> K4["Batch Encoder<br/>sentence-transformers/all-MiniLM-L6-v2"]
        K4 --> K5["L2 Vector Normalization<br/>(Unit Euclidean Norm, dim=384)"]
    end

    subgraph Store["Atomic Vector Persistence"]
        K3 & K5 --> P1["Assemble Matrix & Metadata<br/>Write tmp files: _tmp.npy, _tmp.jsonl"]
        P1 --> P2["Compute File SHA-256 Checksums<br/>Write tmp manifest: _tmp.json"]
        P2 --> P3["Atomic Replacement (os.replace)<br/>data/vector_index/embeddings.npy<br/>data/vector_index/chunks_metadata.jsonl<br/>data/vector_index/index_manifest.json"]
    end

    subgraph QueryLayer["Semantic Retrieval Query Path"]
        Q["User Query String"] --> QE["LocalEmbeddingEngine.embed_query()<br/>(L2 Normalized 384-d vector)"]
        QE --> QS["Cosine Similarity via Dot Product<br/>np.dot(embeddings, query_vec)"]
        QS --> QF["Apply Metadata Filter<br/>(fiscal_year, document_id, has_table, page span)"]
        QF --> QC["Dynamic Citation Resolution<br/>(Map to active evidence page span)"]
        QC --> QR["RetrievalResponse<br/>(Top-k results, similarity scores, citations)"]
    end

    classDef pass fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef warn fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    class QR,P3,K3 pass;
    class G_Skip warn;
```

---

## 12. Hybrid BM25 + Semantic Retrieval Architecture (RRF Fusion)

Prompt 3 implements a unified hybrid retrieval layer that queries both the BM25 Okapi lexical index and the dense semantic vector index in parallel, fusing candidate rankings via Reciprocal Rank Fusion (RRF).

### 12.1 End-to-End Hybrid Flow Diagram

```mermaid
flowchart TD
    UQ["User / Benchmark Query"] --> B_Branch["BM25 Lexical Branch<br/>(k1=1.2, b=0.45, candidate depth=50)"]
    UQ --> S_Branch["Semantic Vector Branch<br/>(all-MiniLM-L6-v2, candidate depth=50)"]
    
    subgraph BM25Proc["BM25 Lexical Processing"]
        B_Branch --> B1["Tokenize & Rupee/Number Normalization"]
        B1 --> B2["Inverted Index Scoring & Term Coverage"]
        B2 --> B3["Apply RetrievalFilter (FY, doc_id, has_table, pages)"]
        B3 --> B_Rank["BM25 Ranked Candidates (top-50)<br/>rank_bm25(d), score_bm25(d)"]
    end
    
    subgraph DenseProc["Semantic Vector Processing"]
        S_Branch --> S1["Encode Query via LocalEmbeddingEngine<br/>(384-d normalized vector)"]
        S1 --> S2["Cosine Similarity via Matrix Dot Product<br/>np.dot(embeddings, q_vec)"]
        S2 --> S3["Apply RetrievalFilter (FY, doc_id, has_table, pages)"]
        S3 --> S_Rank["Semantic Ranked Candidates (top-50)<br/>rank_sem(d), sim_sem(d)"]
    end
    
    subgraph Fusion["Reciprocal Rank Fusion Engine (HybridRetriever)"]
        B_Rank & S_Rank --> RRF_Calc["RRF Score Accumulation<br/>RRF(d) = Σ 1 / (k + rank_b(d))<br/>(default k=60)"]
        RRF_Calc --> TieBreak["Deterministic Tie-Breaking Sort<br/>(-rrf_score, min_branch_rank, chunk_id)"]
        TieBreak --> ProvMerge["Provenance & Diagnostics Assembly<br/>- Preserves bm25_score & bm25_rank<br/>- Preserves semantic_score & semantic_rank<br/>- Full physical_pages span & citation label"]
    end
    
    ProvMerge --> TopK["RetrievalResponse<br/>(Fused Top-k results, rank, scores, full citations)"]
    
    classDef pass fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef branch fill:#e2e3e5,stroke:#383d41,stroke-width:1px;
    class TopK pass;
    class B_Rank,S_Rank branch;
```

### 12.2 Mathematical Definition of RRF
For document $d$ and ranking branches $B \subseteq \{\text{bm25}, \text{semantic}\}$:
$$RRF(d) = \sum_{b \in B} \frac{1}{k + \text{rank}_b(d)}$$
Where:
- $k = 60$ (smoothing constant preventing top ranks from dominating).
- $\text{rank}_b(d) \in [1, \text{depth}_b]$ is the 1-based rank of document $d$ in branch $b$.
- If a candidate document is retrieved by only one branch, it receives contribution solely from that branch.
- Raw BM25 scores and cosine similarities are **never** summed directly; only ordinal rank signals are fused.

---

## 13. Local UI, Qwen Inference, and Observability Flow (Prompt 4)

Prompt 4 adds an interactive local diagnostic interface and integrates the existing local Qwen3-4B model running on an NVIDIA GeForce RTX 5060 Laptop GPU.

### 13.1 Query → Retrieval → Local Qwen → Cited Answer Flow

```mermaid
flowchart TD
    User["User / Evaluator<br/>Web Interface (localhost:8501)"] -->|POST /api/query| Srv["UI Server (ThreadingHTTPServer)<br/>ui/server.py"]
    
    subgraph RetLayer["Layer 4 Retrieval Engine"]
        Srv --> MethodGate{"Retrieval Method?"}
        MethodGate -- "BM25" --> BM25_Exec["Layer4BM25Index.search()"]
        MethodGate -- "Semantic" --> Sem_Exec["PersistentVectorIndex.search()"]
        MethodGate -- "Hybrid RRF" --> Hyb_Exec["HybridRetriever.search()"]
        
        Hyb_Exec --> BM25_Branch["BM25 Branch (top-50)"]
        Hyb_Exec --> Sem_Branch["Semantic Branch (top-50)"]
        BM25_Branch & Sem_Branch --> RRF_Fuse["Reciprocal Rank Fusion (k=60)"]
    end
    
    subgraph DecisionGates["Abstention & Error Decision Engine"]
        BM25_Exec & Sem_Exec & RRF_Fuse --> EvalOut{"Status Evaluation"}
        EvalOut -- "Exceptions in All Branches" --> State_Err["status: retrieval_error<br/>(Preserve error trace)"]
        EvalOut -- "Zero candidates match filters" --> State_NoRes["status: no_results<br/>(is_abstention: true)"]
        EvalOut -- "BM25 abstains & Semantic < 0.65" --> State_Abs["status: abstained<br/>(is_abstention: true)"]
        EvalOut -- "Confident candidates found" --> State_Ev["status: evidence_available<br/>(is_abstention: false)"]
    end
    
    State_Err --> Resp_Err["Return Error Diagnostics to UI"]
    State_NoRes & State_Abs --> Qwen_Skip["Skip Generation or Emit Grounded Refusal"]
    
    subgraph QwenInference["Local Qwen3-4B Inference (cuda:0)"]
        State_Ev --> BoundedPrompt["Formulate Bounded Evidence Prompt<br/>- Numbered blocks [1], [2]<br/>- Document ID, FY, Physical Page<br/>- Anti-jailbreak instruction<br/>- Max 16k char context cap"]
        BoundedPrompt --> IPC["Line-delimited JSON IPC via stdin/stdout"]
        IPC --> Worker["Persistent Qwen Worker<br/>pipeline/inference/qwen_worker.py<br/>RTX 5060 Laptop GPU · 8GB VRAM"]
        Worker --> GenAns["Grounded Generation<br/>- Strict evidence constraint<br/>- Distinguish reporting periods<br/>- Bracketed citations [1], [2]"]
    end
    
    subgraph HardwareObs["Hardware Telemetry Engine"]
        NVSMI["nvidia-smi CLI<br/>pipeline/inference/gpu_telemetry.py"] --> LiveMetrics["Live GPU Metrics<br/>- Utilization %<br/>- VRAM Used/Total/Free<br/>- GPU Temperature"]
    end
    
    GenAns & LiveMetrics --> RenderUI["Render Interactive UI Response<br/>1. Grounded Answer with Clickable Citations<br/>2. Retrieved Evidence Cards with Page Spans<br/>3. Branch Diagnostic Badges (BM25, Sem, RRF)<br/>4. Real-time Telemetry Banner"]
    RenderUI --> User
    
    classDef success fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef warn fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
    classDef fail fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    class State_Ev,RenderUI success;
    class State_Abs,State_NoRes warn;
    class State_Err fail;
```

### 13.2 Outcome Status Classification Matrix

| Status Code | Conditions | Abstention Flag | Description |
|---|---|---|---|
| `evidence_available` | Confident candidates retrieved across active branches (BM25 score $\ge 14.5$ or Semantic score $\ge 0.65$). | `false` | Normal operation. Supporting chunks passed to Qwen for cited answering. |
| `abstained` | Candidates evaluated, but BM25 score $< 14.5$, term coverage $< 40\%$, and semantic similarity $< 0.65$. | `true` | Unanswerable or out-of-domain query. Hallucination safely suppressed. |
| `no_results` | Empty query, or no candidates matched the applied metadata filters. | `true` | No chunks available matching the requested report or criteria. |
| `partial_branch_failure` | One branch raised an exception (e.g. disk fault), but remaining branch returned valid candidates. | `false` | Degraded operation. Evidence from healthy branch is returned with failure noted. |
| `retrieval_error` | All active branches encountered runtime exceptions. | `false` | Index or runtime failure. Never classified as legitimate model abstention. |

