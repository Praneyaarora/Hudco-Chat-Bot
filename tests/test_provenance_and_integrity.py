"""
Regression Tests for Chunk Provenance, Multi-Page Citation, TOC Offset Calibration,
Registry Idempotency, and Artifact Reuse Guards.
File: tests/test_provenance_and_integrity.py
"""

import json
import tempfile
import shutil
import unittest
from pathlib import Path

from pipeline.core.contracts import (
    CanonicalChunk,
    CanonicalSection,
    ContentBlock,
    BlockType,
    PDFSourceLocator,
    DocumentFormat,
    DocumentMetadata,
    CanonicalDocument,
    QualityWarning,
    WarningCategory,
)
from pipeline.adapters.base import RawExtractionPayload, RawPageRecord
from pipeline.adapters.pdf_adapter import detect_printed_page_label
from pipeline.core.chunker import HierarchicalChunker
from pipeline.core.structural_analyzer import StructuralAnalyzer
from pipeline.core.source_registry import SourceRegistry
from pipeline.core.artifact_guard import validate_run_artifacts_for_reuse
from pipeline.retrieval.contracts import RetrievalFilter
from pipeline.retrieval.bm25 import Layer4BM25Index


class TestChunkProvenanceAndIntegrity(unittest.TestCase):
    def test_multi_page_chunk_provenance(self):
        """Verifies that chunks spanning multiple physical pages capture complete provenance."""
        # Create blocks from pages 5, 6, 7, 8
        blocks = [
            ContentBlock(
                block_id="b1",
                block_type=BlockType.PARAGRAPH,
                text_content="Page 5 photo caption and introductory remark.",
                locator=PDFSourceLocator(physical_page=5, printed_page="3"),
            ),
            ContentBlock(
                block_id="b2",
                block_type=BlockType.PARAGRAPH,
                text_content="Page 6 corporate leadership photo and note.",
                locator=PDFSourceLocator(physical_page=6, printed_page="4"),
            ),
            ContentBlock(
                block_id="b3",
                block_type=BlockType.PARAGRAPH,
                text_content="Page 7 award ceremony caption.",
                locator=PDFSourceLocator(physical_page=7, printed_page="5"),
            ),
            ContentBlock(
                block_id="b4",
                block_type=BlockType.PARAGRAPH,
                text_content="Page 8 detailed narrative about HUDCO operations and initiatives in FY 2023-24.",
                locator=PDFSourceLocator(physical_page=8, printed_page="6"),
            ),
        ]

        section = CanonicalSection(
            section_id="sec_01",
            title="Overview",
            level=1,
            physical_page_start=5,
            physical_page_end=8,
            printed_page_start="3",
            printed_page_end="6",
            segmentation_method="test",
            confidence="high",
            blocks=blocks,
        )

        doc = CanonicalDocument(
            metadata=DocumentMetadata(
                document_id="doc_ar24",
                source_id="hudco_annual_report_ar24",
                version_id="doc_ar24_v1_test",
                version_number=1,
                source_filename="ar24.pdf",
                source_url="https://hudco.org.in/ar24.pdf",
                document_format=DocumentFormat.PDF,
                content_sha256="a" * 64,
                file_size_bytes=1000,
                fiscal_year="2023-24",
            ),
            sections=[section],
        )

        chunker = HierarchicalChunker(target_chunk_size=1500, max_chunk_size=2500, chunk_overlap=0)
        chunks, warnings = chunker.chunk_document(doc)

        self.assertEqual(len(chunks), 1)
        c = chunks[0]
        # Start page preserved for chunk ID stability and sorting
        self.assertEqual(c.physical_page, 5)
        self.assertEqual(c.physical_page_end, 8)
        self.assertEqual(c.physical_pages, [5, 6, 7, 8])
        self.assertEqual(c.printed_page, "3")
        self.assertEqual(c.printed_page_end, "6")
        self.assertEqual(c.printed_pages, ["3", "4", "5", "6"])
        self.assertIn("Page 8 detailed narrative", c.content)

        # Retrieval filter: multi-page awareness
        index = Layer4BM25Index()
        index.build_index(chunks)

        # Filter strictly for physical page 8 must match this chunk!
        res_p8 = index.retrieve("narrative", filters=RetrievalFilter(min_physical_page=8, max_physical_page=8), score_threshold=0.0)
        self.assertEqual(len(res_p8.results), 1)
        self.assertEqual(res_p8.results[0].chunk_id, c.chunk_id)
        self.assertEqual(res_p8.results[0].physical_pages, [5, 6, 7, 8])

        # Filter for page 9 must exclude it
        res_p9 = index.retrieve("narrative", filters=RetrievalFilter(min_physical_page=9, max_physical_page=9), score_threshold=0.0)
        self.assertTrue(res_p9.is_abstention or len(res_p9.results) == 0)

    def test_single_page_chunk_provenance(self):
        """Verifies single-page chunk contracts maintain physical_page_end as None."""
        block = ContentBlock(
            block_id="b1",
            block_type=BlockType.PARAGRAPH,
            text_content="Single page narrative.",
            locator=PDFSourceLocator(physical_page=12, printed_page="10"),
        )
        section = CanonicalSection(
            section_id="sec_01",
            title="Single",
            level=1,
            physical_page_start=12,
            physical_page_end=12,
            segmentation_method="test",
            confidence="high",
            blocks=[block],
        )
        doc = CanonicalDocument(
            metadata=DocumentMetadata(
                document_id="doc_ar24",
                source_id="hudco_annual_report_ar24",
                version_id="doc_ar24_v1_test",
                version_number=1,
                source_filename="ar24.pdf",
                source_url="https://hudco.org.in/ar24.pdf",
                document_format=DocumentFormat.PDF,
                content_sha256="b" * 64,
                file_size_bytes=1000,
            ),
            sections=[section],
        )
        chunker = HierarchicalChunker(target_chunk_size=1500, max_chunk_size=2500)
        chunks, _ = chunker.chunk_document(doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].physical_page, 12)
        self.assertIsNone(chunks[0].physical_page_end)
        self.assertEqual(chunks[0].physical_pages, [12])

    def test_running_header_year_regex_rejection(self):
        """Verifies that hyphenated year ranges are not falsely extracted as page numbers."""
        # False positive candidate: "ANNUAL REPORT 2023-24"
        self.assertIsNone(detect_printed_page_label("ANNUAL REPORT 2023-24"))
        self.assertIsNone(detect_printed_page_label("54th Annual Report 2023-24\nDirectors Report"))

        # Valid running headers must still succeed
        self.assertEqual(detect_printed_page_label("52 | ANNUAL REPORT 2023-24"), "52")
        self.assertEqual(detect_printed_page_label("ANNUAL REPORT 2023-24 | Page 104"), "104")
        self.assertEqual(detect_printed_page_label("Directors Report | 88"), "88")

    def test_toc_offset_calibration(self):
        """Verifies automated TOC page offset calibration when physical = printed + offset."""
        analyzer = StructuralAnalyzer()
        clean_matches = [
            ("Reference Information", "17"),
            ("Board of Directors", "18"),
            ("Chairman's Message", "22"),
            ("Notice of AGM", "27"),
            ("Directors' Report", "43"),
        ]
        # Build mock payload where offset is +2 (e.g. printed 17 -> physical 19)
        pages = []
        for p in range(1, 55):
            text = f"Page {p} content."
            if p == 19:
                text = "Reference Information about HUDCO head office and auditors."
            elif p == 20:
                text = "Board of Directors details and profile."
            elif p == 24:
                text = "Chairman's Message to stakeholders."
            elif p == 29:
                text = "Notice of AGM for 54th annual general meeting."
            elif p == 45:
                text = "Directors' Report on operational highlights."
            pages.append(RawPageRecord(physical_page=p, text=text, blocks=[]))

        payload = RawExtractionPayload(
            source_filename="test.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=55,
            pages=pages,
        )

        offset, matched = analyzer._calibrate_toc_offset(clean_matches, payload)
        self.assertEqual(offset, 2)
        self.assertEqual(len(matched), 5)
        self.assertEqual(matched[0], ("Reference Information", 19, "17"))
        self.assertEqual(matched[1], ("Board of Directors", 20, "18"))
        self.assertEqual(matched[2], ("Chairman's Message", 24, "22"))

    def test_source_registry_idempotency_and_lineage(self):
        """Verifies idempotent sync, status preservation, and version lineage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg_path = Path(tmpdir) / "source_registry.json"
            reg_path.write_text(json.dumps({"sources": {}, "version_lineage": {}, "schema_version": "2.0"}), encoding="utf-8")
            reg = SourceRegistry(registry_path=reg_path)

            # 1. Register a source with local download
            reg.register_source(
                source_id="hudco_annual_report_ar24",
                document_id="doc_ar24",
                source_url="https://hudco.org.in/ar24.pdf",
                report_title="HUDCO 54th Annual Report 2023-24",
                download_status="DOWNLOADED_LOCAL",
                verification_status="OFFICIALLY_VERIFIED",
                content_sha256="hash_v1_" + "0" * 56,
                file_path="data/raw/annual_reports/ar24.pdf",
            )
            self.assertEqual(len(reg.data["sources"]), 1)
            self.assertEqual(reg.get_source("hudco_annual_report_ar24")["download_status"], "DOWNLOADED_LOCAL")

            # 2. Re-register via inventory sync with default NOT_DOWNLOADED
            # Must NOT downgrade status or erase file_path!
            inv_path = Path(tmpdir) / "inventory.json"
            with open(inv_path, "w", encoding="utf-8") as f:
                json.dump([
                    {
                        "source_id": "hudco_annual_report_ar24",
                        "document_id": "doc_ar24",
                        "source_url": "https://hudco.org.in/ar24.pdf",
                        "download_status": "NOT_DOWNLOADED",
                        "verification_status": "UNVERIFIED",
                    }
                ], f)

            reg.sync_from_inventory(inv_path)
            rec = reg.get_source("hudco_annual_report_ar24")
            self.assertEqual(rec["download_status"], "DOWNLOADED_LOCAL")
            self.assertEqual(rec["verification_status"], "OFFICIALLY_VERIFIED")
            self.assertEqual(rec["file_path"], "data/raw/annual_reports/ar24.pdf")

            # 3. Hash change must record version lineage
            new_hash = "hash_v2_" + "1" * 56
            reg.register_source(
                source_id="hudco_annual_report_ar24",
                document_id="doc_ar24",
                source_url="https://hudco.org.in/ar24.pdf",
                content_sha256=new_hash,
            )
            lineage = reg.get_version_lineage("hudco_annual_report_ar24")
            self.assertEqual(len(lineage), 1)
            self.assertEqual(lineage[0]["superseded_sha256"], "hash_v1_" + "0" * 56)

    def test_artifact_guard_validation(self):
        """Verifies that artifact_guard accepts valid runs and rejects corrupt/mismatched runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run_test"
            run_dir.mkdir()

            valid_sha = "c" * 64
            # 1. Missing files
            ok, msg = validate_run_artifacts_for_reuse(run_dir, "doc_test", "hudco_test", valid_sha)
            self.assertFalse(ok)
            self.assertIn("missing", msg)

            # Create dummy files
            chunks_path = run_dir / "chunks.jsonl"
            sections_path = run_dir / "sections.json"
            summary_path = run_dir / "processing_summary.json"
            quality_path = run_dir / "quality_report.md"

            quality_path.write_text("# Quality Report", encoding="utf-8")
            sections_path.write_text(json.dumps([{"section_id": "sec_01", "title": "Sec"}]), encoding="utf-8")
            summary_path.write_text(json.dumps({
                "document_id": "doc_test",
                "content_sha256": valid_sha,
                "processing_revision": 1,
                "chunk_count": 1,
            }), encoding="utf-8")
            chunks_path.write_text(json.dumps({
                "chunk_id": "doc_test_v1_c1",
                "document_id": "doc_test",
                "section_id": "sec_01",
                "physical_page": 1,
            }) + "\n", encoding="utf-8")

            # Should now pass
            ok, msg = validate_run_artifacts_for_reuse(run_dir, "doc_test", "hudco_test", valid_sha)
            self.assertTrue(ok, msg)

            # Hash mismatch must fail
            ok_bad_hash, msg_bad_hash = validate_run_artifacts_for_reuse(run_dir, "doc_test", "hudco_test", "d" * 64)
            self.assertFalse(ok_bad_hash)
            self.assertIn("mismatch", msg_bad_hash)


if __name__ == "__main__":
    unittest.main()
