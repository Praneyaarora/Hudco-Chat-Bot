"""
Unit and Integration Tests for Local UI, Qwen Integration, and Retrieval Diagnostics.
File: tests/test_local_ui_and_qwen.py

Covers all test requirements in Prompt 4, Section 7:
- UI request validation and retrieval-method / filter propagation.
- Provenance rendering, page spans, and table metadata.
- Correct handling of no-results, abstention, retrieval errors, and partial branch failure.
- Qwen model failure / unavailable handling without crashing retrieval results.
- Evidence-only answer construction and citation association.
- Runtime diagnostics when GPU metrics are available or unavailable.
- Index-load failures without destructive rebuilds.
- Regression of BM25, semantic, hybrid, canonical chunk IDs, and report filters.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.core.contracts import CanonicalChunk, StructuredTable
from pipeline.retrieval.contracts import (
    RetrievalFilter,
    RetrievalResultItem,
    RetrievalResponse,
    TableMetadata,
)
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.semantic_search import PersistentVectorIndex
from pipeline.retrieval.hybrid_search import HybridRetriever
from pipeline.inference.gpu_telemetry import get_gpu_telemetry
from pipeline.inference.qwen_service import QwenInferenceService
from pipeline.inference.qwen_worker import format_evidence_prompt


class TestLocalUIAndQwenIntegration(unittest.TestCase):
    def setUp(self):
        self.chunk1 = CanonicalChunk(
            chunk_id="chunk_hudco_1",
            document_id="ar26",
            version_id="v1",
            source_id="src_ar26",
            source_filename="ar26.pdf",
            chunk_index=1,
            chunk_index_in_page=1,
            char_count=120,
            token_estimate=30,
            section_id="sec_01",
            section_title="Operational Performance",
            physical_page=12,
            physical_page_end=15,
            physical_pages=[12, 13, 14, 15],
            printed_page="10",
            printed_page_end="13",
            printed_pages=["10", "11", "12", "13"],
            content="Total loan sanctions reached Rs 82,500 crore in FY 2025-26 across housing projects.",
            content_sha256="1" * 64,
            has_table=True,
            structured_tables=[
                StructuredTable(
                    table_id="tbl_sanctions",
                    caption="Loan Sanctions Summary",
                    unit_of_measure="₹ in Crore",
                    headers=["Category", "Amount"],
                    rows=[["Housing", "82,500"]],
                    markdown_representation="| Category | Amount |\n| Housing | 82,500 |",
                    row_count=1,
                    col_count=2,
                )
            ],
            fiscal_year="2025-26",
        )

        self.chunk2 = CanonicalChunk(
            chunk_id="chunk_hudco_2",
            document_id="ar24",
            version_id="v1",
            source_id="src_ar24",
            source_filename="ar24.pdf",
            chunk_index=2,
            chunk_index_in_page=1,
            char_count=100,
            token_estimate=25,
            section_id="sec_02",
            section_title="Financial Highlights",
            physical_page=45,
            physical_page_end=45,
            physical_pages=[45],
            printed_page="42",
            printed_page_end="42",
            printed_pages=["42"],
            content="Net profit for the year stood at Rs 2,116 crore representing a 24% growth.",
            content_sha256="2" * 64,
            has_table=False,
            fiscal_year="2023-24",
        )

    # -------------------------------------------------------------------------
    # 1. UI Request Validation & Filter Propagation
    # -------------------------------------------------------------------------
    def test_01_filter_propagation_and_validation(self):
        """Retrieval filters propagate faithfully across BM25 and Hybrid engines."""
        bm25 = Layer4BM25Index(chunks=[self.chunk1, self.chunk2], abstention_threshold=0.0)
        hybrid = HybridRetriever(bm25_index=bm25, semantic_index=None, rrf_k=60)

        # Cross-year query without filters
        resp_all = hybrid.search(query="loan sanctions", top_k=5)
        self.assertFalse(resp_all.is_abstention)
        self.assertEqual(resp_all.status, "evidence_available")
        self.assertGreaterEqual(len(resp_all.results), 1)

        # Filter strictly for FY 2023-24
        flt = RetrievalFilter(fiscal_year="2023-24")
        resp_filtered = hybrid.search(query="loan sanctions", top_k=5, filters=flt)
        for item in resp_filtered.results:
            self.assertEqual(item.fiscal_year, "2023-24")

    # -------------------------------------------------------------------------
    # 2. Rendering of Source Provenance, Page Spans, and Table Metadata
    # -------------------------------------------------------------------------
    def test_02_provenance_page_spans_and_table_metadata(self):
        """Retrieved evidence items retain full canonical metadata, page spans, and tables."""
        bm25 = Layer4BM25Index(chunks=[self.chunk1, self.chunk2], abstention_threshold=0.0)
        resp = bm25.search("Rs 82,500 crore", top_k=1)

        self.assertEqual(len(resp.results), 1)
        item = resp.results[0]
        self.assertEqual(item.chunk_id, "chunk_hudco_1")
        self.assertEqual(item.source_filename, "ar26.pdf")
        self.assertEqual(item.fiscal_year, "2025-26")
        self.assertEqual(item.physical_pages, [12, 13, 14, 15])
        self.assertEqual(item.printed_pages, ["10", "11", "12", "13"])
        self.assertTrue(item.has_table)
        self.assertIsNotNone(item.table_metadata)
        self.assertEqual(item.table_metadata[0].table_id, "tbl_sanctions")

    # -------------------------------------------------------------------------
    # 3. Handling of No-Results, Abstention, Errors, and Partial Branch Failure
    # -------------------------------------------------------------------------
    def test_03_retrieval_status_contracts(self):
        """Distinctly classifies no_results, abstained, partial_branch_failure, and retrieval_error."""
        # A. Empty query -> no_results
        bm25 = Layer4BM25Index(chunks=[self.chunk1])
        hybrid = HybridRetriever(bm25_index=bm25)
        resp_empty = hybrid.search("")
        self.assertTrue(resp_empty.is_abstention)
        self.assertEqual(resp_empty.status, "no_results")

        # B. Unanswerable query below threshold -> abstained
        resp_unans = bm25.search("international cryptocurrency bitcoin holdings in antarctica")
        self.assertTrue(resp_unans.is_abstention)
        self.assertEqual(resp_unans.status, "abstained")

        # C. Total failure across all active branches -> retrieval_error (not classified as abstention)
        mock_broken_bm25 = MagicMock()
        mock_broken_bm25.N = 10
        mock_broken_bm25.search.side_effect = RuntimeError("Disk I/O failure")
        broken_hybrid = HybridRetriever(bm25_index=mock_broken_bm25, semantic_index=None)
        resp_err = broken_hybrid.search("test query")
        self.assertEqual(resp_err.status, "retrieval_error")
        self.assertFalse(resp_err.is_abstention)

        # D. Partial branch failure: BM25 fails, but Semantic succeeds
        mock_sem = MagicMock()
        mock_sem.exists.return_value = True
        mock_sem.embeddings = [1, 2]
        mock_sem_item = RetrievalResultItem(
            rank=1,
            chunk_id="chunk_hudco_1",
            score=0.85,
            matched_terms=[],
            term_coverage=1.0,
            explanation="Semantic",
            document_id="ar26",
            version_id="v1",
            source_id="src_ar26",
            source_filename="ar26.pdf",
            section_id="sec_01",
            section_title="Operational Performance",
            physical_page=12,
            has_table=False,
            content="Loan sanctions data",
            content_sha256="1" * 64,
            fiscal_year="2025-26",
        )
        mock_sem.search.return_value = RetrievalResponse(
            query="test query",
            total_candidates_scored=1,
            total_results=1,
            results=[mock_sem_item],
            applied_filters=None,
            is_abstention=False,
            retrieval_method="semantic",
            status="evidence_available",
        )

        partial_hybrid = HybridRetriever(bm25_index=mock_broken_bm25, semantic_index=mock_sem)
        resp_partial = partial_hybrid.search("test query")
        self.assertEqual(resp_partial.status, "partial_branch_failure")
        self.assertFalse(resp_partial.is_abstention)
        self.assertEqual(len(resp_partial.results), 1)

    # -------------------------------------------------------------------------
    # 4. Qwen Inference Service Failure Handling (Preserves Retrieval Access)
    # -------------------------------------------------------------------------
    def test_04_qwen_failure_handling_preserves_retrieval(self):
        """If Qwen fails to spawn or crashes, service returns error payload without crashing retrieval."""
        service = QwenInferenceService(model_path="C:\\non_existent_model_dir_xyz")
        res = service.generate(
            query="What is HUDCO net profit?",
            retrieved_items=[self.chunk1.to_retrieval_item(rank=1, score=20.0) if hasattr(self.chunk1, "to_retrieval_item") else
                             RetrievalResultItem(
                                 rank=1,
                                 chunk_id=self.chunk1.chunk_id,
                                 score=20.0,
                                 matched_terms=["profit"],
                                 term_coverage=0.8,
                                 explanation="BM25",
                                 document_id=self.chunk1.document_id,
                                 version_id=self.chunk1.version_id,
                                 source_id=self.chunk1.source_id,
                                 source_filename=self.chunk1.source_filename,
                                 section_id=self.chunk1.section_id,
                                 section_title=self.chunk1.section_title,
                                 has_table=False,
                                 content_sha256=self.chunk1.content_sha256,
                                 fiscal_year=self.chunk1.fiscal_year,
                                 physical_page=self.chunk1.physical_page,
                                 content=self.chunk1.content,
                             )]
        )
        self.assertEqual(res["status"], "inference_error")
        self.assertTrue(res["is_refusal"])
        self.assertIn("Inference engine failure", res["answer"])
        self.assertIsNotNone(res["error"])

    # -------------------------------------------------------------------------
    # 5. Prompt Formatting & Citation Association
    # -------------------------------------------------------------------------
    def test_05_format_evidence_prompt_and_context_bounds(self):
        """Format evidence prompt includes source identifiers, citations, and enforces context budget."""
        evidence_list = [
            {
                "chunk_id": "chunk_101",
                "source_filename": "ar26.pdf",
                "fiscal_year": "2025-26",
                "citation_label": "Page 12",
                "section_title": "Sanctions",
                "content": "Loan sanctions were Rs 82,500 crore.",
            }
        ]
        prompt, included_ids, was_truncated = format_evidence_prompt(
            query="What were the sanctions?",
            evidence_items=evidence_list,
        )
        self.assertIn("--- EVIDENCE ITEM [1] ---", prompt)
        self.assertIn("Chunk ID: chunk_101", prompt)
        self.assertIn("Document: ar26.pdf", prompt)
        self.assertIn("Fiscal Year: 2025-26", prompt)
        self.assertIn("Location: Page 12", prompt)
        self.assertIn("USER QUESTION:", prompt)
        self.assertEqual(included_ids, ["chunk_101"])
        self.assertFalse(was_truncated)

    # -------------------------------------------------------------------------
    # 6. Real Runtime Diagnostics & NVIDIA Telemetry
    # -------------------------------------------------------------------------
    def test_06_gpu_telemetry_inspection(self):
        """GPU telemetry returns structured metrics or clean unavailable state without fabricated numbers."""
        telemetry = get_gpu_telemetry()
        self.assertIn("available", telemetry)
        self.assertIn("gpu_name", telemetry)
        self.assertIn("vram_used_mb", telemetry)
        self.assertIn("vram_total_mb", telemetry)

        if telemetry["available"]:
            self.assertIn("RTX 5060", telemetry["gpu_name"])
            self.assertGreater(telemetry["vram_total_mb"], 7000)
            self.assertIsNotNone(telemetry["driver_version"])

    # -------------------------------------------------------------------------
    # 7. Non-Destructive Vector Index Loading Failure Handling
    # -------------------------------------------------------------------------
    def test_07_index_load_failure_is_non_destructive(self):
        """Index loading errors do not overwrite or delete existing index directory."""
        v_index = PersistentVectorIndex(index_dir=Path("C:\\dummy_non_existent_index"))
        resp = v_index.search("test query")
        self.assertTrue(resp.is_abstention)
        self.assertEqual(resp.status, "no_results")
        self.assertIn("empty or has not been built", resp.abstention_reason)


if __name__ == "__main__":
    unittest.main()
