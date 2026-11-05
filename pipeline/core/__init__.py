"""
Pipeline Core Module.
Exposes canonical data contracts, models, and shared types.
"""

from .contracts import (
    DocumentFormat,
    SourceType,
    DiscoveryMethod,
    ProcessingStatus,
    BlockType,
    WarningCategory,
    SourceConfiguration,
    DiscoveredResource,
    FetchResult,
    DocumentVersion,
    SourceRecord,
    PDFSourceLocator,
    HTMLSourceLocator,
    SourceLocator,
    StructuredTable,
    ContentBlock,
    CanonicalSection,
    DocumentMetadata,
    QualityWarning,
    CanonicalDocument,
    CanonicalChunk,
    CrawlRunManifest,
    QualityMetrics,
    ProcessingRunManifest,
)
from .structural_analyzer import StructuralAnalyzer
from .chunker import HierarchicalChunker
from .pipeline_runner import run_phase2_pipeline

__all__ = [
    "DocumentFormat",
    "SourceType",
    "DiscoveryMethod",
    "ProcessingStatus",
    "BlockType",
    "WarningCategory",
    "SourceConfiguration",
    "DiscoveredResource",
    "FetchResult",
    "DocumentVersion",
    "SourceRecord",
    "PDFSourceLocator",
    "HTMLSourceLocator",
    "SourceLocator",
    "StructuredTable",
    "ContentBlock",
    "CanonicalSection",
    "DocumentMetadata",
    "QualityWarning",
    "CanonicalDocument",
    "CanonicalChunk",
    "CrawlRunManifest",
    "QualityMetrics",
    "ProcessingRunManifest",
    "StructuralAnalyzer",
    "HierarchicalChunker",
    "run_phase2_pipeline",
]
