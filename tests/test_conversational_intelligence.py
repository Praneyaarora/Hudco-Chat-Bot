"""
Unit Test Suite for HUDCO Bot Conversational Intelligence & Emotional Context.
File: tests/test_conversational_intelligence.py
"""

import unittest
from pipeline.inference.conversational_agent import (
    detect_language,
    detect_emotional_tone,
    check_conversational_intent,
)
from pipeline.context.query_context_rewriter import QueryContextRewriter
from pipeline.storage.contracts import ChatMessage
from pipeline.inference.llm_manager import build_synthesis_prompt


class TestConversationalIntelligence(unittest.TestCase):

    def test_language_detection(self):
        # English
        self.assertEqual(detect_language("Where is the head office of HUDCO?"), "english")
        self.assertEqual(detect_language("What was the profit in FY 2023-24?"), "english")

        # Hinglish / Hindi
        self.assertEqual(detect_language("mereko hudco jana ha haryana mien office ha kya?"), "hinglish")
        self.assertEqual(detect_language("hudco ka office gurgaon mein hai kya?"), "hinglish")
        self.assertEqual(detect_language("mujhe complaint karni hai, kahan contact karun?"), "hinglish")
        self.assertEqual(detect_language("hudco mein job ke liye apply kaise karte hain?"), "hinglish")
        self.assertEqual(detect_language("iska last year ka profit kitna tha?"), "hinglish")

    def test_emotional_tone_and_complaint_detection(self):
        # Complaint / Frustration
        t1 = detect_emotional_tone("Is there any helpline number of HUDCO? I want to file a complaint against them!")
        self.assertTrue(t1["is_complaint"])
        self.assertTrue(t1["requires_empathy"])
        self.assertEqual(t1["tone"], "frustrated")

        t2 = detect_emotional_tone("mujhe complaint karni hai, bahut bekaar service hai")
        self.assertTrue(t2["is_complaint"])
        self.assertTrue(t2["requires_empathy"])

        # Gratitude
        t3 = detect_emotional_tone("Thank you so much for the help!")
        self.assertFalse(t3["is_complaint"])
        self.assertEqual(t3["tone"], "gratitude")

        # Neutral
        t4 = detect_emotional_tone("What are the loan sanctions in FY 2023-24?")
        self.assertFalse(t4["is_complaint"])
        self.assertFalse(t4["requires_empathy"])

    def test_natural_concise_greetings(self):
        # English greetings: short, natural, unseen variations
        for query in ["Hi", "Hello there", "Good morning"]:
            g = check_conversational_intent(query)
            self.assertIsNotNone(g, f"Failed greeting check for: {query}")
            self.assertEqual(g["intent"], "greeting")
            self.assertEqual(g["answer"], "Hello! Welcome to HUDCO Bot. How can I help you today?")

        # Hinglish & Indian greetings: warm, concise, and natural
        for query in ["Namaste", "Namashkar", "Pranaam", "Kaise ho?", "Kya haal hai?", "Namaste kaise ho?", "Namashkar, ek baat puchni thi"]:
            g = check_conversational_intent(query)
            self.assertIsNotNone(g, f"Failed greeting check for: {query}")
            self.assertEqual(g["intent"], "greeting")
            self.assertIn("HUDCO Bot mein aapka swagat hai", g["answer"])

    def test_complaints_and_dissatisfaction_intent(self):
        # Grievance queries must be caught and routed to grievance help
        complaint_queries = [
            "Is there any helpline number of HUDCO? I want to file a complaint against them!",
            "Maine pehle bhi complaint ki thi, abhi tak kuch nahi hua",
            "Inse baat kaise kar sakta hu? kaam hi nahi kar rahe ye log",
        ]
        for q in complaint_queries:
            tone = detect_emotional_tone(q)
            self.assertTrue(tone["is_complaint"], f"Emotional tone failed to detect complaint in: {q}")
            self.assertTrue(tone["requires_empathy"], f"Requires empathy should be True for: {q}")
            
            res = check_conversational_intent(q)
            self.assertIsNotNone(res, f"Failed grievance intent routing for: {q}")
            self.assertEqual(res["intent"], "grievance_help")
            self.assertIn("CPGRAMS", res["answer"])
            self.assertIn("011-24649610", res["answer"])

    def test_substantive_queries_not_intercepted_by_greetings(self):
        # Greetings combined with substantive queries should NOT be intercepted as pure greetings
        queries = [
            "Where is HUDCO head office located?",
            "What was HUDCO net profit in FY 2023-24?",
            "Hello, what was HUDCO's net profit in FY 2023-24?",
            "Good morning, what are HUDCO's loan sanctions in 2024?"
        ]
        for q in queries:
            res = check_conversational_intent(q)
            self.assertIsNone(res, f"Substantive query should NOT be intercepted as greeting: {q}")

    def test_ambiguous_visit_intent_clarification(self):
        # User says "mereko hudco jana hai" without location or purpose
        res = check_conversational_intent("mereko hudco jana hai")
        self.assertIsNotNone(res)
        self.assertEqual(res["intent"], "clarification_location")
        self.assertIn("Regional Office", res["answer"])
        self.assertIn("sheher ya rajya", res["answer"])

        res_en = check_conversational_intent("I want to visit HUDCO")
        self.assertIsNotNone(res_en)
        self.assertEqual(res_en["intent"], "clarification_location")
        self.assertIn("Regional Office", res_en["answer"])

    def test_contextual_query_rewriting_for_hinglish_and_locations(self):
        rewriter = QueryContextRewriter()

        # Follow-up after visit clarification
        history = [
            ChatMessage(role="user", content="mereko hudco jana hai"),
            ChatMessage(
                role="assistant",
                content="Sure! Are you looking to visit HUDCO's Registered Head Office in New Delhi or a specific Regional Office? Please specify your city or state."
            )
        ]
        q_rewritten = rewriter.rewrite_query("Haryana mein.", history)
        self.assertIn("HUDCO", q_rewritten)
        self.assertIn("Haryana", q_rewritten)
        self.assertIn("office", q_rewritten.lower())

        # Informal Hinglish office query directly specifying location
        q_loc = rewriter.rewrite_query("mereko hudco jana ha haryana mien office ha kya?", [])
        self.assertIn("Haryana", q_loc)
        self.assertIn("HUDCO", q_loc)

        # Hinglish pronoun follow-up
        history2 = [
            ChatMessage(role="user", content="What was HUDCO profit in FY 2023-24?"),
            ChatMessage(role="assistant", content="HUDCO reported record Net Profit of Rs 2,116.74 crore.")
        ]
        q_pronoun = rewriter.rewrite_query("aur iske loan sanctions kitne the?", history2)
        self.assertIn("loan sanctions", q_pronoun.lower())

    def test_empathy_prompt_construction(self):
        prompt = build_synthesis_prompt(
            query="I want to file a complaint against HUDCO, where do I call?",
            evidence_items=[{"title": "Grievance Redressal", "content": "Contact Grievance Officer at HUDCO Bhawan New Delhi"}],
            language="english",
            emotional_context={"requires_empathy": True, "is_complaint": True}
        )
        self.assertIn("Emotional Empathy & Grievance", prompt)
        self.assertIn("sincere acknowledgment", prompt)
        self.assertIn("CPGRAMS", prompt)


if __name__ == "__main__":
    unittest.main()

