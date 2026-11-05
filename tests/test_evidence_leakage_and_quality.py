"""
Unit & Integration Tests for HUDCO Bot Output Sanitization & Evidence Quality.
File: tests/test_evidence_leakage_and_quality.py
"""

import unittest
from pipeline.inference.qwen_service import strip_citation_markers
from pipeline.inference.llm_manager import build_synthesis_prompt


class TestEvidenceLeakageAndQuality(unittest.TestCase):

    def test_strip_arbitrary_citation_markers(self):
        raw = (
            "HUDCO's head office is in New Delhi, India.\n\n"
            "The current head of HUDCO is Sanjay Kulshrestha, who serves as Chairman & Managing Director.\n\n"
            "[Citation: Evidence Item – Headquarters: New Delhi, Delhi, India]\n\n"
            "[Citation: Evidence Item – Key people: Sanjay Kulshrestha (Chairman & MD)]\n\n"
            "[Citation: Evidence Item – Leadership: Sanjay Kulshrestha, Chairman & Managing Director]"
        )
        clean = strip_citation_markers(raw)
        self.assertNotIn("[Citation:", clean)
        self.assertNotIn("Evidence Item", clean)
        self.assertIn("New Delhi", clean)
        self.assertIn("Sanjay Kulshrestha", clean)
        self.assertEqual(
            clean,
            "HUDCO's head office is in New Delhi, India.\n\n"
            "The current head of HUDCO is Sanjay Kulshrestha, who serves as Chairman & Managing Director."
        )

    def test_strip_numeric_brackets_and_dangling_commas(self):
        raw = "HUDCO's head office is in New Delhi, India. The current head of HUDCO is Sanjay Kulshrestha. [1], [2], [3], [4]"
        clean = strip_citation_markers(raw)
        self.assertNotIn("[1]", clean)
        self.assertNotIn(",,,", clean)
        self.assertFalse(clean.endswith(","))
        self.assertIn("Sanjay Kulshrestha", clean)

    def test_strip_dangling_evidence_item_clause(self):
        raw = (
            "HUDCO's net profit in FY 2022-23 was Rs 1,701.62 crore, and in FY 2023-24 it was Rs 2,116.74 crore.\n"
            "and Evidence Item"
        )
        clean = strip_citation_markers(raw)
        self.assertNotIn("Evidence Item", clean)
        self.assertIn("1,701.62", clean)
        self.assertIn("2,116.74", clean)

    def test_strip_internal_notes_and_explanations(self):
        raw = (
            "The primary registered office number is 011-24649610-21.\n\n"
            "Note: The question asks for 'contact number', and multiple numbers are provided across different contexts."
        )
        clean = strip_citation_markers(raw)
        self.assertNotIn("Note:", clean)
        self.assertNotIn("multiple numbers", clean)
        self.assertIn("011-24649610-21", clean)

    def test_deduplication_of_redundant_lines(self):
        raw = (
            "Sanjay Kulshrestha is the Chairman and Managing Director of HUDCO.\n"
            "Sanjay Kulshrestha is the Chairman and Managing Director of HUDCO."
        )
        clean = strip_citation_markers(raw)
        self.assertEqual(clean.count("Sanjay Kulshrestha"), 1)

    def test_synthesis_prompt_forbids_citation_text(self):
        prompt = build_synthesis_prompt(
            query="Where is HUDCO head office and who is CMD?",
            evidence_items=[{"title": "HUDCO HQ", "content": "Head office in New Delhi, CMD Sanjay Kulshrestha"}],
            is_web=True
        )
        self.assertIn("CONSOLIDATE DUPLICATE FACTS", prompt)
        self.assertIn("ZERO CITATION TEXT IN ANSWER", prompt)


if __name__ == "__main__":
    unittest.main()

