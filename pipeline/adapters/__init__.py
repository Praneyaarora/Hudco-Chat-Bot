"""
Document Extraction Adapters Module.
Exposes BaseDocumentAdapter, PDFDocumentAdapter, and HTMLDocumentAdapter.
"""

from .base import BaseDocumentAdapter, RawPageRecord, RawExtractionPayload
from .pdf_adapter import PDFDocumentAdapter
from .html_adapter import HTMLDocumentAdapter

__all__ = [
    "BaseDocumentAdapter",
    "RawPageRecord",
    "RawExtractionPayload",
    "PDFDocumentAdapter",
    "HTMLDocumentAdapter",
]
