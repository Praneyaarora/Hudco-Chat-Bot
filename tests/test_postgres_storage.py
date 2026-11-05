"""
Unit tests for PostgreSQL storage backend (Neon Serverless compatible).
File: tests/test_postgres_storage.py
"""

import unittest
from unittest.mock import MagicMock, patch
import json
import time

from pipeline.storage.contracts import ChatMessage, ConversationSession
from pipeline.storage.postgres_storage import sanitize_db_url, PostgresConversationStorage
from pipeline.storage.conversation_storage import StorageSecurityError


class TestPostgresStorage(unittest.TestCase):
    """Verifies PostgreSQL storage methods, URL sanitization, and security constraints."""

    def test_sanitize_db_url_converts_protocol(self):
        """Ensures postgres:// is rewritten to postgresql:// for psycopg2."""
        raw = "postgres://user:secret@ep-cool-fog.us-east-2.aws.neon.tech/neondb"
        cleaned = sanitize_db_url(raw)
        self.assertTrue(cleaned.startswith("postgresql://"))
        self.assertIn("sslmode=require", cleaned)

    def test_sanitize_db_url_preserves_existing_sslmode(self):
        """Ensures already configured sslmode is preserved."""
        raw = "postgresql://user:secret@ep-cool-fog.us-east-2.aws.neon.tech/neondb?sslmode=verify-full"
        cleaned = sanitize_db_url(raw)
        self.assertIn("sslmode=verify-full", cleaned)

    @patch("pipeline.storage.postgres_storage.pool.ThreadedConnectionPool")
    def test_schema_initialization(self, mock_pool_cls):
        """Verifies schema DDL execution on initialization."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        storage = PostgresConversationStorage("postgresql://test:test@localhost:5432/testdb")
        self.assertTrue(storage.is_postgres)
        # Verify DDL executed
        mock_cursor.execute.assert_any_call("INSERT INTO schema_migrations (version, applied_at) VALUES (1, %s) ON CONFLICT (version) DO NOTHING;", (unittest.mock.ANY,))

    @patch("pipeline.storage.postgres_storage.pool.ThreadedConnectionPool")
    def test_path_traversal_and_idor_prevention(self, mock_pool_cls):
        """Verifies that malicious session IDs with path traversal characters are rejected."""
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        storage = PostgresConversationStorage("postgresql://test:test@localhost:5432/testdb")

        # Path traversal characters should raise StorageSecurityError
        with self.assertRaises(StorageSecurityError):
            storage.get_conversation("user_123", "../../../etc/passwd")

        with self.assertRaises(StorageSecurityError):
            storage.get_conversation("user_123", "conv_123; DROP TABLE users;")

    @patch("pipeline.storage.postgres_storage.pool.ThreadedConnectionPool")
    def test_user_creation_and_argon2_hashing(self, mock_pool_cls):
        """Verifies user registration hashes password with Argon2id and executes parameterized INSERT."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # No existing user
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        storage = PostgresConversationStorage("postgresql://test:test@localhost:5432/testdb")
        user = storage.create_user("test@hudco.in", "Test Analyst", "securepassword123")

        self.assertEqual(user.email, "test@hudco.in")
        self.assertEqual(user.username, "Test Analyst")
        self.assertTrue(user.password_hash.startswith("$argon2id$"))

        # Verify SQL INSERT was parameterized
        insert_calls = [call for call in mock_cursor.execute.call_args_list if "INSERT INTO users" in str(call)]
        self.assertTrue(len(insert_calls) > 0)
        args = insert_calls[0][0][1]
        self.assertEqual(args[1], "test@hudco.in")
        self.assertEqual(args[2], "Test Analyst")

    @patch("pipeline.storage.postgres_storage.pool.ThreadedConnectionPool")
    def test_session_lifecycle(self, mock_pool_cls):
        """Verifies session save, get, and revocation in PostgreSQL."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        storage = PostgresConversationStorage("postgresql://test:test@localhost:5432/testdb")
        storage.save_session("tok_12345", "user_abc", time.time() + 3600)

        # Verify insert
        save_calls = [call for call in mock_cursor.execute.call_args_list if "INSERT INTO sessions" in str(call)]
        self.assertTrue(len(save_calls) > 0)

        # Mock active session return
        mock_cursor.fetchone.return_value = {
            "token": "tok_12345",
            "user_id": "user_abc",
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
        }
        res = storage.get_session("tok_12345")
        self.assertIsNotNone(res)
        self.assertEqual(res["user_id"], "user_abc")

        # Revoke
        mock_cursor.rowcount = 1
        revoked = storage.revoke_session("tok_12345")
        self.assertTrue(revoked)

    @patch("pipeline.storage.postgres_storage.pool.ThreadedConnectionPool")
    def test_storage_dispatch(self, mock_pool_cls):
        """Verifies get_conversation_storage dynamic dispatch between Postgres and File storage."""
        from pipeline.storage.conversation_storage import get_conversation_storage, FileConversationStorage
        import pipeline.storage.conversation_storage as cs_module

        # Reset global singleton for testing
        cs_module._GLOBAL_STORAGE = None

        with patch.dict("os.environ", {"DATABASE_URL": ""}):
            storage = get_conversation_storage()
            self.assertIsInstance(storage, FileConversationStorage)

        cs_module._GLOBAL_STORAGE = None
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://test:test@ep-neon.us-east-2.aws.neon.tech/neondb"}):
            storage = get_conversation_storage()
            self.assertIsInstance(storage, PostgresConversationStorage)

        # Reset back to default
        cs_module._GLOBAL_STORAGE = None


if __name__ == "__main__":
    unittest.main()
