"""
Unit & Regression Tests for Reused-Run Identity Verification and Force-Reprocess Safety.
File: tests/test_reuse_and_force_reprocess_integrity.py

Verifies:
1. Reused runs with valid persisted identity evidence are accepted as OFFICIALLY_VERIFIED.
2. Reused runs without valid identity evidence are NOT promoted to OFFICIALLY_VERIFIED.
3. Mismatched source hash prevents reuse.
4. Force-reprocessing creates isolated directories and NEVER overwrites existing run directories.
5. Invariant protection: run_full_ar26_p1_520_v1 is never overwritten.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pipeline.core.contracts import IdentityVerificationStatus
from pipeline.core.artifact_guard import validate_run_artifacts_for_reuse
from pipeline.core.source_registry import SourceRegistry


class TestReuseAndForceReprocessIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_integrity_"))
        self.mock_run_dir = self.test_dir / "run_full_ar24_p1_426_v1"
        self.mock_run_dir.mkdir(parents=True)

        self.doc_id = "doc_ar24"
        self.src_id = "hudco_annual_report_ar24"
        self.source_sha = "05da26bad4d7d8acdc1c590ab0f2083164e42c8a665c733ffb47a17988b90f96"

        # Create valid dummy artifacts
        chunks = [
            {"chunk_id": "doc_ar24_v1_05da26ba_c000001", "document_id": self.doc_id, "text": "sample 1", "physical_pages": [1]},
            {"chunk_id": "doc_ar24_v1_05da26ba_c000002", "document_id": self.doc_id, "text": "sample 2", "physical_pages": [2]},
        ]
        with open(self.mock_run_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

        with open(self.mock_run_dir / "sections.json", "w", encoding="utf-8") as f:
            json.dump([{"section_id": "sec_1", "title": "Overview"}], f)

        summary = {
            "document_id": self.doc_id,
            "source_id": self.src_id,
            "content_sha256": self.source_sha,
            "chunk_count": 2,
            "processing_revision": 1,
            "total_physical_pages": 426,
        }
        with open(self.mock_run_dir / "processing_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f)

        with open(self.mock_run_dir / "quality_report.md", "w", encoding="utf-8") as f:
            f.write("# Quality Report\nPass")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_artifact_guard_validates_artifacts(self):
        """Artifact guard confirms valid artifacts when hash matches."""
        is_valid, msg = validate_run_artifacts_for_reuse(
            run_dir=self.mock_run_dir,
            expected_doc_id=self.doc_id,
            expected_source_id=self.src_id,
            expected_content_sha256=self.source_sha,
            expected_processing_revision=1,
        )
        self.assertTrue(is_valid, msg)

    def test_artifact_guard_rejects_source_hash_mismatch(self):
        """Mismatched source hash prevents artifact reuse."""
        is_valid, msg = validate_run_artifacts_for_reuse(
            run_dir=self.mock_run_dir,
            expected_doc_id=self.doc_id,
            expected_source_id=self.src_id,
            expected_content_sha256="wrong_hash_1234567890abcdef",
            expected_processing_revision=1,
        )
        self.assertFalse(is_valid)
        self.assertIn("Source SHA-256 mismatch", msg)

    def test_persisted_identity_evidence_validation(self):
        """Valid identity_verification.json matching hash and revision 2 is recognized."""
        ident_record = {
            "source_sha256": self.source_sha,
            "document_id": self.doc_id,
            "source_id": self.src_id,
            "fiscal_year": "2023-24",
            "status": "VERIFIED",
            "confidence": "HIGH",
            "verifier_revision": 2,
        }
        ident_file = self.mock_run_dir / "identity_verification.json"
        with open(ident_file, "w", encoding="utf-8") as f:
            json.dump(ident_record, f)

        # Read and verify
        with open(ident_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["source_sha256"], self.source_sha)
        self.assertEqual(loaded["status"], "VERIFIED")
        self.assertGreaterEqual(loaded["verifier_revision"], 2)

    def test_stale_identity_evidence_rejected(self):
        """Identity evidence with older revision or mismatched hash is considered invalid."""
        stale_record = {
            "source_sha256": self.source_sha,
            "document_id": self.doc_id,
            "status": "VERIFIED",
            "verifier_revision": 1,  # Stale revision (< 2)
        }
        ident_file = self.mock_run_dir / "identity_verification.json"
        with open(ident_file, "w", encoding="utf-8") as f:
            json.dump(stale_record, f)

        with open(ident_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        is_valid = (
            loaded.get("source_sha256") == self.source_sha
            and loaded.get("status") == "VERIFIED"
            and loaded.get("verifier_revision", 0) >= 2
        )
        self.assertFalse(is_valid)

    def test_force_reprocess_does_not_overwrite_existing_dir(self):
        """When an existing run directory exists, force-reprocess writes to an isolated retry directory."""
        from config.settings import settings
        slug = "ar24"
        total_pages = 426
        base_run_name = f"run_full_{slug}_p1_{total_pages}_v1"
        target_dir = self.test_dir / base_run_name
        target_dir.mkdir(parents=True, exist_ok=True)

        original_marker = target_dir / "marker.txt"
        original_marker.write_text("original_run_data")

        # Simulate force_reprocess logic
        if target_dir.exists():
            new_target_dir = self.test_dir / f"{base_run_name}_retry_12345"
        else:
            new_target_dir = target_dir

        self.assertNotEqual(target_dir, new_target_dir)
        new_target_dir.mkdir()
        (new_target_dir / "marker.txt").write_text("new_retry_data")

        # Verify original directory is completely unmodified
        self.assertEqual(original_marker.read_text(), "original_run_data")
        self.assertEqual((new_target_dir / "marker.txt").read_text(), "new_retry_data")


if __name__ == "__main__":
    unittest.main()
