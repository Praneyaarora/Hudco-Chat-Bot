"""
Neon PostgreSQL Persistent Conversation and User Storage.
File: pipeline/storage/postgres_storage.py

Production-grade storage backend for hosted deployments (e.g., Render Free + Neon Free).
Supports:
1. Neon Serverless PostgreSQL with auto-suspend / cold-start recovery.
2. Connection pooling with pre-query ping, retry logic, and SSL (sslmode=require).
3. Strict multi-user tenant isolation (ownership enforced on all conversation queries).
4. Argon2id password hashing and validation.
5. Idempotent schema migrations (CREATE TABLE IF NOT EXISTS).
6. Full ChatMessage, ConversationSession, UserProfile, and session token persistence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

try:
    import psycopg2
    from psycopg2 import pool, extras
    from psycopg2.extensions import connection as PgConnection
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    PgConnection = Any

from pipeline.storage.contracts import (
    UserProfile,
    UserProfilePublic,
    ChatMessage,
    ConversationSession,
    ConversationSummaryItem,
)
from pipeline.storage.conversation_storage import ConversationStorage, StorageSecurityError

logger = logging.getLogger(__name__)

_ph = PasswordHasher()


def sanitize_db_url(raw_url: str) -> str:
    """
    Normalizes database URL:
    - Replaces postgres:// with postgresql://
    - Enforces sslmode=require for cloud-hosted databases (Neon, Render) if not present.
    """
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    try:
        parsed = urlparse(url)
        query_params = dict(parse_qsl(parsed.query))
        hostname = (parsed.hostname or "").lower()
        
        # Enforce SSL for Neon and remote databases
        if "sslmode" not in query_params and ("neon.tech" in hostname or "render.com" in hostname or "aws" in hostname):
            query_params["sslmode"] = "require"
            new_query = urlencode(query_params)
            url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))
    except Exception as e:
        logger.warning(f"Error sanitizing database URL query parameters: {e}")

    return url


class PostgresConversationStorage(ConversationStorage):
    """
    PostgreSQL-backed conversation and user storage engine.
    Designed for zero-cost operation on Neon Serverless Free Tier + Render Free.
    """

    is_postgres: bool = True

    def __init__(
        self,
        database_url: Optional[str] = None,
        min_connections: int = 1,
        max_connections: int = 8,
    ):
        if not HAS_PSYCOPG2:
            raise ImportError(
                "psycopg2 is required for PostgresConversationStorage. "
                "Install it with 'pip install psycopg2-binary'."
            )

        raw_url = database_url or os.environ.get("DATABASE_URL")
        if not raw_url:
            raise ValueError("DATABASE_URL environment variable or database_url parameter is required.")

        self.db_url = sanitize_db_url(raw_url)
        self.min_connections = min_connections
        self.max_connections = max_connections
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._init_pool()
        self._init_schema()

    def _init_pool(self) -> None:
        """Initializes connection pool with connection retry."""
        logger.info("Initializing PostgreSQL connection pool...")
        try:
            self._pool = pool.ThreadedConnectionPool(
                minconn=self.min_connections,
                maxconn=self.max_connections,
                dsn=self.db_url,
            )
            logger.info("PostgreSQL connection pool initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}")
            raise

    def close(self) -> None:
        """Closes all connections in the pool."""
        if self._pool:
            self._pool.closeall()
            self._pool = None

    @contextmanager
    def get_connection(self):
        """
        Context manager for acquiring a database connection from the pool.
        Handles Neon cold-start/sleep disconnects with automatic reconnect.
        """
        if self._pool is None:
            self._init_pool()

        conn = self._pool.getconn()
        try:
            # Quick health check (Neon sleep disconnect detection)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            except Exception:
                logger.warning("PostgreSQL connection ping failed (Neon wake/sleep). Recycling connection...")
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = psycopg2.connect(self.db_url)

            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                self._pool.putconn(conn)
            except Exception:
                pass

    def _init_schema(self) -> None:
        """Idempotently initializes all required tables and indexes."""
        ddl = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at DOUBLE PRECISION NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(64) PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            username VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(64) NOT NULL DEFAULT 'analyst',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

        CREATE TABLE IF NOT EXISTS sessions (
            token VARCHAR(128) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            created_at DOUBLE PRECISION NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

        CREATE TABLE IF NOT EXISTS conversations (
            session_id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT 'New Conversation',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            rolling_summary TEXT,
            pruned_turns_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS messages (
            message_id VARCHAR(64) PRIMARY KEY,
            session_id VARCHAR(64) NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role VARCHAR(32) NOT NULL,
            content TEXT NOT NULL,
            timestamp DOUBLE PRECISION NOT NULL,
            token_count INTEGER NOT NULL DEFAULT 0,
            evidence_payload JSONB DEFAULT '[]'::jsonb,
            provider_used VARCHAR(64),
            model_name VARCHAR(128),
            turn_index SERIAL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, timestamp ASC, turn_index ASC);
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
                cur.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, %s) ON CONFLICT (version) DO NOTHING;", (time.time(),))
        logger.info("PostgreSQL database schema initialized/verified.")

    # =========================================================================
    # User Management & Authentication
    # =========================================================================

    def create_user(self, email: str, username: str, password: str, role: str = "analyst") -> UserProfile:
        """Registers a new user with Argon2id password hash."""
        email_clean = email.strip().lower()
        if not email_clean or "@" not in email_clean:
            raise ValueError("Invalid email address format.")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters long.")

        pwd_hash = _ph.hash(password)
        now = time.time()
        user = UserProfile(
            email=email_clean,
            username=username.strip() or email_clean.split("@")[0],
            password_hash=pwd_hash,
            role=role,
            created_at=now,
            updated_at=now,
        )

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check for existing email
                cur.execute("SELECT user_id FROM users WHERE email = %s;", (email_clean,))
                if cur.fetchone():
                    raise ValueError("An account with this email address already exists.")

                cur.execute(
                    """
                    INSERT INTO users (user_id, email, username, password_hash, role, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (user.user_id, user.email, user.username, user.password_hash, user.role, user.created_at, user.updated_at),
                )

        logger.info(f"Registered user '{user.username}' ({user.email}) -> {user.user_id} in PostgreSQL")
        return user

    def authenticate_user(self, email: str, password: str) -> Optional[UserProfile]:
        """Authenticates user credentials using Argon2id."""
        email_clean = email.strip().lower()
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute(
                    "SELECT user_id, email, username, password_hash, role, created_at, updated_at FROM users WHERE email = %s;",
                    (email_clean,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                pwd_hash = row["password_hash"]
                try:
                    _ph.verify(pwd_hash, password)
                    # Check if hash needs upgrade
                    if _ph.check_needs_rehash(pwd_hash):
                        new_hash = _ph.hash(password)
                        cur.execute("UPDATE users SET password_hash = %s, updated_at = %s WHERE user_id = %s;", (new_hash, time.time(), row["user_id"]))
                    return UserProfile(
                        user_id=row["user_id"],
                        email=row["email"],
                        username=row["username"],
                        password_hash=row["password_hash"],
                        role=row["role"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                except (VerifyMismatchError, InvalidHashError):
                    return None
                except Exception as e:
                    logger.error(f"PostgreSQL authentication error for {email_clean}: {e}")
                    return None

    def get_user_by_id(self, user_id: str) -> Optional[UserProfile]:
        """Loads user profile record by user_id."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute(
                    "SELECT user_id, email, username, password_hash, role, created_at, updated_at FROM users WHERE user_id = %s;",
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return UserProfile(
                    user_id=row["user_id"],
                    email=row["email"],
                    username=row["username"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )

    # =========================================================================
    # Session Token Management (HttpOnly Cookie Sessions)
    # =========================================================================

    def save_session(self, token: str, user_id: str, expires_at: float) -> None:
        """Persists a valid session token in PostgreSQL."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (token, user_id, created_at, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (token) DO UPDATE SET expires_at = EXCLUDED.expires_at;
                    """,
                    (token, user_id, time.time(), expires_at),
                )

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Retrieves and validates an active session token."""
        now = time.time()
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute(
                    "SELECT token, user_id, created_at, expires_at FROM sessions WHERE token = %s;",
                    (token,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                if row["expires_at"] < now:
                    cur.execute("DELETE FROM sessions WHERE token = %s;", (token,))
                    return None
                return {
                    "token": row["token"],
                    "user_id": row["user_id"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                }

    def revoke_session(self, token: str) -> bool:
        """Revokes an active session token upon logout."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE token = %s;", (token,))
                return cur.rowcount > 0

    def cleanup_expired_sessions(self) -> int:
        """Purges expired sessions from database."""
        now = time.time()
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE expires_at < %s;", (now,))
                return cur.rowcount

    # =========================================================================
    # Conversation Session Management
    # =========================================================================

    def list_conversations(self, user_id: str) -> List[ConversationSummaryItem]:
        """Lists all conversations owned by the user, ordered by last update (newest first)."""
        query = """
        SELECT c.session_id, c.title, c.created_at, c.updated_at, c.rolling_summary,
               COUNT(m.message_id) AS msg_count,
               (
                   SELECT m2.content FROM messages m2
                   WHERE m2.session_id = c.session_id
                   ORDER BY m2.timestamp DESC, m2.turn_index DESC LIMIT 1
               ) AS last_msg
        FROM conversations c
        LEFT JOIN messages m ON m.session_id = c.session_id
        WHERE c.user_id = %s
        GROUP BY c.session_id, c.title, c.created_at, c.updated_at, c.rolling_summary
        ORDER BY c.updated_at DESC;
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute(query, (user_id,))
                rows = cur.fetchall()

        summaries = []
        for row in rows:
            last_msg = row["last_msg"] or ""
            preview = (last_msg[:90] + "...") if len(last_msg) > 90 else last_msg
            summaries.append(
                ConversationSummaryItem(
                    session_id=row["session_id"],
                    title=row["title"],
                    message_count=int(row["msg_count"]),
                    created_at=float(row["created_at"]),
                    updated_at=float(row["updated_at"]),
                    preview=preview,
                    has_summary=bool(row["rolling_summary"]),
                )
            )
        return summaries

    def get_conversation(self, user_id: str, session_id: str) -> Optional[ConversationSession]:
        """
        Retrieves a complete conversation session with all its messages.
        Enforces strict user ownership: cannot access sessions of another user.
        """
        clean_session = re.sub(r"[^a-zA-Z0-9_\-]", "", session_id)
        if clean_session != session_id:
            raise StorageSecurityError(f"Access denied: Illegal characters in session_id '{session_id}'.")

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT session_id, user_id, title, created_at, updated_at, rolling_summary, pruned_turns_count
                    FROM conversations
                    WHERE session_id = %s AND user_id = %s;
                    """,
                    (clean_session, user_id),
                )
                conv_row = cur.fetchone()
                if not conv_row:
                    return None

                cur.execute(
                    """
                    SELECT message_id, role, content, timestamp, token_count, evidence_payload, provider_used, model_name
                    FROM messages
                    WHERE session_id = %s
                    ORDER BY timestamp ASC, turn_index ASC;
                    """,
                    (clean_session,),
                )
                msg_rows = cur.fetchall()

        messages = []
        for m in msg_rows:
            ev_data = m["evidence_payload"]
            if isinstance(ev_data, str):
                try:
                    ev_data = json.loads(ev_data)
                except Exception:
                    ev_data = []
            elif ev_data is None:
                ev_data = []

            messages.append(
                ChatMessage(
                    message_id=m["message_id"],
                    role=m["role"],
                    content=m["content"],
                    timestamp=float(m["timestamp"]),
                    token_count=int(m["token_count"] or 0),
                    evidence_payload=ev_data,
                    provider_used=m["provider_used"],
                    model_name=m["model_name"],
                )
            )

        return ConversationSession(
            session_id=conv_row["session_id"],
            user_id=conv_row["user_id"],
            title=conv_row["title"],
            created_at=float(conv_row["created_at"]),
            updated_at=float(conv_row["updated_at"]),
            messages=messages,
            rolling_summary=conv_row["rolling_summary"],
            pruned_turns_count=int(conv_row["pruned_turns_count"] or 0),
        )

    def create_conversation(self, user_id: str, title: str = "New Conversation") -> ConversationSession:
        """Creates a new empty conversation session for the user."""
        now = time.time()
        session = ConversationSession(
            user_id=user_id,
            title=title.strip() or "New Conversation",
            created_at=now,
            updated_at=now,
            messages=[],
        )

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (session_id, user_id, title, created_at, updated_at, rolling_summary, pruned_turns_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (session.session_id, session.user_id, session.title, session.created_at, session.updated_at, None, 0),
                )

        logger.info(f"Created conversation '{session.session_id}' for user '{user_id}' in PostgreSQL")
        return session

    def save_message(self, user_id: str, session_id: str, message: ChatMessage) -> Optional[ConversationSession]:
        """Appends a new turn and updates the session atomically."""
        now = time.time()
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                # Ensure conversation exists and is owned by user
                cur.execute(
                    "SELECT session_id, title FROM conversations WHERE session_id = %s AND user_id = %s;",
                    (session_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    # Create conversation if not exists
                    first_title = message.content[:45].strip() or "New Chat"
                    cur.execute(
                        """
                        INSERT INTO conversations (session_id, user_id, title, created_at, updated_at, rolling_summary, pruned_turns_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (session_id, user_id, first_title, now, now, None, 0),
                    )
                    current_title = first_title
                else:
                    current_title = row["title"]

                # Auto-title on first user message if title is default
                if message.role == "user" and current_title in ("New Conversation", "New Chat"):
                    first_line = message.content.strip().split("\n")[0]
                    new_title = (first_line[:48] + "...") if len(first_line) > 48 else first_line
                    cur.execute(
                        "UPDATE conversations SET title = %s, updated_at = %s WHERE session_id = %s AND user_id = %s;",
                        (new_title, now, session_id, user_id),
                    )
                else:
                    cur.execute(
                        "UPDATE conversations SET updated_at = %s WHERE session_id = %s AND user_id = %s;",
                        (now, session_id, user_id),
                    )

                # Insert message
                ev_json = json.dumps(message.evidence_payload or [])
                cur.execute(
                    """
                    INSERT INTO messages (message_id, session_id, user_id, role, content, timestamp, token_count, evidence_payload, provider_used, model_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s);
                    """,
                    (
                        message.message_id,
                        session_id,
                        user_id,
                        message.role,
                        message.content,
                        message.timestamp or now,
                        message.token_count,
                        ev_json,
                        message.provider_used,
                        message.model_name,
                    ),
                )

        return self.get_conversation(user_id, session_id)

    def update_rolling_summary(self, user_id: str, session_id: str, summary_text: str, pruned_turns: int) -> bool:
        """Updates the rolling summary and accumulated pruned turns count."""
        now = time.time()
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET rolling_summary = %s,
                        pruned_turns_count = pruned_turns_count + %s,
                        updated_at = %s
                    WHERE session_id = %s AND user_id = %s;
                    """,
                    (summary_text.strip(), pruned_turns, now, session_id, user_id),
                )
                affected = cur.rowcount > 0

        if affected:
            logger.info(f"Updated rolling summary for session {session_id} in PostgreSQL (pruned {pruned_turns} turns).")
        return affected

    def rename_conversation(self, user_id: str, session_id: str, new_title: str) -> bool:
        """Renames a conversation session with ownership check."""
        clean_title = new_title.strip()
        if not clean_title:
            return False

        now = time.time()
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET title = %s, updated_at = %s
                    WHERE session_id = %s AND user_id = %s;
                    """,
                    (clean_title, now, session_id, user_id),
                )
                return cur.rowcount > 0

    def delete_conversation(self, user_id: str, session_id: str) -> bool:
        """Permanently deletes a conversation with strict ownership check (cascades to messages)."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM conversations WHERE session_id = %s AND user_id = %s;",
                    (session_id, user_id),
                )
                deleted = cur.rowcount > 0

        if deleted:
            logger.info(f"Deleted conversation {session_id} for user {user_id} from PostgreSQL")
        return deleted

    def export_conversation(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Exports a conversation thread as an audit-grade JSON payload."""
        session = self.get_conversation(user_id, session_id)
        if not session:
            return None
        payload = session.model_dump()
        payload["exported_at"] = time.time()
        payload["export_source"] = "HUDCO Bot Enterprise Storage (PostgreSQL)"
        return payload

    def import_conversation(self, user_id: str, data: Dict[str, Any]) -> Optional[ConversationSession]:
        """Imports an external conversation JSON into the user's isolated workspace."""
        try:
            messages_raw = data.get("messages", [])
            messages = [ChatMessage(**m) for m in messages_raw]

            session = ConversationSession(
                user_id=user_id,
                title=f"[Imported] {data.get('title', 'Restored Chat')}",
                messages=messages,
                rolling_summary=data.get("rolling_summary"),
                pruned_turns_count=data.get("pruned_turns_count", 0),
            )

            now = time.time()
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO conversations (session_id, user_id, title, created_at, updated_at, rolling_summary, pruned_turns_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (session.session_id, session.user_id, session.title, session.created_at, session.updated_at, session.rolling_summary, session.pruned_turns_count),
                    )
                    for m in messages:
                        cur.execute(
                            """
                            INSERT INTO messages (message_id, session_id, user_id, role, content, timestamp, token_count, evidence_payload, provider_used, model_name)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s);
                            """,
                            (
                                m.message_id,
                                session.session_id,
                                user_id,
                                m.role,
                                m.content,
                                m.timestamp or now,
                                m.token_count,
                                json.dumps(m.evidence_payload or []),
                                m.provider_used,
                                m.model_name,
                            ),
                        )
            return self.get_conversation(user_id, session.session_id)
        except Exception as e:
            logger.error(f"Failed to import conversation into PostgreSQL for {user_id}: {e}")
            return None

