"""
Regression tests for reused-run metrics and performance measurement integrity.
File: tests/test_reused_run_metrics.py
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import settings
from pipeline.core.contracts import ProcessingStatus
from scripts.run_full_corpus_ingestion import process_report


class TestReusedRunMetrics(unittest.TestCase):
    """
    Validates that:
    1. Reused runs do not fabricate execution timings (e.g., hardcoded 304.66s or 0.0s).
    2. Peak memory for reused runs is reported as None/unavailable rather than fabricated.
    3. Elapsed wall clock time for reused runs reflects only the validation/loading time.
    4. Fresh runs properly measure and isolate separate phase timings and memory profiling.
    """

    def test_reused_run_does_not_fabricate_metrics(self):
        """
        Verify that when a report's artifacts are reused, historical execution metrics
        (extraction_seconds, structural_analysis_seconds, chunking_seconds, peak_memory_mb)
        are explicitly None or marked unavailable, not hardcoded numbers or misleading zeros.
        """
        target = {
            "slug": "ar26",
            "filename": "ar26.pdf",
            "doc_id": "doc_ar26",
            "src_id": "hudco_annual_report_ar26",
            "fiscal_year": "2025-26",
            "title": "HUDCO 56th Annual Report 2025-26",
            "url": "https://www.hudco.org.in/writereaddata/ar26.pdf",
        }

        mock_downloader = MagicMock()
        mock_registry = MagicMock()

        # Execute process_report on the existing ar26 valid run
        result = process_report(target, mock_downloader, mock_registry, force_reprocess=False)

        self.assertEqual(result["status"], "SUCCESS_REUSED")
        self.assertTrue(result["artifacts_reused"])

        # Metric assertions: must not be hardcoded legacy values (304.66s, 2421.56MB)
        self.assertIsNone(
            result["extraction_seconds"],
            "extraction_seconds should be None for reused runs as extraction was skipped.",
        )
        self.assertIsNone(
            result["structural_analysis_seconds"],
            "structural_analysis_seconds should be None for reused runs.",
        )
        self.assertIsNone(
            result["chunking_seconds"],
            "chunking_seconds should be None for reused runs.",
        )
        self.assertIsNone(
            result["peak_memory_mb"],
            "peak_memory_mb should be None for reused runs since processing memory was not incurred.",
        )

        # Total wall clock seconds for reuse check should be measured and strictly positive (> 0.0s)
        self.assertGreater(
            result["total_wall_clock_seconds"],
            0.0,
            "Total wall clock should be measured for the reuse check itself and not be 0.0s",
        )
        self.assertLess(
            result["total_wall_clock_seconds"],
            10.0,
            "Reused check should complete quickly without reprocessing",
        )

        # Chunk count should be accurately reflected
        self.assertEqual(result["chunk_count"], 2682)
        self.assertEqual(result["total_pages"], 520)

    def test_profiling_resources_cleanup_on_exception(self):
        """
        Verify that tracemalloc profiling is stopped even when an exception occurs during processing.
        """
        import tracemalloc
        target = {
            "slug": "ar99_test",
            "filename": "ar99_test.pdf",
            "doc_id": "doc_ar99",
            "src_id": "hudco_annual_report_ar99",
            "fiscal_year": "2099-00",
            "title": "HUDCO Test Report 2099-00",
            "url": "https://www.hudco.org.in/writereaddata/ar99.pdf",
        }
        mock_downloader = MagicMock()
        mock_downloader.download_file.return_value = {
            "file_path": str(settings.ANNUAL_REPORTS_DIR / "ar15.pdf"),
            "size_bytes": 1024 * 1024,
            "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        }
        mock_registry = MagicMock()

        with patch("scripts.run_full_corpus_ingestion.PDFDocumentAdapter.extract_file", side_effect=RuntimeError("Simulated extraction error")):
            with self.assertRaises(RuntimeError):
                process_report(target, mock_downloader, mock_registry, force_reprocess=True)

        # Tracemalloc should not be left tracing
        self.assertFalse(tracemalloc.is_tracing(), "tracemalloc must be stopped even after an exception")


if __name__ == "__main__":
    unittest.main()

