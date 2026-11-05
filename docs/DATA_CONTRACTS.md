# Canonical Data Contracts and Provenance Schemas

**Document Identifier**: `HUDCO-DOCPROC-CONTRACTS-2026-V2`  
**Target Path**: `docs/DATA_CONTRACTS.md`  
**Status**: Approved Phase 0B Data Contracts Specification (Extended for Discovery & Versioning)  
**Framework**: Pydantic v2 (Python 3.10+)  
**Scope**: Full formal schema specifications, typing constraints, provenance rules, serialization behaviors, and validation invariants spanning source discovery, acquisition, canonical extraction, and chunking.

---

## 1. Provenance Invariants & Grounding Rules

All entities in the new pipeline must strictly adhere to these immutable provenance invariants:

1. **Entity Identity Hierarchy**:
   - `source_id`: Persistent identifier for an origin location (e.g. `src_hudco_ar26` or `src_pmay_circulars`).
   - `document_id`: Canonical asset family identifier (e.g. `annual_report_ar26`).
   - `version_id`: Immutable content snapshot (e.g. `doc_ar26_v1_c412ce14`).
   - `chunk_id`: Atomic knowledge passage (e.g. `ar26_v1_c412ce14_sec_05_p052_c00`).
2. **Dual-Page Separation**:
   - `physical_page`: Integer $\ge 1$. Mandatory for all PDF sources. Represents the absolute 1-based sheet position in the digital PDF file stream.
   - `printed_page`: Optional string (accommodates Arabic numerals `52` and Roman numerals `iv`, `x`). Represents the human-readable page number visually printed in the report layout.
   - **Invariant**: The system must never overwrite, conflate, or substitute `physical_page` with `printed_page`.
3. **Version-Aware Deterministic Chunk Identifiers**:
   - Every chunk must have a globally unique, deterministic ID matching the regex:
     `^[a-z0-9_]+_v\d+_[a-f0-9]{8}_sec_\d{2}_p\d{3}_c\d{2}$`
   - Formula: `{document_id}_v{version}_{hash8}_{section_id}_p{physical_page:03d}_c{chunk_index:02d}`
   - Re-running chunking on an unchanged document snapshot produces 100% byte-identical IDs. Revisions produce distinct IDs while maintaining lineage.
4. **Traceability to Canonical Content**:
   - Every chunk contains `source_locator`, `content_sha256`, `version_id`, `document_id`, and `section_id`.
   - Modifying chunk text invalidates the `content_sha256`, triggering automatic cache invalidation in downstream retrieval caches.

---

## 2. Complete Pydantic v2 Schema Definitions

Below are the exact Pydantic v2 models that govern the in-memory object graph and on-disk JSON/JSONL artifacts.

```python
"""
Canonical Data Contracts for Clean Document Processing & Chunking Pipeline.
File: pipeline/core/contracts.py
"""

from typing import List, Optional, Dict, Any, Union, Literal
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, HttpUrl, field_validator


# ============================================================================
# 1. ENUMS & CONSTANTS
# ============================================================================

class DocumentFormat(str, Enum):
    PDF = "pdf"
    HTML = "html"
    DOCX = "docx"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    LOCAL_FILESYSTEM = "local_filesystem"
    DIRECT_URL = "direct_url"
    CONFIGURED_WEBSITE = "configured_website"


class DiscoveryMethod(str, Enum):
    LOCAL_SCAN = "local_scan"
    DIRECT_USER_SPECIFIED = "direct_user_specified"
    SITEMAP_XML = "sitemap_xml"
    RSS_FEED = "rss_feed"
    HTML_LISTING = "html_listing"
    PAGINATION_LINK = "pagination_link"


class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    SUCCESS_WITH_WARNINGS = "success_with_warnings"
    PARTIAL_SUCCESS = "partial_success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class IdentityVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"


class WarningCategory(str, Enum):
    BLANK_PAGE = "blank_page"
    SCANNED_PAGE = "scanned_page"
    SHORT_CONTENT = "short_content"
    TABLE_MALFORMED = "table_malformed"
    TOC_UNCERTAIN_OFFSET = "toc_uncertain_offset"
    TOC_FALLBACK_WINDOW = "toc_fallback_window"
    ENCODING_ANOMALY = "encoding_anomaly"
    NETWORK_RETRY = "network_retry"
    RATE_LIMITED = "rate_limited"
    SPA_UNSUPPORTED = "spa_unsupported"
    GENERAL = "general"


# ============================================================================
# 2. SOURCE CONFIGURATION & DISCOVERY CONTRACTS
# ============================================================================

class SourceConfiguration(BaseModel):
    """Configuration for an approved document origin."""
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(..., description="Unique slug for origin e.g. hudco_annual_reports")
    source_type: SourceType = Field(...)
    display_name: str = Field(...)
    base_url: Optional[str] = Field(None, description="Base origin URL for web sources")
    seed_urls: List[str] = Field(default_factory=list, description="Initial discovery URLs")
    local_watch_dir: Optional[str] = Field(None, description="Directory path for local filesystem intake")
    allowed_domains: List[str] = Field(default_factory=list, description="Strict domain allowlist for crawler")
    allowed_path_prefixes: List[str] = Field(default_factory=list, description="Allowed URL path prefixes")
    disallowed_path_patterns: List[str] = Field(default_factory=list, description="Path regex patterns to ignore")
    sitemap_url: Optional[str] = None
    rss_feed_url: Optional[str] = None
    max_crawl_depth: int = Field(default=3, ge=1, le=10)
    max_pages_to_crawl: int = Field(default=50, ge=1, le=500)
    rate_limit_delay_seconds: float = Field(default=1.5, ge=0.5)
    max_download_bytes: int = Field(default=250 * 1024 * 1024, description="Hard cap (250MB)")
    recheck_interval_hours: int = Field(default=24, ge=1)
    is_active: bool = Field(default=True)


class DiscoveredResource(BaseModel):
    """A URL or file path discovered during intake or crawling."""
    resource_url: str = Field(..., description="Normalized canonical URL or local file path")
    source_id: str = Field(...)
    discovery_method: DiscoveryMethod = Field(...)
    parent_page_url: Optional[str] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    anchor_text: Optional[str] = None
    crawl_depth: int = Field(default=0, ge=0)
    inferred_title: Optional[str] = None
    inferred_date: Optional[str] = None


class FetchResult(BaseModel):
    """Result of acquiring a remote or local raw resource."""
    resource_url: str
    http_status: Optional[int] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None
    content_type_header: Optional[str] = None
    detected_mime_type: str = Field(..., description="MIME type verified via magic bytes")
    content_sha256: str = Field(..., min_length=64, max_length=64)
    file_size_bytes: int = Field(..., ge=0)
    spool_file_path: str = Field(..., description="Local path to downloaded raw asset")
    elapsed_seconds: float = Field(..., ge=0.0)
    is_not_modified: bool = Field(default=False, description="True if HTTP 304 occurred")
    error_message: Optional[str] = None


# ============================================================================
# 3. SOURCE REGISTRY & VERSION LINEAGE CONTRACTS
# ============================================================================

class DocumentVersion(BaseModel):
    """Immutable snapshot of a document's content at a point in time."""
    version_id: str = Field(..., description="Format: doc_{name}_v{version}_{hash8}")
    source_id: str = Field(...)
    document_id: str = Field(...)
    version_number: int = Field(..., ge=1)
    content_sha256: str = Field(..., min_length=64, max_length=64)
    file_size_bytes: int = Field(..., ge=0)
    raw_file_path: str = Field(..., description="Persistent path in managed raw storage")
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    is_current: bool = Field(default=True)
    superseded_at: Optional[datetime] = None
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.SUCCESS)
    chunk_count: int = Field(default=0, ge=0)


class SourceRecord(BaseModel):
    """Persistent ledger entry tracking an origin URL or local path over time."""
    source_id: str = Field(..., description="Unique slug for origin")
    canonical_url: str = Field(..., description="Master origin URL or file path")
    source_type: SourceType = Field(...)
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_checked_at: datetime = Field(default_factory=datetime.utcnow)
    last_modified_header: Optional[str] = None
    last_etag_header: Optional[str] = None
    current_version_id: Optional[str] = None
    version_count: int = Field(default=0, ge=0)
    status: str = Field(default="ACTIVE", description="ACTIVE, UPSTREAM_REMOVED, ERROR")
    last_error: Optional[str] = None


# ============================================================================
# 4. SOURCE LOCATORS (PROVENANCE)
# ============================================================================

class PDFSourceLocator(BaseModel):
    """Exact spatial and page locator within a physical PDF document."""
    model_config = ConfigDict(frozen=True)

    physical_page: int = Field(..., ge=1, description="1-based physical sheet index in the PDF stream")
    printed_page: Optional[str] = Field(None, description="Report-printed page label (Arabic or Roman)")
    bbox: Optional[List[float]] = Field(None, description="Normalized bounding box [x0, y0, x1, y1]")


class HTMLSourceLocator(BaseModel):
    """Exact DOM and structural locator within an HTML webpage or FAQ."""
    model_config = ConfigDict(frozen=True)

    source_url: Optional[str] = Field(None, description="Canonical source URL")
    css_selector: Optional[str] = Field(None, description="CSS selector path")
    heading_hierarchy: List[str] = Field(default_factory=list, description="Ancestor heading breadcrumbs (h1 > h2)")


SourceLocator = Union[PDFSourceLocator, HTMLSourceLocator]


# ============================================================================
# 5. STRUCTURED TABLES & CONTENT BLOCKS
# ============================================================================

class StructuredTable(BaseModel):
    """High-fidelity tabular matrix representation."""
    model_config = ConfigDict(frozen=True)

    table_id: str = Field(..., description="Local unique table identifier (e.g. p052_tbl01)")
    caption: Optional[str] = Field(None, description="Extracted table title or caption")
    unit_of_measure: Optional[str] = Field(None, description="Currency or unit e.g. Rs. in Crore")
    headers: List[str] = Field(..., description="Consolidated column header labels")
    rows: List[List[str]] = Field(..., description="2D cell matrix of body rows")
    markdown_representation: str = Field(..., description="Clean GitHub-Flavored Markdown table")
    is_malformed: bool = Field(default=False, description="Flag set if row/column mismatch occurred")
    row_count: int = Field(..., ge=0)
    col_count: int = Field(..., ge=0)
    detected_fiscal_years: List[str] = Field(default_factory=list, description="All financial years present in column headers or rows")



class ContentBlock(BaseModel):
    """Atomic content unit extracted from source documents."""
    block_id: str = Field(..., description="Unique block ID within document")
    block_type: BlockType = Field(...)
    text_content: str = Field(..., description="Raw or normalized text representation")
    locator: SourceLocator = Field(..., description="Physical provenance locator")
    heading_level: Optional[int] = Field(None, ge=1, le=6, description="1-6 for headings")
    table_data: Optional[StructuredTable] = Field(None, description="Populated only if block_type == TABLE")
    is_boilerplate: bool = Field(default=False, description="Flag for detected header/footer noise")


# ============================================================================
# 6. CANONICAL SECTIONS & CANONICAL DOCUMENT
# ============================================================================

class CanonicalSection(BaseModel):
    """Logical document partition (e.g. Board's Report, Financial Statements)."""
    section_id: str = Field(..., pattern=r"^sec_\d{2}$", description="Normalized section ID: sec_01, sec_02")
    title: str = Field(..., min_length=1, description="Official section title")
    level: int = Field(default=1, ge=1, le=3, description="Nesting level")
    physical_page_start: int = Field(..., ge=1)
    physical_page_end: int = Field(..., ge=1)
    printed_page_start: Optional[str] = None
    printed_page_end: Optional[str] = None
    segmentation_method: str = Field(..., description="native_outline, toc_page_discovery, heading_heuristic, fallback")
    confidence: Literal["high", "medium", "low"] = Field(...)
    blocks: List[ContentBlock] = Field(default_factory=list, description="Ordered child content blocks")

    @field_validator("physical_page_end")
    @classmethod
    def validate_page_order(cls, v: int, info) -> int:
        start = info.data.get("physical_page_start")
        if start is not None and v < start:
            raise ValueError(f"physical_page_end ({v}) cannot be less than physical_page_start ({start})")
        return v


class DocumentMetadata(BaseModel):
    """Master document catalogue metadata."""
    document_id: str = Field(..., description="Canonical ID: {doc_type}_{name}")
    source_id: str = Field(..., description="Reference to parent SourceRecord")
    version_id: str = Field(..., description="Reference to DocumentVersion")
    version_number: int = Field(default=1, ge=1)
    source_filename: str = Field(...)
    source_url: Optional[str] = None
    document_format: DocumentFormat = Field(...)
    content_sha256: str = Field(..., min_length=64, max_length=64)
    file_size_bytes: int = Field(..., ge=0)
    total_physical_pages: Optional[int] = Field(None, ge=1)
    discovery_method: DiscoveryMethod = Field(default=DiscoveryMethod.DIRECT_USER_SPECIFIED)
    title_hint: Optional[str] = None
    fiscal_year_hint: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QualityWarning(BaseModel):
    """Audit warning recorded during extraction, structural analysis, or chunking."""
    category: WarningCategory = Field(...)
    message: str = Field(...)
    physical_page: Optional[int] = None
    section_id: Optional[str] = None
    block_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CanonicalDocument(BaseModel):
    """Format-agnostic in-memory representation of an ingested document."""
    metadata: DocumentMetadata
    sections: List[CanonicalSection] = Field(default_factory=list)
    warnings: List[QualityWarning] = Field(default_factory=list)
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.SUCCESS)


# ============================================================================
# 7. CANONICAL KNOWLEDGE CHUNKS (OUTPUT ARTIFACTS)
# ============================================================================

class CanonicalChunk(BaseModel):
    """
    Atomic, section-aware knowledge chunk for indexing and retrieval.
    Persisted to .jsonl artifacts.
    """
    chunk_id: str = Field(..., description="Format: doc_v{ver}_{hash8}_sec_{sec}_p{page}_c{idx}")
    document_id: str = Field(...)
    version_id: str = Field(...)
    source_id: str = Field(...)
    source_filename: str = Field(...)
    section_id: str = Field(...)
    physical_page: int = Field(..., ge=1, description="Primary starting physical PDF page")
    physical_page_end: Optional[int] = Field(None, ge=1, description="Ending physical PDF page for multi-page chunks")
    physical_pages: List[int] = Field(default_factory=list, description="All physical pages contributing content to this chunk")
    printed_page: Optional[str] = Field(None, description="Primary starting printed page label")
    printed_page_end: Optional[str] = Field(None, description="Ending printed page label for multi-page chunks")
    printed_pages: List[str] = Field(default_factory=list, description="All printed page labels contributing content to this chunk")
    chunk_index_in_page: int = Field(..., ge=0)
    has_table: bool = Field(default=False)
    char_count: int = Field(..., ge=0)
    token_estimate: int = Field(..., ge=0)
    content: str = Field(..., min_length=1, description="Primary textual and/or markdown content")
    content_sha256: str = Field(..., min_length=64, max_length=64)
    structured_tables: List[StructuredTable] = Field(default_factory=list)
    ancestor_headings: List[str] = Field(default_factory=list)
    is_stale: bool = Field(default=False, description="Set to True when superseded by a new version")
    fiscal_year: Optional[str] = Field(None, description="Verified report fiscal year e.g. '2025-26'")
    reporting_period: Optional[str] = Field(None, description="Specific reporting period if granularly identified")
    report_title: Optional[str] = Field(None, description="Official report title e.g. 'HUDCO 54th Annual Report 2023-24'")



# ============================================================================
# 8. AUDIT MANIFESTS (CRAWL RUN & PROCESSING RUN)
# ============================================================================

class CrawlRunManifest(BaseModel):
    """Execution record for an automated website crawl or discovery sweep."""
    crawl_id: str
    source_id: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    seed_urls_visited: int
    pages_crawled: int
    documents_discovered: int
    downloads_attempted: int
    downloads_succeeded: int
    downloads_skipped_unchanged: int
    downloads_failed: int
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class QualityMetrics(BaseModel):
    """Quantitative quality indicators for an extraction run."""
    total_extracted_pages: int
    empty_page_count: int
    suspiciously_short_page_count: int
    total_sections: int
    total_blocks: int
    total_tables: int
    malformed_table_count: int
    total_chunks_emitted: int
    avg_chunk_char_count: float
    min_chunk_char_count: int
    max_chunk_char_count: int


class ProcessingRunManifest(BaseModel):
    """Exhaustive, machine-readable audit manifest for a pipeline execution."""
    run_id: str = Field(...)
    source_id: str = Field(...)
    document_id: str = Field(...)
    version_id: str = Field(...)
    status: ProcessingStatus = Field(...)
    started_at: datetime = Field(...)
    completed_at: datetime = Field(...)
    duration_seconds: float = Field(...)
    source_file_path: str = Field(...)
    content_sha256: str = Field(...)
    document_format: DocumentFormat = Field(...)
    structural_method: str = Field(...)
    structural_confidence: str = Field(...)
    metrics: QualityMetrics
    warnings: List[QualityWarning] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    output_artifacts: Dict[str, str] = Field(default_factory=dict)
```

---

## 3. Metadata Rules: Mandatory vs. Optional vs. Never-Fabricated

| Field | Nature | Invariant / Fabrication Rule |
|---|---|---|
| `physical_page` | **Mandatory** | Real 1-based page index. Must never be missing or fabricated for PDF documents. |
| `printed_page` | **Optional** | Extracted from running headers/footers. If page has no printed number, must remain `None`. **Never fabricate.** |
| `content_sha256` | **Mandatory** | Computed directly from bytes or normalized text. |
| `version_id` | **Mandatory** | Computed deterministically from `{document_id}_v{version}_{hash8}`. |
| `chunk_id` | **Mandatory** | Guaranteed unique across versions and corpus. |
| `unit_of_measure` | **Optional** | Captured from table headers/captions. If absent, must remain `None`. **Never assume default currency.** |
| `http_etag` / `http_last_modified`| **Optional** | Captured verbatim from HTTP response. If absent, must remain `None`. |

---

## 4. Layer 4 Retrieval Service Contracts

Defined in `pipeline/retrieval/contracts.py`:

```python
class RetrievalFilter(BaseModel):
    """Metadata filter applied to the retrieval index."""
    document_id: Optional[str] = None
    version_id: Optional[str] = None
    section_id: Optional[str] = None
    section_title_contains: Optional[str] = None
    min_physical_page: Optional[int] = Field(None, ge=1)
    max_physical_page: Optional[int] = Field(None, ge=1)
    has_table: Optional[bool] = None
    include_stale: bool = False

    @classmethod
    def validate_filter(cls, filter_obj: "RetrievalFilter") -> None:
        if filter_obj.min_physical_page is not None and filter_obj.max_physical_page is not None:
            if filter_obj.min_physical_page > filter_obj.max_physical_page:
                raise ValueError("min_physical_page cannot exceed max_physical_page")


class TableMetadata(BaseModel):
    """Summarized metadata for structured tables contained in a retrieved chunk."""
    table_id: str
    caption: Optional[str] = None
    unit_of_measure: Optional[str] = None
    headers: List[str] = Field(default_factory=list)
    row_count: int
    col_count: int


class RetrievalResultItem(BaseModel):
    """Ranked candidate chunk returned by the Layer 4 retrieval engine."""
    rank: int = Field(..., ge=1)
    chunk_id: str
    score: float
    matched_terms: List[str] = Field(default_factory=list)
    term_coverage: float = Field(0.0)
    explanation: str = ""
    document_id: str
    version_id: str
    source_id: str
    source_filename: str
    section_id: str
    section_title: str
    physical_page: int
    printed_page: Optional[str] = None
    has_table: bool
    table_metadata: Optional[List[TableMetadata]] = None
    content: str
    content_sha256: str


class RetrievalResponse(BaseModel):
    """Complete response envelope from Layer 4 retrieval service."""
    query: str
    total_candidates_scored: int
    total_results: int
    results: List[RetrievalResultItem]
    applied_filters: Optional[RetrievalFilter] = None
    is_abstention: bool = False
    abstention_threshold: float = 0.0
    abstention_reason: Optional[str] = None
```

---

## 5. End-to-End Orchestrator Manifest Contracts

Emitted by `pipeline/runner.py`:

```python
class SourceDocumentMetadata(BaseModel):
    filename: str
    sha256: str
    size_bytes: int


class TestSummaryRecord(BaseModel):
    total_run: int
    failures: int
    errors: int
    passed: bool


class DatasetStatisticsRecord(BaseModel):
    total_chunks: int
    total_physical_pages: int
    has_table_chunks: int


class PipelineManifest(BaseModel):
    """Execution record for an end-to-end pipeline run."""
    pipeline_version: str
    execution_timestamp: datetime
    duration_seconds: float
    status: ProcessingStatus
    source_document: SourceDocumentMetadata
    run_directory: str
    artifacts_reused: bool
    dataset_statistics: DatasetStatisticsRecord
    test_summary: TestSummaryRecord
    retrieval_metrics: Dict[str, float]
    acceptance_gates: Dict[str, bool]
    stage_timings_seconds: Dict[str, float]


class LatestApprovedRunPointer(BaseModel):
    """Pointer file published at data/output_chunks/latest_approved_run.json."""
    approved_at: datetime
    approved_run_dir: str
    source_filename: str
    source_sha256: str
    total_chunks: int
    metrics: Dict[str, float]
```


