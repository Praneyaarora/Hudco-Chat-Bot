"""
Unit Tests for Stage B Metadata Compatibility, Deserialization, and Filtering.
File: tests/test_stage_b_metadata_compatibility.py
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline.core.contracts import (
    CanonicalChunk,
    StructuredTable,
    PDFSourceLocator,
    ProcessingStatus,
)
from pipeline.retrieval.contracts import RetrievalFilter
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.loader import load_canonical_chunks


class TestStageBMetadataCompatibility(unittest.TestCase):
    def test_legacy_chunk_jsonl_deserialization(self):
        """Verify older chunks without fiscal_year/reporting_period load safely with None defaults."""
        legacy_chunk_dict = {
            "chunk_id": "doc_ar26_v1_c412ce14_sec_01_p1_c0_r1",
            "document_id": "doc_ar26",
            "version_id": "doc_ar26_v1_c412ce14",
            "source_id": "hudco_annual_report_ar26",
            "source_filename": "ar26.pdf",
            "section_id": "sec_01",
            "section_title": "Corporate Overview",
            "physical_page": 1,
            "printed_page": "1",
            "chunk_index_in_page": 0,
            "has_table": False,
            "char_count": 120,
            "token_estimate": 30,
            "content": "Housing and Urban Development Corporation Limited legacy chunk content.",
            "content_sha256": "abcdef1234567890" * 4,
            "structured_tables": [],
            "ancestor_headings": ["Corporate Overview"],
            "source_block_ids": ["blk_01"],
            "warnings": [],
            "is_stale": False,
            "processing_revision": 1,
            # Note: fiscal_year, reporting_period, report_title OMITTED!
        }
        chunk = CanonicalChunk.model_validate(legacy_chunk_dict)
        self.assertIsNone(chunk.fiscal_year)
        self.assertIsNone(chunk.reporting_period)
        self.assertIsNone(chunk.report_title)
        self.assertEqual(chunk.chunk_id, "doc_ar26_v1_c412ce14_sec_01_p1_c0_r1")

    def test_new_metadata_serialization_roundtrip(self):
        """Verify serialization and deserialization of new metadata fields."""
        chunk = CanonicalChunk(
            chunk_id="doc_ar24_v1_05da26ba_sec_02_p5_c0_r1",
            document_id="doc_ar24",
            version_id="doc_ar24_v1_05da26ba",
            source_id="hudco_annual_report_ar24",
            source_filename="ar24.pdf",
            section_id="sec_02",
            section_title="Board of Directors",
            physical_page=5,
            printed_page="3",
            chunk_index_in_page=0,
            has_table=False,
            char_count=150,
            token_estimate=38,
            content="54th Annual Report FY 2023-24 text.",
            content_sha256="1234567890abcdef" * 4,
            structured_tables=[],
            ancestor_headings=["Contents"],
            source_block_ids=["blk_02"],
            warnings=[],
            is_stale=False,
            processing_revision=1,
            fiscal_year="2023-24",
            reporting_period="FY 2023-24",
            report_title="HUDCO 54th Annual Report 2023-24",
        )
        json_data = json.loads(chunk.model_dump_json())
        self.assertEqual(json_data["fiscal_year"], "2023-24")
        self.assertEqual(json_data["reporting_period"], "FY 2023-24")
        self.assertEqual(json_data["report_title"], "HUDCO 54th Annual Report 2023-24")

        # Roundtrip deserialization
        restored = CanonicalChunk.model_validate(json_data)
        self.assertEqual(restored.fiscal_year, "2023-24")
        self.assertEqual(restored.reporting_period, "FY 2023-24")
        self.assertEqual(restored.report_title, "HUDCO 54th Annual Report 2023-24")

    def test_structured_table_detected_fiscal_years(self):
        """Verify table model holds multiple financial years for comparative balance sheets."""
        tbl = StructuredTable(
            table_id="tbl_p153_0",
            physical_page=153,
            printed_page="151",
            row_count=10,
            col_count=4,
            headers=["Particulars", "Note No.", "As at 31st March 2024", "As at 31st March 2023"],
            rows=[["Total Equity", "15", "15,480.00", "14,120.00"]],
            raw_text="Equity table",
            markdown_representation="| Particulars | Note No. | As at 31st March 2024 | As at 31st March 2023 |\n| Total Equity | 15 | 15,480.00 | 14,120.00 |",
            detected_fiscal_years=["2023-24", "2022-23"],
        )
        self.assertEqual(tbl.detected_fiscal_years, ["2023-24", "2022-23"])

    def test_retrieval_filtering_by_fiscal_year(self):
        """Verify BM25 index correctly filters chunks by single and multi-value fiscal year."""
        c1 = CanonicalChunk(
            chunk_id="c1",
            document_id="doc_ar24",
            version_id="v1",
            source_id="s1",
            source_filename="ar24.pdf",
            section_id="sec_01",
            section_title="Financial Highlights",
            physical_page=10,
            chunk_index_in_page=0,
            has_table=False,
            char_count=50,
            token_estimate=12,
            content="Net profit reached record highs in housing loans disbursement.",
            content_sha256="1" * 64,
            structured_tables=[],
            ancestor_headings=[],
            source_block_ids=[],
            fiscal_year="2023-24",
        )
        c2 = CanonicalChunk(
            chunk_id="c2",
            document_id="doc_ar26",
            version_id="v1",
            source_id="s2",
            source_filename="ar26.pdf",
            section_id="sec_01",
            section_title="Financial Highlights",
            physical_page=10,
            chunk_index_in_page=0,
            has_table=False,
            char_count=50,
            token_estimate=12,
            content="Net profit increased significantly with expanded infrastructure loans.",
            content_sha256="2" * 64,
            structured_tables=[],
            ancestor_headings=[],
            source_block_ids=[],
            fiscal_year="2025-26",
        )

        index = Layer4BM25Index(chunks=[c1, c2])

        # Query without filter: returns both
        res_all = index.retrieve("profit loans", top_k=5)
        self.assertEqual(len(res_all.results), 2)

        # Filter strictly for 2023-24
        filter_24 = RetrievalFilter(fiscal_year="2023-24")
        res_24 = index.retrieve("profit loans", top_k=5, filters=filter_24)
        self.assertEqual(len(res_24.results), 1)
        self.assertEqual(res_24.results[0].chunk_id, "c1")
        self.assertEqual(res_24.results[0].fiscal_year, "2023-24")

        # Filter strictly for 2025-26
        filter_26 = RetrievalFilter(fiscal_year="2025-26")
        res_26 = index.retrieve("profit loans", top_k=5, filters=filter_26)
        self.assertEqual(len(res_26.results), 1)
        self.assertEqual(res_26.results[0].chunk_id, "c2")
        self.assertEqual(res_26.results[0].fiscal_year, "2025-26")

        # Multi-value filter
        filter_multi = RetrievalFilter(fiscal_years=["2023-24", "2025-26"])
        res_multi = index.retrieve("profit loans", top_k=5, filters=filter_multi)
        self.assertEqual(len(res_multi.results), 2)

    def test_existing_approved_run_ar26_artifacts_load_cleanly(self):
        """Verify the approved run chunks.jsonl (2,682 chunks) can be loaded without error."""
        chunks_file = Path("data/output_chunks/run_full_ar26_p1_520_v1/chunks.jsonl")
        if not chunks_file.exists():
            self.skipTest("Approved run chunks.jsonl not found in repo.")
        chunks = load_canonical_chunks(str(chunks_file))
        self.assertEqual(len(chunks), 2682)

    def test_pilot_ar24_artifacts_load_cleanly(self):
        """Verify pilot ar24 chunks.jsonl (2,360 chunks with calibrated 19 sections) can be loaded and has fiscal_year set."""
        chunks_file = Path("data/output_chunks/run_pilot_ar24_p1_426_v1/chunks.jsonl")
        if not chunks_file.exists():
            self.skipTest("Pilot ar24 chunks.jsonl not found.")
        chunks = load_canonical_chunks(str(chunks_file))
        self.assertEqual(len(chunks), 2360)
        # Verify all carry fiscal_year '2023-24'
        for c in chunks[:50]:
            self.assertEqual(c.fiscal_year, "2023-24")
            self.assertEqual(c.report_title, "HUDCO 54th Annual Report 2023-24")


if __name__ == "__main__":
    unittest.main()
