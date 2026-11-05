"""
Unit Tests for Source Registry and Version Lineage.
File: tests/test_source_registry.py
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline.core.source_registry import SourceRegistry


class TestSourceRegistry(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.registry_file = self.test_dir / "test_source_registry.json"
        self.registry = SourceRegistry(registry_path=self.registry_file)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_registry_creation_and_reload(self):
        """Verify registry saves and reloads accurately."""
        self.registry.register_source(
            source_id="hudco_test_ar",
            document_id="doc_test_ar",
            source_url="https://example.com/ar.pdf",
            report_title="HUDCO Test Report 2024",
            report_fiscal_year="2023-24",
            download_status="NOT_DOWNLOADED",
            verification_status="URL_VERIFIED_CONTENT_UNVERIFIED",
            content_sha256="abcdef1234567890" * 4,
        )
        self.assertTrue(self.registry_file.exists())

        # Reload in new instance
        reloaded = SourceRegistry(registry_path=self.registry_file)
        source = reloaded.get_source("hudco_test_ar")
        self.assertIsNotNone(source)
        self.assertEqual(source["report_fiscal_year"], "2023-24")
        self.assertEqual(source["report_title"], "HUDCO Test Report 2024")

    def test_atomic_write_safety(self):
        """Verify atomic replacement via .tmp prevents corruption."""
        self.registry.register_source(
            source_id="src_atomic",
            document_id="doc_atomic",
            source_url="https://example.com/atomic.pdf",
        )
        self.assertTrue(self.registry_file.exists())
        # Verify no orphaned .tmp file
        tmp_file = self.registry_file.with_suffix(".tmp")
        self.assertFalse(tmp_file.exists())

    def test_duplicate_registration_idempotence(self):
        """Verify registering existing source updates fields without deleting prior metadata."""
        self.registry.register_source(
            source_id="src_dup",
            document_id="doc_dup",
            source_url="https://example.com/dup.pdf",
            report_title="Original Title",
            report_fiscal_year="2022-23",
        )
        # Re-register with new status
        self.registry.register_source(
            source_id="src_dup",
            document_id="doc_dup",
            source_url="https://example.com/dup.pdf",
            download_status="DOWNLOADED_LOCAL",
        )
        source = self.registry.get_source("src_dup")
        self.assertEqual(source["report_title"], "Original Title")
        self.assertEqual(source["report_fiscal_year"], "2022-23")
        self.assertEqual(source["download_status"], "DOWNLOADED_LOCAL")

    def test_failed_request_recording_without_deletion(self):
        """Verify failed HTTP request is logged without removing previously ingested source."""
        self.registry.register_source(
            source_id="src_fail",
            document_id="doc_fail",
            source_url="https://example.com/fail.pdf",
            report_fiscal_year="2021-22",
            download_status="DOWNLOADED_LOCAL",
            verification_status="OFFICIALLY_VERIFIED",
        )
        # Record failure
        self.registry.register_failed_request(
            source_id="src_fail",
            error_message="HTTP 503 Service Unavailable",
            http_status=503,
        )
        source = self.registry.get_source("src_fail")
        self.assertIsNotNone(source)
        self.assertEqual(source["http_status"], 503)
        self.assertIn("HTTP 503 Service Unavailable", source["warnings"][-1])
        # Prior metadata and download status remain intact!
        self.assertEqual(source["report_fiscal_year"], "2021-22")
        self.assertEqual(source["download_status"], "DOWNLOADED_LOCAL")

    def test_content_hash_change_and_version_lineage(self):
        """Verify content change triggers version lineage preservation."""
        hash_v1 = "1111111111111111" * 4
        hash_v2 = "2222222222222222" * 4

        self.registry.register_source(
            source_id="src_versioned",
            document_id="doc_versioned",
            source_url="https://example.com/doc.pdf",
            content_sha256=hash_v1,
            file_path="data/raw/doc_v1.pdf",
        )
        source = self.registry.get_source("src_versioned")
        self.assertEqual(source["version_count"], 1)

        # Update with new content hash
        self.registry.register_source(
            source_id="src_versioned",
            document_id="doc_versioned",
            source_url="https://example.com/doc.pdf",
            content_sha256=hash_v2,
            file_path="data/raw/doc_v2.pdf",
        )
        source = self.registry.get_source("src_versioned")
        self.assertEqual(source["content_sha256"], hash_v2)
        self.assertEqual(source["version_count"], 2)

        lineage = self.registry.get_version_lineage("src_versioned")
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0]["superseded_sha256"], hash_v1)
        self.assertEqual(lineage[0]["superseded_file_path"], "data/raw/doc_v1.pdf")

    def test_missing_or_unknown_fiscal_year(self):
        """Verify sources without confirmed fiscal years store None explicitly."""
        self.registry.register_source(
            source_id="src_unknown_fy",
            document_id="doc_unknown",
            source_url="https://example.com/unknown.pdf",
        )
        source = self.registry.get_source("src_unknown_fy")
        self.assertIsNone(source["report_fiscal_year"])


if __name__ == "__main__":
    unittest.main()
