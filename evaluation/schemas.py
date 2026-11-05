"""
Pydantic schemas and data contracts for the HUDCO Evaluation Harness.
Strictly separates physical PDF pages, verified printed pages, and evaluation metrics.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class PageExtractionRecord(BaseModel):
    """Raw page-level extraction record preserving page mapping and quality flags."""
    document_id: str
    source_filename: str
    section_id: str
    section_title: str
    physical_page: int = Field(..., ge=1, description="1-based physical PDF page index")
    printed_page: Optional[int] = Field(None, ge=1, description="Verified printed report page label")
    char_count: int
    is_empty: bool
    is_suspiciously_short: bool
    has_table: bool
    text: str
    warnings: List[str] = Field(default_factory=list)

class EvaluationChunk(BaseModel):
    """Atomic, section-aware chunk with deterministic ID and provenance metadata."""
    chunk_id: str = Field(..., description="Deterministic ID: doc_sec_pXXX_cXX")
    document_id: str
    source_filename: str
    section_id: str
    section_title: str
    physical_page: int = Field(..., ge=1, description="1-based physical PDF page index")
    printed_page: Optional[int] = Field(None, ge=1, description="Verified printed report page label")
    chunk_index: int = Field(..., ge=0, description="0-based index within the page")
    char_count: int
    token_estimate: int
    has_table: bool
    content: str
    sha256: str

class EvaluationQuestion(BaseModel):
    """Benchmark question definition with ground truth and verification metadata."""
    question_id: str = Field(..., description="Unique question identifier e.g. Q01")
    question: str
    category: str = Field(
        ...,
        description="direct_fact, numeric_table, multi_passage, multi_section, ambiguous, unanswerable, definition"
    )
    expected_answer: Optional[str] = None
    expected_source_document: str = "HUDCO_AR_2025_26_c412ce14"
    expected_pdf_pages: List[int] = Field(default_factory=list, description="Verified physical PDF pages")
    expected_printed_pages: List[int] = Field(default_factory=list, description="Verified printed report pages")
    expected_relevant_chunk_ids: List[str] = Field(default_factory=list, description="Verified relevant chunk IDs")
    answerability: str = Field(
        default="answerable",
        description="answerable, unanswerable, needs_review"
    )
    evaluation_notes: str = ""

class RetrievalResultItem(BaseModel):
    """Ranked retrieval candidate returned by BM25."""
    rank: int = Field(..., ge=1)
    chunk_id: str
    score: float
    matched_terms: List[str] = Field(default_factory=list)
    explanation: str = ""
    document_id: str
    section_id: str
    section_title: str
    physical_page: int
    printed_page: Optional[int] = None
    has_table: bool
    text: str

class QuestionRetrievalEvaluation(BaseModel):
    """Evaluation result for a single question."""
    question_id: str
    question: str
    category: str
    answerability: str
    has_ground_truth: bool
    expected_pdf_pages: List[int] = Field(default_factory=list)
    expected_chunk_ids: List[str] = Field(default_factory=list)
    retrieved_items: List[RetrievalResultItem] = Field(default_factory=list)
    hit_at_1: Optional[bool] = None
    hit_at_3: Optional[bool] = None
    hit_at_5: Optional[bool] = None
    reciprocal_rank: Optional[float] = None
    zero_retrieval: bool = False
    generated_answer: Optional[str] = None
    cited_chunk_ids: List[str] = Field(default_factory=list)
    citation_validity: Optional[Dict[str, Any]] = None
    abstention_correct: Optional[bool] = None
    notes: List[str] = Field(default_factory=list)

class EvaluationRunReport(BaseModel):
    """Complete evaluation run record with aggregate metrics and configuration."""
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    mode: str = "retrieval_only"
    total_questions: int
    answerable_questions: int
    unanswerable_questions: int
    eligible_evaluation_questions: int
    recall_at_1: Optional[float] = None
    recall_at_3: Optional[float] = None
    recall_at_5: Optional[float] = None
    mrr: Optional[float] = None
    zero_retrieval_count: int = 0
    questions: List[QuestionRetrievalEvaluation] = Field(default_factory=list)
    corpus_stats: Dict[str, Any] = Field(default_factory=dict)
