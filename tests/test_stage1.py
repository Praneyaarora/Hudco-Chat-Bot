"""
Unit Tests for Stage 1 Ingestion, Deduplication, Fingerprinting, and Segmentation.
Covers Tests A through L.
"""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pypdf import PdfWriter

from pipeline.stage_1_ingestion.downloader import DocumentDownloader
from pipeline.stage_1_ingestion.fingerprint import DocumentFingerprinter
from pipeline.stage_1_ingestion.segmenter import PDFSegmenter


def create_dummy_pdf(file_path: Path, num_pages: int = 10, title: str = "Test PDF") -> None:
    """Helper to generate a minimal valid multi-page PDF."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    with open(file_path, "wb") as f:
        writer.write(f)


class TestStage1Ingestion(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.raw_dir = self.test_dir / "raw"
        self.registry_file = self.test_dir / "registry.json"
        self.downloader = DocumentDownloader(
            target_dir=self.raw_dir,
            registry_path=self.registry_file,
            max_retries=1
        )
        self.segmenter = PDFSegmenter(output_dir=self.test_dir / "sections")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_a_streaming_download_success(self):
        """TEST A: Streaming downloader succeeds and creates expected file."""
        sample_pdf = self.test_dir / "source.pdf"
        create_dummy_pdf(sample_pdf, 5, "Sample Report")

        with open(sample_pdf, "rb") as f:
            pdf_bytes = f.read()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.iter_content.return_value = [pdf_bytes[:1024], pdf_bytes[1024:]]
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.get", return_value=mock_resp):
            res = self.downloader.download_file(
                url="https://example.com/test.pdf",
                destination_filename="test.pdf",
                subdirectory="annual_reports"
            )

        self.assertEqual(res["status"], "DOWNLOADED")
        self.assertFalse(res["is_duplicate"])
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertEqual(res["size_bytes"], len(pdf_bytes))

    def test_b_sha256_matches_content(self):
        """TEST B: SHA-256 matches expected content."""
        sample_pdf = self.test_dir / "source.pdf"
        create_dummy_pdf(sample_pdf, 3, "SHA Test")
        expected_sha = DocumentDownloader.compute_sha256_of_file(sample_pdf)

        res = self.downloader.ingest_local_file(sample_pdf)
        self.assertEqual(res["sha256"], expected_sha)

    def test_c_duplicate_detection(self):
        """TEST C: Same content with different filename is detected as duplicate."""
        sample_pdf = self.test_dir / "source.pdf"
        create_dummy_pdf(sample_pdf, 4, "Duplicate Test")

        with open(sample_pdf, "rb") as f:
            pdf_bytes = f.read()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.iter_content.return_value = [pdf_bytes]
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.get", return_value=mock_resp):
            # First download
            res1 = self.downloader.download_file("https://example.com/file1.pdf", "doc_v1.pdf")
            self.assertEqual(res1["status"], "DOWNLOADED")

            # Second download of identical content under different name
            res2 = self.downloader.download_file("https://example.com/file2.pdf", "doc_v2.pdf")
            self.assertEqual(res2["status"], "DUPLICATE")
            self.assertTrue(res2["is_duplicate"])

    def test_d_collision_protection_different_content(self):
        """TEST D: Same filename with different content is preserved without silent overwrite."""
        file1 = self.test_dir / "f1.pdf"
        create_dummy_pdf(file1, 2, "Doc 1")
        with open(file1, "rb") as f:
            b1 = f.read()

        file2 = self.test_dir / "f2.pdf"
        create_dummy_pdf(file2, 6, "Doc 2 Different")
        with open(file2, "rb") as f:
            b2 = f.read()

        mock1 = MagicMock()
        mock1.status_code = 200
        mock1.headers = {"Content-Type": "application/pdf"}
        mock1.iter_content.return_value = [b1]
        mock1.raise_for_status.return_value = None

        mock2 = MagicMock()
        mock2.status_code = 200
        mock2.headers = {"Content-Type": "application/pdf"}
        mock2.iter_content.return_value = [b2]
        mock2.raise_for_status.return_value = None

        with patch("requests.Session.get", side_effect=[mock1, mock2]):
            res1 = self.downloader.download_file("https://example.com/ar.pdf", "ar.pdf")
            res2 = self.downloader.download_file("https://example.com/new_ar.pdf", "ar.pdf")

        # Both files must exist on disk with different filenames
        p1 = Path(res1["file_path"])
        p2 = Path(res2["file_path"])
        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())
        self.assertNotEqual(p1.name, p2.name)

    def test_e_invalid_magic_bytes_rejected(self):
        """TEST E: Invalid/HTML response is rejected by magic byte check."""
        html_bytes = b"<!DOCTYPE html><html><body>Error 404</body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.iter_content.return_value = [html_bytes]
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.get", return_value=mock_resp):
            with self.assertRaises(RuntimeError):
                self.downloader.download_file("https://example.com/fake.pdf", "fake.pdf")

    def test_f_incomplete_download_cleanup(self):
        """TEST F: Incomplete download removes temporary .part file."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.iter_content.side_effect = ConnectionResetError("Connection broke")
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.get", return_value=mock_resp):
            with self.assertRaises(RuntimeError):
                self.downloader.download_file("https://example.com/broken.pdf", "broken.pdf")

        part_files = list(self.raw_dir.glob("*.part"))
        self.assertEqual(len(part_files), 0)

    def test_g_outline_extraction_normalized(self):
        """TEST G: Native outline extraction returns normalized records."""
        pdf_path = self.test_dir / "outline.pdf"
        create_dummy_pdf(pdf_path, 10, "Outline PDF")
        res = self.segmenter.inspect_structure(pdf_path)
        self.assertIn("outline_present", res)
        self.assertIn("raw_outline_entries", res)
        self.assertEqual(res["total_pages"], 10)

    def test_h_invalid_outline_quality_gate(self):
        """TEST H: Low-quality or single-digit outline fails quality gate."""
        junk_outline = [
            {"title": "1", "physical_page": 1},
            {"title": "2", "physical_page": 2},
            {"title": "Final_Final", "physical_page": 3}
        ]
        is_valid, quality, issues = self.segmenter.validate_outline_quality(junk_outline, total_pages=100)
        self.assertFalse(is_valid)
        self.assertIn(quality, ["INVALID", "WEAK"])
        self.assertTrue(len(issues) > 0)

    def test_i_printed_physical_page_mapping_separated(self):
        """TEST I: Printed and physical pages are represented separately."""
        pdf_path = self.test_dir / "sample.pdf"
        create_dummy_pdf(pdf_path, 50, "Annual Report")

        parsed_entries = [
            {"title": "Reference Information", "printed_page": 18},
            {"title": "Directors' Report", "printed_page": 32},
            {"title": "Financial Statements", "printed_page": 210}
        ]

        mapped, method, conf, diag = self.segmenter.map_printed_to_physical_pages(
            pdf_path=pdf_path,
            parsed_entries=parsed_entries,
            total_pages=500
        )

        self.assertEqual(len(mapped), 3)
        for item in mapped:
            self.assertIn("printed_page_start", item)
            self.assertIn("physical_page_start", item)

    def test_j_section_ranges_non_overlapping(self):
        """TEST J: Section ranges are non-overlapping and ordered."""
        mapped_entries = [
            {"section_id": "sec_01", "title": "Section A", "physical_page_start": 5, "printed_page_start": 1},
            {"section_id": "sec_02", "title": "Section B", "physical_page_start": 15, "printed_page_start": 11},
            {"section_id": "sec_03", "title": "Section C", "physical_page_start": 30, "printed_page_start": 26},
        ]
        plan, warnings = self.segmenter.build_section_plan(
            mapped_entries=mapped_entries,
            total_pages=50,
            segmentation_method="toc_page_discovery",
            confidence="high"
        )

        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]["physical_page_start"], 5)
        self.assertEqual(plan[0]["physical_page_end"], 14)
        self.assertEqual(plan[1]["physical_page_start"], 15)
        self.assertEqual(plan[1]["physical_page_end"], 29)
        self.assertEqual(plan[2]["physical_page_start"], 30)
        self.assertEqual(plan[2]["physical_page_end"], 50)

    def test_k_fixed_window_fallback_labeling(self):
        """TEST K: Fixed-window fallback is explicitly classified."""
        plan, warnings = self.segmenter.build_section_plan(
            mapped_entries=[],
            total_pages=60,
            segmentation_method="fixed_window_fallback",
            confidence="low"
        )
        self.assertEqual(len(plan), 3)  # 25, 25, 10
        self.assertEqual(plan[0]["segmentation_method"], "fixed_window_fallback")
        self.assertEqual(plan[0]["confidence"], "low")
        self.assertIn("Logical_Window", plan[0]["title"])

    def test_l_pdf_splitting_creates_files(self):
        """TEST L: PDF splitting generates physical section files on disk."""
        pdf_path = self.test_dir / "split_test.pdf"
        create_dummy_pdf(pdf_path, 30, "Split Test")

        plan = [
            {"section_id": "sec_01", "title": "Chapter 1", "safe_title": "Chapter_1", "physical_page_start": 1, "physical_page_end": 10, "printed_page_start": 1, "printed_page_end": 10, "segmentation_method": "toc", "confidence": "high"},
            {"section_id": "sec_02", "title": "Chapter 2", "safe_title": "Chapter_2", "physical_page_start": 11, "physical_page_end": 30, "printed_page_start": 11, "printed_page_end": 30, "segmentation_method": "toc", "confidence": "high"},
        ]

        results = self.segmenter.split_pdf(pdf_path, "TEST_DOC", plan)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(Path(r["output_path"]).exists())
            self.assertGreater(r["size_bytes"], 0)

    def test_m_validate_local_pdf(self):
        """TEST M: Local PDF validation checks magic bytes, size, HTML content, and structure."""
        # 1. Missing file
        is_val, msg = DocumentDownloader.validate_local_pdf(self.test_dir / "non_existent.pdf")
        self.assertFalse(is_val)
        self.assertIn("does not exist", msg)

        # 2. Too small
        small_file = self.test_dir / "tiny.pdf"
        small_file.write_bytes(b"%PDF-1.4 dummy short")
        is_val, msg = DocumentDownloader.validate_local_pdf(small_file)
        self.assertFalse(is_val)
        self.assertIn("suspiciously small", msg)

        # 3. HTML error page
        html_file = self.test_dir / "error.pdf"
        html_file.write_bytes(b"<!DOCTYPE html><html><body>Error 404 Not Found</body></html>" + b" " * 12000)
        is_val, msg = DocumentDownloader.validate_local_pdf(html_file)
        self.assertFalse(is_val)
        self.assertIn("HTML error page", msg)

        # 4. Valid PDF with > 10KB size
        valid_pdf = self.test_dir / "valid.pdf"
        create_dummy_pdf(valid_pdf, num_pages=150, title="Valid Test Report")
        is_val, msg = DocumentDownloader.validate_local_pdf(valid_pdf)
        self.assertTrue(is_val, f"Validation failed unexpectedly: {msg}")
        self.assertIn("Valid PDF", msg)


if __name__ == "__main__":
    unittest.main()
