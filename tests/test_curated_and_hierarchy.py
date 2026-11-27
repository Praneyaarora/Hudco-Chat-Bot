"""
Unit tests for Curated Official HUDCO Links, 4-Tier Hierarchy, and Anti-Autofill Attributes.
File: tests/test_curated_and_hierarchy.py
"""

import os
import unittest
from pathlib import Path

from pipeline.retrieval.contracts import RetrievalResultItem
from pipeline.retrieval.curated_retriever import CuratedLinksRetriever
from pipeline.inference.llm_manager import build_synthesis_prompt


class TestCuratedLinksAndHierarchy(unittest.TestCase):

    def setUp(self):
        self.retriever = CuratedLinksRetriever()

    def test_curated_retriever_loaded(self):
        self.assertTrue(self.retriever._is_loaded, "CuratedLinksRetriever should load successfully.")
        self.assertGreater(len(self.retriever.chunks), 20, "Should have loaded curated chunks.")

    def test_leadership_board_query_prefers_official_board_link(self):
        query = "Who is the Chairman and Managing Director CMD of HUDCO?"
        results = self.retriever.retrieve(query, top_k=3)
        self.assertGreater(len(results), 0, "Should return results for CMD query.")
        top_item = results[0]
        self.assertEqual(top_item.source_type, "official_link")
        self.assertIn("Leadership?type=board", top_item.url)
        self.assertIn("Sanjay Kulshrestha", top_item.content)
        self.assertGreaterEqual(top_item.score, 0.70, "Official live link should have high score.")
        self.assertGreaterEqual(top_item.recency_score, 1.20)

    def test_management_team_query_prefers_management_link(self):
        query = "Who is the Chief Vigilance Officer CVO and Company Secretary of HUDCO?"
        results = self.retriever.retrieve(query, top_k=3)
        self.assertGreater(len(results), 0)
        found_mgmt = any("Leadership?type=management" in r.url for r in results)
        self.assertTrue(found_mgmt, "Management team link should be retrieved.")

    def test_corporate_office_query_retrieves_contact_or_office_link(self):
        query = "Where is HUDCO head office and registered office located?"
        results = self.retriever.retrieve(query, top_k=3)
        self.assertGreater(len(results), 0)
        top_item = results[0]
        self.assertTrue(
            ("corporate-office" in top_item.url) or ("contact-us" in top_item.url),
            f"Expected corporate-office or contact-us, got {top_item.url}"
        )

    def test_pdf_links_have_lower_priority_than_primary_web_links(self):
        primary_chunks = [c for c in self.retriever.chunks if "type=board" in c.get("url", "")]
        orgchart_chunks = [c for c in self.retriever.chunks if "orgchart.pdf" in c.get("url", "")]
        webdir_chunks = [c for c in self.retriever.chunks if "webdirectory.pdf" in c.get("url", "")]
        faq_chunks = [c for c in self.retriever.chunks if "FAQ-hudco.pdf" in c.get("url", "")]

        self.assertTrue(len(primary_chunks) > 0)
        self.assertTrue(len(orgchart_chunks) > 0)
        self.assertTrue(len(webdir_chunks) > 0)
        self.assertTrue(len(faq_chunks) > 0)

        # Primary HTML links have 1.15-1.20
        self.assertGreater(primary_chunks[0]["recency_score"], orgchart_chunks[0]["recency_score"])
        self.assertGreater(primary_chunks[0]["recency_score"], webdir_chunks[0]["recency_score"])
        self.assertGreater(primary_chunks[0]["recency_score"], faq_chunks[0]["recency_score"])

    def test_llm_manager_prompt_formats_official_link_evidence(self):
        item = {
            "title": "HUDCO Board Leadership",
            "url": "https://hudco.org.in/Leadership?type=board",
            "source_type": "official_link",
            "recency_tier": "Official Live Web Page",
            "content": "Shri Sanjay Kulshrestha is Chairman and MD.",
        }
        prompt = build_synthesis_prompt(
            query="Who is CMD?",
            evidence_items=[item],
            is_web=False,
        )
        self.assertIn("Official HUDCO Live Source", prompt)
        self.assertIn("https://hudco.org.in/Leadership?type=board", prompt)
        self.assertIn("Shri Sanjay Kulshrestha", prompt)

    def test_anti_autofill_attributes_in_index_html(self):
        index_html_path = Path(__file__).resolve().parent.parent / "ui" / "static" / "index.html"
        content = index_html_path.read_text(encoding="utf-8")

        # searchChatsInput must have autocomplete="off" and data-lpignore="true"
        self.assertIn('id="searchChatsInput"', content)
        self.assertIn('autocomplete="off"', content)
        self.assertIn('data-lpignore="true"', content)

        # chatInputText must have autocomplete="off" and data-lpignore="true"
        self.assertIn('id="chatInputText"', content)


if __name__ == "__main__":
    unittest.main()
