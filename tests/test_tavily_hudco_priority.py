"""
Tests for Score-Based Recency Prioritization, Grounding Sufficiency, and Tavily hudco.org.in Priority.
File: tests/test_tavily_hudco_priority.py

Validates:
1. Dynamic Recency Scoring: Highest value assigned to latest reports (FY 2025-26).
2. Historical Target Year Handling: Target year query ("in 2018") ranks historical report highest.
3. Grounding Sufficiency Evaluator: Enforces local chunks priority; prevents Tavily call when local chunks suffice.
4. Tavily Official Website Priority: Approach 1 targets hudco.org.in and official domains.
5. Entity Guardrails: Ensures false entities like Dobbs Ferry are disqualified while Indian HUDCO is prioritized.
"""

import unittest
from unittest.mock import patch, MagicMock

from pipeline.retrieval.contracts import RetrievalResultItem
from pipeline.retrieval.scoring import (
    parse_fiscal_year,
    detect_query_target_year,
    calculate_recency_score,
    calculate_relevance_score,
    compute_composite_score,
    rerank_chunks_with_recency,
    evaluate_local_sufficiency,
    LATEST_CORPUS_YEAR,
)
from pipeline.retrieval.tavily_search import TavilySearchAgent, INDIAN_HUDCO_KEYWORDS, DISQUALIFYING_PATTERNS


class TestScoreBasedRecencyAndTavilyPriority(unittest.TestCase):

    def setUp(self):
        self.chunk_latest = RetrievalResultItem(
            rank=1,
            chunk_id="chunk_2026_01",
            score=25.0,
            document_id="doc_ar26",
            version_id="v1",
            source_id="src_ar26",
            source_filename="ar26.pdf",
            section_id="sec_cmd",
            section_title="Board of Directors & Management",
            physical_page=12,
            content="Shri Sanjay Kulshrestha serves as Chairman & Managing Director of HUDCO in FY 2025-26.",
            content_sha256="a" * 64,
            fiscal_year="2025-26",
            has_table=False,
            bm25_score=26.5,
            semantic_score=0.82,
            rrf_score=0.031,
        )

        self.chunk_old = RetrievalResultItem(
            rank=2,
            chunk_id="chunk_2016_01",
            score=28.0,  # Higher raw BM25 score in older report
            document_id="doc_ar16",
            version_id="v1",
            source_id="src_ar16",
            source_filename="ar16.pdf",
            section_id="sec_cmd",
            section_title="Board of Directors",
            physical_page=14,
            content="Shri M. Ravi Kanth serves as Chairman & Managing Director of HUDCO in FY 2015-16.",
            content_sha256="b" * 64,
            fiscal_year="2015-16",
            has_table=False,
            bm25_score=28.0,
            semantic_score=0.79,
            rrf_score=0.032,
        )

        self.tavily_agent = TavilySearchAgent(api_key="tvly-mock-test-key")

    def test_01_parse_fiscal_year(self):
        """Verifies fiscal year extraction across string patterns, document IDs, and dicts."""
        self.assertEqual(parse_fiscal_year("2025-26"), 2026)
        self.assertEqual(parse_fiscal_year("2023-24"), 2024)
        self.assertEqual(parse_fiscal_year("doc_ar26"), 2026)
        self.assertEqual(parse_fiscal_year("ar15.pdf"), 2015)
        self.assertEqual(parse_fiscal_year({"fiscal_year": "2024-25"}), 2025)
        self.assertEqual(parse_fiscal_year(self.chunk_latest), 2026)
        self.assertIsNone(parse_fiscal_year("unknown_document"))

    def test_02_detect_query_target_year(self):
        """Detects whether user is querying current/latest information vs historical year."""
        # Current / General inquiries -> None (prioritize latest)
        self.assertIsNone(detect_query_target_year("Who is the CMD of HUDCO?"))
        self.assertIsNone(detect_query_target_year("HUDCO registered office contact number"))
        self.assertIsNone(detect_query_target_year("What are the housing loan interest rates?"))

        # Explicit historical queries -> Extracts target year
        self.assertEqual(detect_query_target_year("What was HUDCO net profit in 2018?"), 2018)
        self.assertEqual(detect_query_target_year("Loan sanctions for FY 2021-22"), 2022)
        self.assertEqual(detect_query_target_year("During 2016 what was the balance sheet size?"), 2016)

    def test_03_recency_score_prioritizes_latest_information(self):
        """Latest annual report (FY 2025-26) receives 1.0 recency score; historical reports decay."""
        score_2026, tier_2026 = calculate_recency_score(2026)
        score_2024, tier_2024 = calculate_recency_score(2024)
        score_2016, tier_2016 = calculate_recency_score(2016)

        self.assertEqual(score_2026, 1.00)
        self.assertIn("Latest", tier_2026)
        self.assertGreater(score_2026, score_2024)
        self.assertGreater(score_2024, score_2016)
        self.assertLessEqual(score_2016, 0.10)

    def test_04_recency_reranking_promotes_latest_chunk_over_older_chunk(self):
        """Even if an older report has a slightly higher raw BM25 score, the latest report ranks #1."""
        raw_candidates = [self.chunk_old, self.chunk_latest]
        query = "Who is the CMD of HUDCO?"

        reranked = rerank_chunks_with_recency(raw_candidates, query=query, top_k=2)

        # The FY 2025-26 chunk must be promoted to Rank 1
        self.assertEqual(reranked[0].chunk_id, "chunk_2026_01")
        self.assertEqual(reranked[0].rank, 1)
        self.assertEqual(reranked[0].fiscal_year, "2025-26")
        self.assertGreater(reranked[0].composite_score, reranked[1].composite_score)
        self.assertIn("Latest", reranked[0].recency_tier)

    def test_05_targeted_historical_query_prioritizes_requested_year(self):
        """When user asks for 2015-16, the 2015-16 chunk outscores the 2025-26 chunk."""
        raw_candidates = [self.chunk_latest, self.chunk_old]
        query = "Who was the CMD of HUDCO in 2016?"

        reranked = rerank_chunks_with_recency(raw_candidates, query=query, top_k=2)

        # The 2016 chunk must be Rank 1 for a 2016 query
        self.assertEqual(reranked[0].chunk_id, "chunk_2016_01")
        self.assertEqual(reranked[0].rank, 1)
        self.assertIn("Target Year Match", reranked[0].recency_tier)

    def test_06_evaluate_local_sufficiency_bypasses_tavily(self):
        """High-confidence local chunks suffice; Tavily web search is marked bypassed."""
        reranked = rerank_chunks_with_recency([self.chunk_latest], query="Who is CMD of HUDCO?", top_k=1)
        sufficiency = evaluate_local_sufficiency(reranked, min_threshold=0.40)

        self.assertTrue(sufficiency["is_sufficient"])
        self.assertEqual(sufficiency["decision"], "use_local_chunks")
        self.assertGreaterEqual(sufficiency["top_composite_score"], 0.40)
        self.assertIn("bypassed", sufficiency["reason"])

    def test_07_evaluate_local_sufficiency_permits_web_fallback_when_chunks_insufficient(self):
        """Low-scoring or empty chunk results trigger web fallback."""
        low_score_chunk = {
            "chunk_id": "chunk_weak",
            "score": 0.12,
            "composite_score": 0.18,
            "relevance_score": 0.10,
            "recency_score": 0.45,
            "recency_tier": "Archive",
            "source_filename": "ar15.pdf",
        }
        sufficiency = evaluate_local_sufficiency([low_score_chunk], min_threshold=0.40)

        self.assertFalse(sufficiency["is_sufficient"])
        self.assertEqual(sufficiency["decision"], "web_search_fallback")
        self.assertIn("fallback permitted", sufficiency["reason"])

    def test_08_tavily_web_search_prioritizes_hudco_official_domain(self):
        """Tavily search filters and validates results with highest domain bonus for hudco.org.in."""
        mock_raw_results = [
            {
                "title": "Welcome to HUDCO Official Website",
                "url": "https://hudco.org.in/contact-us",
                "content": "Registered and Corporate Office: HUDCO Bhawan, India Habitat Centre, Lodhi Road, New Delhi 110003 in 2026.",
                "score": 0.85,
            },
            {
                "title": "HUDCO News on Financial Portal",
                "url": "https://moneycontrol.com/news/hudco",
                "content": "HUDCO loan sanctions updates for housing infrastructure in 2025.",
                "score": 0.86,
            },
            {
                "title": "HudCo Shared Workspace",
                "url": "https://hudco.co/dobbs-ferry",
                "content": "Coworking space located in Dobbs Ferry, Westchester.",
                "score": 0.95,
            },
        ]

        validated = self.tavily_agent.filter_and_validate_results(mock_raw_results, "HUDCO contact number")

        # 1. Dobbs Ferry coworking space must be disqualified
        urls = [v["url"] for v in validated]
        self.assertNotIn("https://hudco.co/dobbs-ferry", urls)

        # 2. hudco.org.in must be ranked #1 with official domain bonus and recency bonus
        self.assertEqual(validated[0]["url"], "https://hudco.org.in/contact-us")
        self.assertEqual(validated[0]["domain"], "hudco.org.in")
        self.assertIn("hudco.org.in", validated[0]["recency_tier"])
        self.assertGreater(validated[0]["score"], validated[1]["score"])
        self.assertIsNotNone(validated[0]["scoring_breakdown"])

    @patch("urllib.request.urlopen")
    def test_09_tavily_search_approach1_official_hudco_domain_called(self, mock_urlopen):
        """Tavily search executes Approach 1 targeting hudco.org.in official domain."""
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"results": [{"title": "HUDCO Contact Details", "url": "https://hudco.org.in/contact", '
            b'"content": "HUDCO Bhawan New Delhi 110003 in 2026", "score": 0.90}], "answer": "Direct contact answer"}'
        )
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = self.tavily_agent.search(query="HUDCO helpline number", max_results=3)

        self.assertTrue(res["success"])
        self.assertEqual(res["provider"], "tavily_hudco_official")
        self.assertEqual(len(res["evidence"]), 1)
        self.assertEqual(res["evidence"][0]["domain"], "hudco.org.in")


if __name__ == "__main__":
    unittest.main()
