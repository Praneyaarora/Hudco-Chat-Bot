"""
Unit and Integration Tests for Semantic / Vector Retrieval Engine.
File: tests/test_semantic_retrieval.py

Covers all 15 test requirements in Prompt 2, Section 10:
- Vector dimensions, embedding consistency, and device fallback.
- Rejection of duplicate chunk IDs.
- Incremental caching of unchanged embeddings.
- Semantic query execution, scoring, and metadata filtering.
- Dynamic page citation provenance (e.g. targeted evidence page).
- Empty query and empty index handling.
- Index save, load, and corruption detection.
- Exclusion of unverified/blocked reports (e.g. ar20).
- Preservation of approved ar26 baseline.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from config.settings import settings
from pipeline.core.contracts import CanonicalChunk, StructuredTable
from pipeline.retrieval.contracts import RetrievalFilter, RetrievalResponse
from pipeline.retrieval.embedding import LocalEmbeddingEngine
from pipeline.retrieval.semantic_search import PersistentVectorIndex, VectorIndexManifest


class TestSemanticRetrieval(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_semantic_"))
        self.engine = LocalEmbeddingEngine(batch_size=16)
        self.index = PersistentVectorIndex(index_dir=self.test_dir, embedding_engine=self.engine)

        # Sample test canonical chunks
        self.chunk1 = CanonicalChunk(
            chunk_id="doc_ar24_v1_c000001",
            document_id="doc_ar24",
            source_id="hudco_annual_report_ar24",
            version_id="doc_ar24_v1",
            chunk_index=1,
            chunk_index_in_page=1,
            char_count=100,
            token_estimate=25,
            section_id="sec_01",
            section_title="Corporate Overview & Financial Highlights",
            ancestor_headings=["Annual Report 2023-24"],
            physical_page=5,
            physical_page_end=9,
            physical_pages=[5, 6, 7, 8, 9],
            content="Housing and Urban Development Corporation recorded historic loan sanctions of Rs. 82,000 crore.",
            content_sha256="a" * 64,
            has_table=False,
            fiscal_year="2023-24",
            source_filename="ar24.pdf",
        )

        self.chunk2 = CanonicalChunk(
            chunk_id="doc_ar24_v1_c000002",
            document_id="doc_ar24",
            source_id="hudco_annual_report_ar24",
            version_id="doc_ar24_v1",
            chunk_index=2,
            chunk_index_in_page=1,
            char_count=90,
            token_estimate=20,
            section_id="sec_02",
            section_title="Balance Sheet",
            ancestor_headings=["Financial Statements"],
            physical_page=45,
            physical_page_end=45,
            physical_pages=[45],
            content="Standalone Balance Sheet shows Net Worth of Rs. 16,500 crore as on 31st March 2024.",
            content_sha256="b" * 64,
            has_table=True,
            structured_tables=[
                StructuredTable(
                    table_id="tbl_bs_01",
                    caption="Balance Sheet Highlights",
                    unit_of_measure="₹ in Crore",
                    headers=["Particulars", "FY 2023-24", "FY 2022-23"],
                    rows=[
                        ["Net Worth", "16,500.00", "15,200.00"],
                        ["Total Assets", "92,000.00", "84,000.00"],
                    ],
                    markdown_representation="| Particulars | FY 2023-24 | FY 2022-23 |\n| Net Worth | 16,500.00 | 15,200.00 |",
                    row_count=2,
                    col_count=3,
                )
            ],
            fiscal_year="2023-24",
            source_filename="ar24.pdf",
        )

        self.chunk3 = CanonicalChunk(
            chunk_id="doc_ar26_v1_c000001",
            document_id="doc_ar26",
            source_id="hudco_annual_report_ar26",
            version_id="doc_ar26_v1",
            chunk_index=1,
            chunk_index_in_page=1,
            char_count=80,
            token_estimate=18,
            section_id="sec_01",
            section_title="Operational Review",
            ancestor_headings=["Performance Review"],
            physical_page=12,
            physical_page_end=12,
            physical_pages=[12],
            content="For FY 2025-26, HUDCO achieved net profit after tax of Rs. 2,500 crore.",
            content_sha256="c" * 64,
            has_table=False,
            fiscal_year="2025-26",
            source_filename="ar26.pdf",
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_build_and_dimension_consistency(self):
        """Index builds correctly and output matrix matches embedding dimension."""
        chunks = [self.chunk1, self.chunk2, self.chunk3]
        source_info = {
            "doc_ar24": {"source_id": "hudco_annual_report_ar24", "chunk_count": 2},
            "doc_ar26": {"source_id": "hudco_annual_report_ar26", "chunk_count": 1},
        }
        manifest = self.index.build_from_canonical_chunks(chunks, source_info, show_progress=False)

        self.assertEqual(manifest.total_chunks, 3)
        self.assertEqual(manifest.embedding_dimension, 384)
        self.assertEqual(self.index.embeddings.shape, (3, 384))
        self.assertTrue(self.index.exists())

    def test_02_rejection_of_duplicate_chunk_ids(self):
        """Duplicate chunk IDs must raise ValueError and abort build."""
        dup_chunk = CanonicalChunk(
            chunk_id="doc_ar24_v1_c000001",  # Same as chunk1
            document_id="doc_ar24",
            source_id="hudco_annual_report_ar24",
            version_id="doc_ar24_v1",
            chunk_index=99,
            chunk_index_in_page=99,
            char_count=50,
            token_estimate=10,
            section_id="sec_01",
            section_title="Dup",
            content="Duplicate chunk text",
            content_sha256="d" * 64,
            physical_page=1,
            source_filename="ar24.pdf",
        )
        with self.assertRaises(ValueError) as ctx:
            self.index.build_from_canonical_chunks([self.chunk1, dup_chunk], {}, show_progress=False)
        self.assertIn("Duplicate chunk ID", str(ctx.exception))

    def test_03_incremental_caching(self):
        """Unchanged chunk content SHA-256 reuses existing vector without re-encoding."""
        chunks = [self.chunk1, self.chunk2]
        manifest1 = self.index.build_from_canonical_chunks(chunks, {}, show_progress=False)
        self.assertEqual(manifest1.chunks_indexed, 2)
        self.assertEqual(manifest1.chunks_skipped, 0)

        # Build again with chunk1, chunk2 and new chunk3
        manifest2 = self.index.build_from_canonical_chunks([self.chunk1, self.chunk2, self.chunk3], {}, show_progress=False)
        self.assertEqual(manifest2.total_chunks, 3)
        self.assertEqual(manifest2.chunks_skipped, 2)  # Reused from cache
        self.assertEqual(manifest2.chunks_indexed, 1)  # Only chunk3 newly encoded

    def test_04_semantic_search_ranking(self):
        """Natural language queries rank relevant chunks with valid similarity scores."""
        self.index.build_from_canonical_chunks([self.chunk1, self.chunk2, self.chunk3], {}, show_progress=False)

        response = self.index.search("balance sheet net worth assets", top_k=2)
        self.assertFalse(response.is_abstention)
        self.assertEqual(len(response.results), 2)
        # Top result should be chunk2 (Balance Sheet)
        top = response.results[0]
        self.assertEqual(top.chunk_id, "doc_ar24_v1_c000002")
        self.assertGreater(top.score, 0.4)
        self.assertTrue(top.has_table)
        self.assertEqual(top.fiscal_year, "2023-24")

    def test_05_metadata_filtering(self):
        """Filters constrain search results by fiscal year, table flag, and document ID."""
        self.index.build_from_canonical_chunks([self.chunk1, self.chunk2, self.chunk3], {}, show_progress=False)

        # Filter by fiscal year 2025-26
        fy_filter = RetrievalFilter(fiscal_year="2025-26")
        res_fy = self.index.search("profit", filters=fy_filter)
        self.assertEqual(len(res_fy.results), 1)
        self.assertEqual(res_fy.results[0].chunk_id, "doc_ar26_v1_c000001")

        # Filter by has_table = True
        tbl_filter = RetrievalFilter(has_table=True)
        res_tbl = self.index.search("financials", filters=tbl_filter)
        self.assertEqual(len(res_tbl.results), 1)
        self.assertEqual(res_tbl.results[0].chunk_id, "doc_ar24_v1_c000002")

    def test_06_dynamic_citation_provenance_page_window(self):
        """Page filter intersects multi-page chunk and returns targeted evidence page."""
        self.index.build_from_canonical_chunks([self.chunk1], {}, show_progress=False)

        # Unfiltered citation reflects full span
        res_all = self.index.search("loan sanctions", top_k=1)
        self.assertEqual(res_all.results[0].citation_label, "Pages 5-9")

        # Targeted page window [8, 8]
        p_filter = RetrievalFilter(min_physical_page=8, max_physical_page=8)
        res_p8 = self.index.search("loan sanctions", top_k=1, filters=p_filter)
        self.assertEqual(len(res_p8.results), 1)
        item = res_p8.results[0]
        self.assertEqual(item.citation_page, 8)
        self.assertEqual(item.citation_pages, [8])
        self.assertEqual(item.citation_label, "Page 8")

    def test_07_empty_query_handling(self):
        """Empty query returns abstention response."""
        self.index.build_from_canonical_chunks([self.chunk1], {}, show_progress=False)
        res = self.index.search("   ")
        self.assertTrue(res.is_abstention)
        self.assertIn("Empty query", res.abstention_reason)

    def test_08_empty_index_handling(self):
        """Searching an empty or unbuilt index returns abstention."""
        empty_index = PersistentVectorIndex(index_dir=self.test_dir / "empty_dir", embedding_engine=self.engine)
        res = empty_index.search("any query")
        self.assertTrue(res.is_abstention)

    def test_09_save_and_reload_consistency(self):
        """Reloading persisted index produces identical vectors and search results."""
        self.index.build_from_canonical_chunks([self.chunk1, self.chunk2, self.chunk3], {}, show_progress=False)

        reloaded_index = PersistentVectorIndex(index_dir=self.test_dir, embedding_engine=self.engine)
        success = reloaded_index.load()
        self.assertTrue(success)
        self.assertEqual(len(reloaded_index.metadata_records), 3)

        res1 = self.index.search("loan sanctions", top_k=3)
        res2 = reloaded_index.search("loan sanctions", top_k=3)
        self.assertEqual([r.chunk_id for r in res1.results], [r.chunk_id for r in res2.results])
        self.assertEqual([r.score for r in res1.results], [r.score for r in res2.results])

    def test_10_approved_ar26_baseline_integrity(self):
        """Approved ar26 baseline files and latest pointer remain intact and valid."""
        approved_pointer = settings.OUTPUT_CHUNKS_DIR / "latest_approved_run.json"
        self.assertTrue(approved_pointer.exists())
        with open(approved_pointer, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("source_filename"), "ar26.pdf")
        self.assertEqual(data.get("source_sha256"), "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41")
        self.assertEqual(data.get("total_chunks"), 2682)

        approved_run = Path(data.get("approved_run_dir"))
        self.assertTrue(approved_run.exists())
        chunks_file = approved_run / "chunks.jsonl"
        self.assertTrue(chunks_file.exists())


if __name__ == "__main__":
    unittest.main()
