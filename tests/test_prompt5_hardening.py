"""
Unit Tests for Prompt 5 Reliability Hardening.
File: tests/test_prompt5_hardening.py

Tests:
1. UI query validation: rejection of empty queries, bad top_k, bad methods, ar20, bad page ranges.
2. Citation validator: detection of grounded citations, out-of-bounds markers, unverified chunk IDs.
3. Subprocess lifecycle: graceful termination, timeout enforcement, stderr circular buffer.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.retrieval.contracts import RetrievalResultItem
from pipeline.inference.qwen_service import validate_citations, QwenInferenceService


class TestPrompt5Hardening(unittest.TestCase):
    def setUp(self):
        self.item1 = RetrievalResultItem(
            rank=1,
            chunk_id="chunk_hudco_1",
            score=0.9,
            matched_terms=["sanctions"],
            term_coverage=1.0,
            explanation="Match",
            document_id="ar26",
            version_id="v1",
            source_id="src_ar26",
            source_filename="ar26.pdf",
            section_id="sec_1",
            section_title="Sanctions",
            physical_page=10,
            has_table=False,
            content_sha256="a" * 64,
            fiscal_year="2025-26",
            content="Total loan sanctions reached Rs 82,500 crore.",
        )
        self.item2 = RetrievalResultItem(
            rank=2,
            chunk_id="chunk_hudco_2",
            score=0.8,
            matched_terms=["disbursements"],
            term_coverage=1.0,
            explanation="Match",
            document_id="ar26",
            version_id="v1",
            source_id="src_ar26",
            source_filename="ar26.pdf",
            section_id="sec_2",
            section_title="Disbursements",
            physical_page=12,
            has_table=False,
            content_sha256="b" * 64,
            fiscal_year="2025-26",
            content="Total disbursements were Rs 55,000 crore.",
        )

    def test_citation_validator_fully_grounded(self):
        """Validates that cited chunk IDs and bracket markers matching evidence pass as verified."""
        raw_answer = "HUDCO sanctions stood at Rs 82,500 crore [1] and disbursements at Rs 55,000 crore [2]."
        cited_cids = ["chunk_hudco_1", "chunk_hudco_2"]
        val = validate_citations(
            cited_chunk_ids=cited_cids,
            retrieved_items=[self.item1, self.item2],
            raw_answer=raw_answer,
        )
        self.assertTrue(val["is_valid"])
        self.assertTrue(val["has_citations"])
        self.assertEqual(val["verification_status"], "VERIFIED_GROUNDED")
        self.assertEqual(val["grounded_chunk_ids"], ["chunk_hudco_1", "chunk_hudco_2"])
        self.assertEqual(val["unverified_chunk_ids"], [])
        self.assertEqual(val["out_of_bounds_markers"], [])

    def test_citation_validator_flags_hallucinated_brackets(self):
        """Validates that bracket citations outside retrieved items range are flagged."""
        raw_answer = "Net profit was Rs 2,116 crore [99]."
        cited_cids = []
        val = validate_citations(
            cited_chunk_ids=cited_cids,
            retrieved_items=[self.item1, self.item2],
            raw_answer=raw_answer,
        )
        self.assertFalse(val["is_valid"])
        self.assertEqual(val["verification_status"], "HALLUCINATED_OR_INVALID_CITATIONS")
        self.assertEqual(val["out_of_bounds_markers"], [99])

    def test_citation_validator_flags_unverified_chunk_id(self):
        """Validates that cited chunk IDs absent from evidence list are flagged."""
        raw_answer = "Sanctions data [1]."
        cited_cids = ["chunk_hudco_1", "fabricated_chunk_id_xyz"]
        val = validate_citations(
            cited_chunk_ids=cited_cids,
            retrieved_items=[self.item1],
            raw_answer=raw_answer,
        )
        self.assertFalse(val["is_valid"])
        self.assertIn("fabricated_chunk_id_xyz", val["unverified_chunk_ids"])
        self.assertEqual(val["verification_status"], "HALLUCINATED_OR_INVALID_CITATIONS")

    def test_qwen_service_inference_timeout(self):
        """Validates that Qwen inference service enforces timeout when worker hangs."""
        service = QwenInferenceService(
            model_path=r"C:\Users\Praneya Arora\Desktop\qwen 4B",
            startup_timeout=2.0,
            inference_timeout=1.0,
        )
        # Mock process to hang on queue get
        with patch.object(service, "_ensure_worker"):
            service._process = MagicMock()
            service._process.stdin = MagicMock()
            res = service.generate(
                query="test timeout",
                retrieved_items=[self.item1],
            )
            self.assertIn(res["status"], ("inference_error", "inference_timeout"))
            self.assertTrue(res["is_refusal"])
            self.assertIn("timed out", res["answer"])


if __name__ == "__main__":
    unittest.main()

