"""
Unit and Integration Tests for Department Router, Official Links, and Annual Report Sleeping Mechanism.
File: tests/test_department_and_temporal_routing.py
"""

import unittest
from pipeline.retrieval.scoring import (
    detect_query_temporal_intent,
    filter_candidate_chunks_by_temporal_intent,
    rerank_chunks_with_recency,
)
from pipeline.retrieval.department_router import DepartmentRouter, DEPARTMENTS, expand_query_acronyms
from pipeline.retrieval.curated_retriever import CuratedLinksRetriever
from pipeline.context.query_context_rewriter import QueryContextRewriter


class TestDepartmentAndTemporalRouting(unittest.TestCase):

    def setUp(self):
        self.curated_retriever = CuratedLinksRetriever()
        self.router = DepartmentRouter(curated_retriever=self.curated_retriever)

    def test_default_temporal_intent_puts_older_reports_to_sleep(self):
        # Query does not ask for past years or history
        q = "what is the loan book of hudco?"
        info = detect_query_temporal_intent(q)
        self.assertFalse(info["historical_requested"])
        self.assertEqual(info["active_years"], {2026})

        mock_candidates = [
            {"chunk_id": "c_ar26", "document_id": "doc_ar26", "content": "FY26 loan book: 1,60,724 cr"},
            {"chunk_id": "c_ar25", "document_id": "doc_ar25", "content": "FY25 loan book: 1,24,828 cr"},
            {"chunk_id": "c_ar24", "document_id": "doc_ar24", "content": "FY24 loan book: 92,654 cr"},
            {"chunk_id": "link_curated", "source_type": "official_link", "content": "H1 FY27 loan book: 1,86,111 cr"},
        ]

        active = filter_candidate_chunks_by_temporal_intent(mock_candidates, query=q)
        active_ids = [c["chunk_id"] for c in active]
        self.assertIn("c_ar26", active_ids)
        self.assertIn("link_curated", active_ids)
        # ar25 and ar24 must be put to sleep!
        self.assertNotIn("c_ar25", active_ids)
        self.assertNotIn("c_ar24", active_ids)

    def test_relative_last_n_years_awakens_requested_range(self):
        # Query explicitly asks for "last 4 years"
        q = "tell me the profit and loan sanctions over the last 4 years?"
        info = detect_query_temporal_intent(q)
        self.assertTrue(info["historical_requested"])
        # Should awaken 2023, 2024, 2025, 2026
        self.assertEqual(info["active_years"], {2023, 2024, 2025, 2026})

        mock_candidates = [
            {"chunk_id": "c_ar26", "document_id": "doc_ar26", "content": "FY26"},
            {"chunk_id": "c_ar25", "document_id": "doc_ar25", "content": "FY25"},
            {"chunk_id": "c_ar24", "document_id": "doc_ar24", "content": "FY24"},
            {"chunk_id": "c_ar23", "document_id": "doc_ar23", "content": "FY23"},
            {"chunk_id": "c_ar20", "document_id": "doc_ar20", "content": "FY20 older"},
        ]

        active = filter_candidate_chunks_by_temporal_intent(mock_candidates, query=q)
        active_ids = [c["chunk_id"] for c in active]
        self.assertIn("c_ar26", active_ids)
        self.assertIn("c_ar25", active_ids)
        self.assertIn("c_ar24", active_ids)
        self.assertIn("c_ar23", active_ids)
        # ar20 is beyond the 4-year window and must remain asleep
        self.assertNotIn("c_ar20", active_ids)

    def test_explicit_historical_year_awakens_target_year(self):
        q = "what was the net profit in 2022?"
        info = detect_query_temporal_intent(q)
        self.assertTrue(info["historical_requested"])
        self.assertEqual(info["target_year"], 2022)

        mock_candidates = [
            {"chunk_id": "c_ar26", "document_id": "doc_ar26", "content": "FY26"},
            {"chunk_id": "c_ar22", "document_id": "doc_ar22", "content": "FY22"},
        ]
        active = filter_candidate_chunks_by_temporal_intent(mock_candidates, query=q)
        active_ids = [c["chunk_id"] for c in active]
        self.assertIn("c_ar22", active_ids)
        self.assertNotIn("c_ar26", active_ids)

    def test_department_router_classifies_finances_and_loan_book(self):
        q = "what is the loan book and loan outstanding of hudco?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "finances_and_results")
        self.assertIn("https://hudco.org.in/financial-presentations", dept.primary_urls)

        _, items = self.router.route_and_retrieve(q, top_k=3)
        self.assertGreater(len(items), 0)
        top = items[0]
        # Should retrieve latest presentation chunk or live presentation
        self.assertIn("1,86,111", top.content)
        self.assertGreaterEqual(top.recency_score, 1.30)

    def test_department_router_classifies_bonds(self):
        q = "how to apply for 54EC capital gains bonds?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "bonds_and_investors")

        _, items = self.router.route_and_retrieve(q, top_k=2)
        self.assertGreater(len(items), 0)
        self.assertTrue(any("54ec" in it.url.lower() or "bonds" in it.url.lower() for it in items))

    def test_department_router_classifies_careers(self):
        q = "are there any current job vacancies or recruitment in hudco?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "careers_and_recruitment")

    def test_department_router_classifies_tenders(self):
        q = "where can I find active tenders and e-procurement notices?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "tenders_and_procurement")

    def test_department_router_classifies_grievances(self):
        q = "how to file a complaint or grievance in CPGRAMS?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "grievances_and_redressal")

    def test_leadership_board_returns_sanjay_kulshrestha(self):
        q = "who is the chairman and managing director of hudco?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "leadership_and_board")

        _, items = self.router.route_and_retrieve(q, top_k=3)
        self.assertGreater(len(items), 0)
        has_cmd = any("Sanjay Kulshrestha" in it.content for it in items)
        self.assertTrue(has_cmd, "CMD Shri Sanjay Kulshrestha must be retrieved in leadership evidence")

    def test_acronym_expansion(self):
        self.assertIn("human resources", expand_query_acronyms("who is head of hr?"))
        self.assertIn("information technology", expand_query_acronyms("who is head of it?"))
        self.assertIn("managing director", expand_query_acronyms("who is the md of hudco?"))
        self.assertIn("profit after tax", expand_query_acronyms("what is pat in q2?"))

    def test_human_resources_department_retrieval(self):
        q = "who is the head of hr?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "human_resources_department")

        _, items = self.router.route_and_retrieve(q, top_k=3)
        self.assertGreater(len(items), 0)
        has_hr_head = any("Prabhjot Singh Makkar" in it.content or "GM(HR)" in it.content for it in items)
        self.assertTrue(has_hr_head, "Head of HR Prabhjot Singh Makkar must be retrieved in HR evidence")

    def test_information_technology_department_retrieval(self):
        q = "who is the head of it?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "information_technology_department")

        _, items = self.router.route_and_retrieve(q, top_k=3)
        self.assertGreater(len(items), 0)
        has_it_head = any("Hemlata Sharma" in it.content or "GM(IT)" in it.content for it in items)
        self.assertTrue(has_it_head, "Head of IT Hemlata Sharma must be retrieved in IT evidence")

    def test_shareholders_and_dividend_routing(self):
        q = "who are top 10 shareholders of hudco? and describe their dividend."
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "shareholders_and_dividends")

        _, items = self.router.route_and_retrieve(q, top_k=3)
        self.assertGreater(len(items), 0)
        has_lic_or_dividend = any("LIC" in it.content or "dividend" in it.content.lower() or "shareholding" in it.content.lower() for it in items)
        self.assertTrue(has_lic_or_dividend, "Evidence must contain shareholder/dividend details")

    def test_share_price_performance_routing(self):
        q = "what is share price performance of hudco?"
        dept = self.router.classify_query(q)
        self.assertIsNotNone(dept)
        self.assertEqual(dept.dept_id, "market_and_share_price")

        _, items = self.router.route_and_retrieve(q, top_k=3)
        self.assertGreater(len(items), 0)
        has_mcap_or_price = any("market capitalisation" in it.content.lower() or "share price" in it.content.lower() for it in items)
        self.assertTrue(has_mcap_or_price, "Evidence must contain share price / market capitalisation details")

    def test_query_context_rewriter_no_stickiness_and_pronoun_resolution(self):
        rewriter = QueryContextRewriter()

        # Case 1: Independent question after asking about CMD must NOT stick to CMD
        history_cmd = [
            {"role": "user", "content": "who is the chairman and cmd?"},
            {"role": "assistant", "content": "The Chairman & Managing Director of HUDCO is Shri Sanjay Kulshrestha."}
        ]
        rewritten_hr = rewriter.rewrite_query("who is the head of hr?", history_cmd)
        self.assertNotIn("cmd", rewritten_hr.lower())
        self.assertNotIn("sanjay kulshrestha", rewritten_hr.lower())
        self.assertEqual(rewritten_hr.strip(), "who is the head of hr?")

        # Case 2: Pronoun follow-up "how can I apply for it?" after 54EC bond must resolve to 54ec bond
        history_54ec = [
            {"role": "user", "content": "what are the features of 54ec bonds?"},
            {"role": "assistant", "content": "54EC Capital Gain Bonds offer tax exemption on long-term capital gains."}
        ]
        rewritten_apply = rewriter.rewrite_query("how can I apply for it?", history_54ec)
        self.assertIn("54ec", rewritten_apply.lower())
        self.assertNotIn("job", rewritten_apply.lower())
        self.assertNotIn("recruitment", rewritten_apply.lower())

    def test_historical_year_suppresses_live_links_and_prioritizes_past_report(self):
        q = "who was ed of hr in 2018?"
        info = detect_query_temporal_intent(q)
        self.assertTrue(info["historical_requested"])
        self.assertEqual(info["target_year"], 2018)

        mock_candidates = [
            {"chunk_id": "link_management_live", "source_type": "official_department_live", "content": "Smt. Vandana Motsara – ED HR 2026"},
            {"chunk_id": "c_ar18_hr", "document_id": "doc_ar18", "content": "J. Prem Nawaz ED (HR/Admn.) 2018"},
            {"chunk_id": "c_ar26_hr", "document_id": "doc_ar26", "content": "Current ED HR 2026"},
        ]

        active = filter_candidate_chunks_by_temporal_intent(mock_candidates, query=q)
        active_ids = [c["chunk_id"] for c in active]
        # Historical target year 2018 must awaken ar18 and put live 2026 link and ar26 to sleep
        self.assertIn("c_ar18_hr", active_ids)
        self.assertNotIn("link_management_live", active_ids)
        self.assertNotIn("c_ar26_hr", active_ids)


if __name__ == "__main__":
    unittest.main()
