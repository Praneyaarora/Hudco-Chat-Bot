"""
Abstract Base Document Adapter Interface.
File: pipeline/adapters/base.py

Defines the contract for all format-specific document extractors (PDF, HTML, and future formats).
Encapsulates format-specific parsing details and emits standardized RawExtractionPayload objects.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from pipeline.core.contracts import (
    DocumentFormat,
    ContentBlock,
    StructuredTable,
    QualityWarning,
    PDFSourceLocator,
    HTMLSourceLocator,
)


class RawPageRecord(BaseModel):
    """Page-level extraction record preserving physical page index and extraction quality."""
    physical_page: int = Field(..., ge=1, description="1-based physical page or partition index")
    printed_page: Optional[str] = Field(None, description="Report-printed page label (Arabic or Roman)")
    text: str = Field(default="", description="Normalized raw text extracted from page")
    char_count: int = Field(default=0, ge=0)
    is_empty: bool = Field(default=False)
    is_suspiciously_short: bool = Field(default=False, description="True if text < 100 characters")
    is_scanned: bool = Field(default=False, description="True if page appears to be a raster image")
    tables: List[StructuredTable] = Field(default_factory=list)
    blocks: List[ContentBlock] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    extraction_error: Optional[str] = None


class RawExtractionPayload(BaseModel):
    """Complete document extraction container returned by an adapter."""
    source_filename: str
    document_format: DocumentFormat
    total_physical_pages: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    outline_entries: List[Dict[str, Any]] = Field(default_factory=list, description="Native bookmarks or headings")
    pages: List[RawPageRecord] = Field(default_factory=list)
    warnings: List[QualityWarning] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    @property
    def is_clean_success(self) -> bool:
        """True if extraction encountered zero errors and zero page failures."""
        return len(self.errors) == 0 and all(p.extraction_error is None for p in self.pages)


class BaseDocumentAdapter(ABC):
    """Abstract interface for all document format extraction adapters."""

    @abstractmethod
    def can_handle(self, mime_type: str, file_path: Optional[Path] = None) -> bool:
        """Returns True if this adapter supports the given MIME type or file extension."""
        pass

    @abstractmethod
    def extract_file(
        self,
        file_path: Path,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        """Extracts document content from a local filesystem path."""
        pass

    @abstractmethod
    def extract_bytes(
        self,
        data: bytes,
        filename: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        """Extracts document content directly from in-memory bytes."""
        pass
