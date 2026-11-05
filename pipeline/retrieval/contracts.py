"""
Layer 4 Retrieval Contracts and Data Schemas.
File: pipeline/retrieval/contracts.py

Defines the formal request, filter, and response contracts for the Layer 4
indexing and retrieval service.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RetrievalFilter(BaseModel):
    """
    Metadata filter applied to the retrieval index.
    Filters can constrain search to specific documents, sections, page windows,
    or content types (e.g. tabular vs narrative).
    """
    document_id: Optional[str] = Field(None, description="Exact document family identifier (e.g. doc_ar26)")
    version_id: Optional[str] = Field(None, description="Exact document version (e.g. v1)")
    section_id: Optional[str] = Field(None, description="Exact canonical section ID (e.g. sec_01)")
    section_title_contains: Optional[str] = Field(None, description="Sub-string match on section title")
    min_physical_page: Optional[int] = Field(None, ge=1, description="Minimum physical PDF page (inclusive)")
    max_physical_page: Optional[int] = Field(None, ge=1, description="Maximum physical PDF page (inclusive)")
    has_table: Optional[bool] = Field(None, description="If True, only return chunks with tables; if False, only narrative")
    include_stale: bool = Field(False, description="Whether to include chunks marked as superseded (is_stale=True)")
    fiscal_year: Optional[str] = Field(None, description="Exact report fiscal year e.g. '2025-26'")
    fiscal_years: Optional[List[str]] = Field(None, description="Set of allowed report fiscal years")


    @classmethod
    def validate_filter(cls, filter_obj: "RetrievalFilter") -> None:
        if filter_obj.min_physical_page is not None and filter_obj.max_physical_page is not None:
            if filter_obj.min_physical_page > filter_obj.max_physical_page:
                raise ValueError(
                    f"Invalid page range: min_physical_page ({filter_obj.min_physical_page}) "
                    f"cannot exceed max_physical_page ({filter_obj.max_physical_page})"
                )


class TableMetadata(BaseModel):
    """Summarized metadata for structured tables contained in a retrieved chunk."""
    table_id: str
    caption: Optional[str] = None
    unit_of_measure: Optional[str] = None
    headers: List[str] = Field(default_factory=list)
    row_count: int
    col_count: int


class RetrievalResultItem(BaseModel):
    """
    Ranked candidate chunk returned by the Layer 4 retrieval engine.
    Carries complete provenance, scoring diagnostics, and table metadata.
    """
    rank: int = Field(..., ge=1, description="1-based candidate rank")
    chunk_id: str = Field(..., description="Deterministic canonical chunk identifier")
    score: float = Field(..., description="BM25 lexical relevance score")
    matched_terms: List[str] = Field(default_factory=list, description="Query terms contributing to score")
    term_coverage: float = Field(0.0, description="Ratio of unique query terms matched by this chunk")
    explanation: str = Field("", description="Per-term score contribution diagnostic")
    document_id: str
    version_id: str
    source_id: str
    source_filename: str
    section_id: str
    section_title: str
    ancestor_headings: List[str] = Field(default_factory=list, description="Section ancestor hierarchy")
    physical_page: int
    physical_page_end: Optional[int] = None
    physical_pages: List[int] = Field(default_factory=list)
    printed_page: Optional[str] = None
    printed_page_end: Optional[str] = None
    printed_pages: List[str] = Field(default_factory=list)
    has_table: bool
    table_metadata: Optional[List[TableMetadata]] = None
    content: str = Field(..., description="Raw textual and/or markdown chunk content")
    content_sha256: str = Field(..., description="Content hash for verification and caching")
    fiscal_year: Optional[str] = Field(None, description="Report fiscal year (e.g. '2025-26')")
    reporting_period: Optional[str] = Field(None, description="Specific reporting period if granularly detected")
    citation_page: Optional[int] = Field(None, description="Exact or targeted evidence physical page")
    citation_pages: List[int] = Field(default_factory=list, description="All contributing physical pages")
    citation_label: str = Field("", description="Human-readable citation (e.g. 'Page 8' or 'Pages 5-16')")
    retrieval_method: str = Field("bm25", description="'bm25', 'semantic', or 'hybrid_rrf'")
    bm25_score: Optional[float] = Field(None, description="Raw BM25 lexical score if retrieved by BM25 branch")
    bm25_rank: Optional[int] = Field(None, description="1-based candidate rank in BM25 branch")
    semantic_score: Optional[float] = Field(None, description="Cosine similarity score if retrieved by semantic branch")
    semantic_rank: Optional[int] = Field(None, description="1-based candidate rank in semantic branch")
    rrf_score: Optional[float] = Field(None, description="Reciprocal Rank Fusion fused score")


class RetrievalResponse(BaseModel):
    """
    Complete response envelope from Layer 4 retrieval service.
    """
    query: str
    total_candidates_scored: int
    total_results: int
    results: List[RetrievalResultItem]
    applied_filters: Optional[RetrievalFilter] = None
    is_abstention: bool = Field(False, description="True if top candidate score or coverage is below confidence threshold")
    abstention_threshold: float = Field(0.0, description="Calibrated score threshold applied")
    abstention_reason: Optional[str] = Field(None, description="Diagnostic explanation for abstention")
    retrieval_method: str = Field("bm25", description="'bm25', 'semantic', or 'hybrid_rrf'")
    status: str = Field("evidence_available", description="Outcome status: 'evidence_available', 'abstained', 'no_results', 'retrieval_error', 'partial_branch_failure'")
    rrf_k: Optional[int] = Field(None, description="RRF constant k applied if hybrid retrieval was used")
    branch_candidate_counts: Dict[str, int] = Field(default_factory=dict, description="Counts of candidates scored/retrieved per branch")


