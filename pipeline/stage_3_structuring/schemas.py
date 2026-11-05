"""
Pydantic Schemas for the Unified Knowledge Schema.
Enforces strict validation, typing, and provenance metadata across all extracted chunks.
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl

class SourceMetadata(BaseModel):
    """Source provenance and authority information."""
    title: str = Field(..., description="Document or publication title")
    document_type: str = Field(..., description="e.g. annual_report, circular, faq, web_page")
    url: Optional[str] = Field(None, description="Direct URL to source document")
    fiscal_year: Optional[str] = Field(None, description="Fiscal year e.g. 2024-25")
    page_start: Optional[int] = Field(None, description="Starting page in PDF")
    page_end: Optional[int] = Field(None, description="Ending page in PDF")
    authority_tier: int = Field(default=1, ge=1, le=3, description="1=Official AR/Gov circular, 2=Website, 3=FAQ")
    is_latest: bool = Field(default=True, description="Flag indicating if this is latest version")

class ClassificationMetadata(BaseModel):
    """Domain taxonomy and intent categorization."""
    department: str = Field(..., description="Responsible HUDCO department")
    section_title: str = Field(..., description="Logical heading or section title")
    primary_intent: str = Field(
        ...,
        description="Core intent e.g. FINANCIAL_RESULTS, RETAIL_HOUSING_LOAN, PMAY_SCHEMES, INFRA_PROJECT_FINANCING, BONDS_AND_BORROWINGS, LOCATE_OFFICE"
    )
    secondary_intents: List[str] = Field(default_factory=list, description="Associated secondary intents")
    entities_covered: List[str] = Field(default_factory=list, description="Extracted key financial/scheme entities")

class TableItem(BaseModel):
    """Structured markdown table container."""
    table_id: str
    title: Optional[str] = None
    markdown: str

class ContentPayload(BaseModel):
    """Extracted text, summaries, and Markdown tables."""
    summary: str = Field(..., description="Concise synopsis of the chunk content")
    text_content: str = Field(..., description="Normalized clean textual content")
    tables: List[TableItem] = Field(default_factory=list, description="Aligned Markdown tables")

class ChunkMetadata(BaseModel):
    """Technical and auditing metadata."""
    char_count: int
    token_estimate: int
    sha256: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(default=1)

class UnifiedChunk(BaseModel):
    """The Master Atomic Knowledge Chunk Schema for HUDCO RAG."""
    chunk_id: str = Field(..., description="Unique deterministic chunk identifier")
    document_id: str = Field(..., description="Unique parent document identifier")
    source: SourceMetadata
    classification: ClassificationMetadata
    content: ContentPayload
    metadata: ChunkMetadata
