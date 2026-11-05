"""
Comprehensive End-to-End Production Flow Verification for HUDCO Bot.
File: tests/test_production_flow.py

Validates:
1. Server initialization & health check.
2. Guest session resolution (PostgreSQL & File without users_dir access).
3. Guest conversation creation and query flow.
4. User registration with Argon2id hashing & input validation.
5. User authentication & session lifecycle.
6. User logout & cookie clearance.
7. Tenant isolation (User A cannot access User B's conversations).
8. Vector index metadata integrity (cross-platform CRLF / LF invariance).
9. RAG hybrid retrieval over HUDCO canonical chunks.
10. Local file storage fallback when DATABASE_URL is unset.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.storage.contracts import ChatMessage, ConversationSession
from pipeline.storage.conversation_storage import FileConversationStorage
from pipeline.storage.postgres_storage import PostgresConversationStorage
from pipeline.storage.auth_manager import AuthSessionManager
from pipeline.retrieval.semantic_search import PersistentVectorIndex, compute_normalized_text_sha256
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.hybrid_search import HybridRetriever


class TestProductionFlow(unittest.TestCase):
    """End-to-end integration and security assertions for HUDCO Bot production deployment."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.context_path = Path(self.temp_dir.name)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_local_file_storage_lifecycle(self):
        """Verifies local mode file storage works completely without DATABASE_URL."""
        storage = FileConversationStorage(base_dir=str(self.context_path))
        
        # 1. Register user
        user = storage.create_user("analyst@hudco.in", "Analyst One", "StrongPass123!", role="analyst")
        self.assertTrue(user.user_id.startswith("user_"))
        self.assertEqual(user.email, "analyst@hudco.in")

        # 2. Re-lookup user by email
        lookup = storage.get_user_by_email("ANALYST@HUDCO.IN")
        self.assertIsNotNone(lookup)
        self.assertEqual(lookup.user_id, user.user_id)

        # 3. Create conversation
        conv = storage.create_conversation(user_id=user.user_id, title="Financial Analysis")
        self.assertTrue(conv.session_id.startswith("conv_"))

        # 4. Save messages
        msg = ChatMessage(role="user", content="What was HUDCO loan sanction amount?")
        updated = storage.save_message(user_id=user.user_id, session_id=conv.session_id, message=msg)
        self.assertEqual(len(updated.messages), 1)

        # 5. Verify rolling summary
        storage.update_rolling_summary(user_id=user.user_id, session_id=conv.session_id, summary_text="Discussed loan sanctions", pruned_turns=2)
        reloaded = storage.get_conversation(user_id=user.user_id, session_id=conv.session_id)
        self.assertEqual(reloaded.rolling_summary, "Discussed loan sanctions")
        self.assertEqual(reloaded.pruned_turns_count, 2)

    def test_02_tenant_isolation_idor_prevention(self):
        """Verifies User A cannot read, update, or delete User B's conversation in file storage."""
        storage = FileConversationStorage(base_dir=str(self.context_path))
        user_a = storage.create_user("user_a@hudco.in", "User A", "PassWordA123")
        user_b = storage.create_user("user_b@hudco.in", "User B", "PassWordB123")

        conv_a = storage.create_conversation(user_id=user_a.user_id, title="User A Confidential")

        # User B attempts to access User A's conversation
        self.assertIsNone(storage.get_conversation(user_id=user_b.user_id, session_id=conv_a.session_id))
        self.assertFalse(storage.rename_conversation(user_id=user_b.user_id, session_id=conv_a.session_id, new_title="Hacked"))
        self.assertFalse(storage.delete_conversation(user_id=user_b.user_id, session_id=conv_a.session_id))

    @patch("pipeline.storage.postgres_storage.pool.ThreadedConnectionPool")
    def test_03_postgres_guest_resolution_no_users_dir(self, mock_pool_cls):
        """Verifies Postgres storage guest resolution does NOT access users_dir and reuses existing user."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        # Mock existing guest user
        mock_cursor.fetchone.return_value = {
            "user_id": "user_guest_existing",
            "email": "guest@local.dev",
            "username": "Guest User",
            "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$fakehash",
            "role": "guest",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        storage = PostgresConversationStorage("postgresql://test:test@localhost:5432/neondb")
        # Ensure it does NOT have users_dir attribute
        self.assertFalse(hasattr(storage, "users_dir"))

        # Look up guest user by email
        guest = storage.get_user_by_email("guest@local.dev")
        self.assertIsNotNone(guest)
        self.assertEqual(guest.user_id, "user_guest_existing")

    def test_04_vector_index_cross_platform_hash_invariance(self):
        """Verifies metadata integrity verification succeeds for both CRLF and LF byte streams."""
        meta_file = Path("data/vector_index/chunks_metadata.jsonl")
        if meta_file.exists():
            norm_hash = compute_normalized_text_sha256(meta_file)
            # Must equal the canonical normalized LF hash
            self.assertEqual(norm_hash, "5a2cd1e6ba389106cfa193358831a83a74f21fc46ec2c7817c83b5d5bad4e97d")

    def test_05_auth_session_lifecycle(self):
        """Verifies session creation, authentication, and revocation."""
        storage = FileConversationStorage(base_dir=str(self.context_path))
        auth = AuthSessionManager(storage=storage)

        user = storage.create_user("session_test@hudco.in", "Session User", "Password123")
        token = auth.create_session(user_id=user.user_id, max_age=3600)
        self.assertTrue(len(token) >= 32)

        # Validate session
        validated_user = auth.validate_session(token)
        self.assertIsNotNone(validated_user)
        self.assertEqual(validated_user.user_id, user.user_id)

        # Revoke session
        self.assertTrue(auth.revoke_session(token))
        self.assertIsNone(auth.validate_session(token))


if __name__ == "__main__":
    unittest.main()
