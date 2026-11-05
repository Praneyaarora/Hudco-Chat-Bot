"""
Unit and Integration Tests for HUDCO Bot Storage, Authentication, and Context Subsystems.
File: tests/test_context_and_storage.py
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline.storage.contracts import ChatMessage, UserProfile
from pipeline.storage.conversation_storage import FileConversationStorage, StorageSecurityError
from pipeline.storage.auth_manager import AuthSessionManager
from pipeline.context.token_meter import (
    MODEL_CONTEXT_SPECS,
    estimate_tokens,
    validate_context_budget,
    calculate_context_telemetry,
    prune_conversation_turns,
)
from pipeline.context.rolling_summarizer import RollingSummarizer
from pipeline.context.query_context_rewriter import QueryContextRewriter


class TestContextAndStorageSubsystems(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hudco_test_context_")
        self.storage = FileConversationStorage(base_dir=self.temp_dir)
        self.auth = AuthSessionManager()
        self.auth.storage = self.storage
        self.auth.sessions_file = Path(self.temp_dir) / "sessions.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_user_creation_and_argon2_hashing(self):
        user = self.storage.create_user(
            email="test_analyst@hudco.in",
            username="Analyst Alpha",
            password="StrongPassword123!",
            role="analyst"
        )
        self.assertTrue(user.user_id.startswith("user_"))
        self.assertNotEqual(user.password_hash, "StrongPassword123!")
        self.assertTrue(user.password_hash.startswith("$argon2id$"))

        # Password verification
        authenticated = self.storage.authenticate_user("test_analyst@hudco.in", "StrongPassword123!")
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated.user_id, user.user_id)

        # Invalid password refusal
        bad_auth = self.storage.authenticate_user("test_analyst@hudco.in", "WrongPassword!")
        self.assertIsNone(bad_auth)

    def test_session_cookie_lifecycle(self):
        user = self.storage.create_user("user_b@hudco.in", "User B", "Pass12345!")
        token = self.auth.create_session(user.user_id)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 30)

        # Validate session
        validated_user = self.auth.validate_session(token)
        self.assertIsNotNone(validated_user)
        self.assertEqual(validated_user.user_id, user.user_id)

        # Build cookie header
        cookie_hdr = self.auth.build_set_cookie_header(token)
        self.assertIn("hudco_session=", cookie_hdr)
        self.assertIn("HttpOnly", cookie_hdr)

        # Revoke session (logout)
        revoked = self.auth.revoke_session(token)
        self.assertTrue(revoked)
        self.assertIsNone(self.auth.validate_session(token))

    def test_idor_isolation_between_users(self):
        user1 = self.storage.create_user("user1@hudco.in", "User 1", "P@ssword1")
        user2 = self.storage.create_user("user2@hudco.in", "User 2", "P@ssword2")

        # User 1 creates conversation
        conv1 = self.storage.create_conversation(user1.user_id, title="User 1 Secret Topic")
        self.assertIsNotNone(conv1)

        # User 2 attempts to read User 1 conversation
        attempt = self.storage.get_conversation(user2.user_id, conv1.session_id)
        self.assertIsNone(attempt, "User 2 must NOT be able to read User 1 conversation.")

    def test_directory_traversal_protection(self):
        user = self.storage.create_user("traversal@hudco.in", "Attacker", "P@ssword1")
        with self.assertRaises(StorageSecurityError):
            self.storage.get_conversation(user.user_id, "../../../etc/passwd")

    def test_rolling_summarizer(self):
        summarizer = RollingSummarizer()
        pruned = [
            ChatMessage(role="user", content="What was HUDCO loan disbursement in FY 2023-24?"),
            ChatMessage(role="assistant", content="In FY 2023-24, HUDCO achieved record loan disbursements of Rs 17,987 crore.")
        ]
        summary = summarizer.summarize_turns(
            existing_summary="",
            pruned_turns=pruned,
            active_provider="local_qwen"
        )
        self.assertIn("User", summary)
        self.assertIn("Assistant", summary)
        self.assertIn("loan disbursement", summary.lower())

    def test_contextual_query_rewriter(self):
        rewriter = QueryContextRewriter()
        recent_turns = [
            ChatMessage(role="user", content="Tell me about the UiWIN platform launched by HUDCO."),
            ChatMessage(role="assistant", content="UiWIN is a one-stop facilitator for urban local bodies.")
        ]
        rewritten = rewriter.rewrite_query(
            current_query="When was it launched?",
            recent_turns=recent_turns
        )
        self.assertNotIn("When was it launched?", rewritten)
        self.assertTrue("UiWIN" in rewritten or "platform" in rewritten)

    def test_token_meter_and_budget_validation(self):
        # Validation
        budget, warn = validate_context_budget("local_qwen", 40000)
        self.assertEqual(budget, 32768)  # Clamped to max

        budget_cloud, warn_cloud = validate_context_budget("gemini", 20000)
        self.assertIsNotNone(warn_cloud)
        self.assertIn("usage limits", warn_cloud)

        # Telemetry calculation
        telemetry = calculate_context_telemetry(
            system_prompt="HUDCO Bot System",
            rolling_summary="Prior discussion on loan sanctions.",
            active_turns=[{"role": "user", "content": "What about Net Worth?"}],
            evidence_items=[{"content": "Net worth for FY 23-24 was Rs 15,000 crore."}],
            user_query="What about Net Worth?",
            max_budget=8192
        )
        self.assertGreater(telemetry.used_tokens, 0)
        self.assertLessEqual(telemetry.percentage, 100.0)
        self.assertTrue(telemetry.has_rolling_summary)


if __name__ == "__main__":
    unittest.main()
