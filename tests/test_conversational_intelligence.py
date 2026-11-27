"""
Unit Test Suite for HUDCO Bot Conversational Intelligence & Emotional Context.
File: tests/test_conversational_intelligence.py
"""

import unittest
from pipeline.inference.conversational_agent import (
    detect_language,
    detect_emotional_tone,
    check_conversational_intent,
    detect_spam,
    detect_abusive_content,
    detect_ambiguity_or_conflict,
)
from pipeline.context.token_meter import calculate_context_telemetry
from pipeline.storage.conversation_storage import FileConversationStorage
from pipeline.inference.qwen_service import strip_citation_markers
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

    def test_spam_detection(self):
        # Keysmash & repeated patterns
        is_spam, msg = detect_spam("asdasdasdasdasd")
        self.assertTrue(is_spam)
        self.assertIn("spam", msg.lower())

        is_spam2, _ = detect_spam("aaaaaaaaaaaa")
        self.assertTrue(is_spam2)

        is_spam3, _ = detect_spam("hello hello hello hello hello hello")
        self.assertTrue(is_spam3)

        # Repeated turns flooding
        history = [
            ChatMessage(role="user", content="tell me profit"),
            ChatMessage(role="assistant", content="Profit is Rs 2,116 cr"),
            ChatMessage(role="user", content="tell me profit"),
            ChatMessage(role="assistant", content="Profit is Rs 2,116 cr"),
        ]
        is_spam4, msg4 = detect_spam("tell me profit", recent_turns=history)
        self.assertTrue(is_spam4)

        # Genuine query must NOT be flagged as spam
        not_spam, _ = detect_spam("who is the chairman and managing director of hudco?")
        self.assertFalse(not_spam)

    def test_abusive_language_detection(self):
        # English abuse
        is_abusive, msg = detect_abusive_content("You are an idiot and stupid bot")
        self.assertTrue(is_abusive)
        self.assertIn("polite", msg.lower())

        # Hindi/Hinglish abuse
        is_abusive_hi, msg_hi = detect_abusive_content("bhosdike mera loan approve kar")
        self.assertTrue(is_abusive_hi)
        self.assertIn("vinamra", msg_hi.lower())

        # Normal queries must NOT be flagged
        not_abusive, _ = detect_abusive_content("What is the asset quality and gross NPA of HUDCO?")
        self.assertFalse(not_abusive)

    def test_ambiguity_and_conflict_clarification(self):
        # Asking vague "who is ed?" must ask for department clarification
        res_ed = check_conversational_intent("who is ed?")
        self.assertIsNotNone(res_ed)
        self.assertEqual(res_ed["intent"], "clarification_conflict")
        self.assertIn("Finance", res_ed["answer"])
        self.assertIn("Law", res_ed["answer"])
        self.assertIn("Executive Director", res_ed["answer"])

        # Asking vague "who is gm?" must ask for department clarification
        res_gm = check_conversational_intent("who is the gm?")
        self.assertIsNotNone(res_gm)
        self.assertEqual(res_gm["intent"], "clarification_conflict")
        self.assertIn("Human Resources", res_gm["answer"])
        self.assertIn("Information Technology", res_gm["answer"])

        # Asking specifically for "who is ed finance?" must pass to factual retrieval (not intercepted)
        res_spec = check_conversational_intent("who is ed finance?")
        self.assertIsNone(res_spec)

        # Asking for full list "list of all ed" must pass to factual retrieval (not intercepted)
        res_list = check_conversational_intent("give me the list of ed")
        self.assertIsNone(res_list)

    def test_context_budget_warnings_and_pyramid_pruning(self):
        # Test 50% warning
        t_50 = calculate_context_telemetry(
            system_prompt="Test",
            rolling_summary=None,
            active_turns=[{"role": "user", "content": "hello " * 800}],
            evidence_items=[],
            user_query="hi",
            max_budget=2000,
        )
        self.assertGreaterEqual(t_50.percentage, 50.0)
        self.assertIsNotNone(t_50.warning_message)
        self.assertIn("Older conversation turns will not be saved indefinitely", t_50.warning_message)

        # Test 100% capacity warning
        t_100 = calculate_context_telemetry(
            system_prompt="Test",
            rolling_summary=None,
            active_turns=[{"role": "user", "content": "hello " * 2000}],
            evidence_items=[],
            user_query="hi",
            max_budget=1000,
        )
        self.assertEqual(t_100.percentage, 100.0)
        self.assertIn("pyramid", t_100.warning_message.lower())

        # Test pyramid pruning in storage
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = FileConversationStorage(base_dir=tmp_dir)
            session = storage.create_conversation("user_test", "Test Chat")
            for i in range(10):
                storage.save_message("user_test", session.session_id, ChatMessage(role="user", content=f"msg_{i}"))

            s_before = storage.get_conversation("user_test", session.session_id)
            self.assertEqual(len(s_before.messages), 10)

            # Prune to keep last 4 turns
            storage.prune_oldest_messages("user_test", session.session_id, keep_last_n=4)
            s_after = storage.get_conversation("user_test", session.session_id)
            self.assertEqual(len(s_after.messages), 4)
            self.assertEqual(s_after.messages[-1].content, "msg_9")

    def test_crisp_bullet_points_prompt_and_sanitizer(self):
        # Verify synthesis prompt enforces crisp bullets and zero filler words
        prompt = build_synthesis_prompt(
            query="list the executive directors of hudco",
            evidence_items=[{"title": "Management", "content": "Daljeet Singh Khatri, Varsha Punhani"}],
            language="english"
        )
        self.assertIn("CRISP, DIRECT & ZERO FILLER WORDS", prompt)
        self.assertIn("MANDATORY POINTER / BULLET FORMAT FOR LISTS", prompt)

        # Verify sanitizer strips conversational preamble
        raw = "Certainly! Here is the list of Executive Directors:\n• Shri Daljeet Singh Khatri\n• Ms. Varsha Punhani"
        cleaned = strip_citation_markers(raw)
        self.assertNotIn("Certainly", cleaned)
        self.assertNotIn("Here is the list", cleaned)
        self.assertIn("Shri Daljeet Singh Khatri", cleaned)


if __name__ == "__main__":
    unittest.main()

