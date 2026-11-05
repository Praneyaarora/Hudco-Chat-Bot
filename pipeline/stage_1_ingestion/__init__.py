"""
Stage 1: Ingestion & Document Segmentation Pipeline.
Handles document acquisition, SHA-256 deduplication, deterministic fingerprinting,
TOC discovery, printed-to-physical page mapping, and non-overlapping PDF segmentation.
"""
from .downloader import DocumentDownloader
from .segmenter import PDFSegmenter
from .fingerprint import DocumentFingerprinter
from .run_stage1 import run_stage_1

__all__ = [
    "DocumentDownloader",
    "PDFSegmenter",
    "DocumentFingerprinter",
    "run_stage_1",
]
