"""
Session and Authentication Manager for HUDCO Bot.
File: pipeline/storage/auth_manager.py

Provides:
- Cryptographically secure session tokens via secrets module.
- HttpOnly cookie serialization.
- Session persistence across server restarts (sessions.json).
- Identity derivation strictly from verified server-side session.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from http import cookies
from pathlib import Path
from typing import Dict, Any, Optional

from pipeline.storage.contracts import UserProfile, UserProfilePublic
from pipeline.storage.conversation_storage import get_conversation_storage

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "hudco_session"
DEFAULT_SESSION_DURATION_SEC = 7 * 24 * 3600  # 7 days


class AuthSessionManager:
    """Manages secure user sessions and cookie lifecycle."""

    def __init__(self):
        self.storage = get_conversation_storage()
        self.sessions_file = self.storage.base_dir / "sessions.json"
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._load_sessions()

    def _load_sessions(self) -> None:
        """Loads active sessions from persistent storage."""
        with self._lock:
            if self.sessions_file.exists():
                try:
                    with open(self.sessions_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    now = time.time()
                    # Filter unexpired sessions
                    self._sessions = {
                        token: meta for token, meta in data.items()
                        if meta.get("expires_at", 0) > now
                    }
                except Exception as e:
                    logger.warning(f"Could not load sessions from file: {e}")
                    self._sessions = {}
            else:
                self._sessions = {}

    def _persist_sessions(self) -> None:
        """Saves sessions to disk atomically."""
        try:
            self.storage._atomic_write_json(self.sessions_file, self._sessions)
        except Exception as e:
            logger.error(f"Failed to persist sessions: {e}")

    def create_session(self, user_id: str, max_age: int = DEFAULT_SESSION_DURATION_SEC) -> str:
        """Generates a secure 256-bit session token."""
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + max_age

        with self._lock:
            self._sessions[token] = {
                "user_id": user_id,
                "created_at": time.time(),
                "expires_at": expires_at,
            }
            self._persist_sessions()

        logger.info(f"Created secure session for user '{user_id}' (expires in {max_age // 3600} hours).")
        return token

    def validate_session(self, token: str) -> Optional[UserProfile]:
        """Validates session token and returns active UserProfile if valid and not expired."""
        if not token:
            return None

        with self._lock:
            meta = self._sessions.get(token)
            if not meta:
                return None

            if meta.get("expires_at", 0) < time.time():
                # Expired
                del self._sessions[token]
                self._persist_sessions()
                return None

            user_id = meta.get("user_id")
            if not user_id:
                return None

            return self.storage.get_user_by_id(user_id)

    def revoke_session(self, token: str) -> bool:
        """Invalidates an active session token upon logout."""
        with self._lock:
            if token in self._sessions:
                del self._sessions[token]
                self._persist_sessions()
                return True
            return False

    def extract_token_from_headers(self, headers: Any) -> Optional[str]:
        """Parses HttpOnly cookie header to extract the session token."""
        raw_cookie = headers.get("Cookie") or headers.get("cookie") or ""
        if not raw_cookie:
            return None

        try:
            cookie_parser = cookies.SimpleCookie()
            cookie_parser.load(raw_cookie)
            if SESSION_COOKIE_NAME in cookie_parser:
                return cookie_parser[SESSION_COOKIE_NAME].value
        except Exception as e:
            logger.warning(f"Error parsing Cookie header: {e}")

        return None

    def authenticate_request(self, headers: Any) -> Optional[UserProfile]:
        """Convenience method: extracts cookie and resolves verified UserProfile."""
        token = self.extract_token_from_headers(headers)
        return self.validate_session(token) if token else None

    def build_set_cookie_header(self, token: str, max_age: int = DEFAULT_SESSION_DURATION_SEC) -> str:
        """Builds hardened Set-Cookie header string."""
        c = cookies.SimpleCookie()
        c[SESSION_COOKIE_NAME] = token
        c[SESSION_COOKIE_NAME]["path"] = "/"
        c[SESSION_COOKIE_NAME]["httponly"] = True
        c[SESSION_COOKIE_NAME]["samesite"] = "Lax"
        c[SESSION_COOKIE_NAME]["max-age"] = max_age
        # On production HTTPS (e.g. Render), Secure flag is recommended
        if os.environ.get("RENDER") or os.environ.get("USE_SECURE_COOKIES", "").lower() == "true":
            c[SESSION_COOKIE_NAME]["secure"] = True
        return c.output(header="").strip()

    def build_clear_cookie_header(self) -> str:
        """Builds Set-Cookie header to clear the session cookie upon logout."""
        c = cookies.SimpleCookie()
        c[SESSION_COOKIE_NAME] = ""
        c[SESSION_COOKIE_NAME]["path"] = "/"
        c[SESSION_COOKIE_NAME]["httponly"] = True
        c[SESSION_COOKIE_NAME]["samesite"] = "Lax"
        c[SESSION_COOKIE_NAME]["max-age"] = 0
        c[SESSION_COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        return c.output(header="").strip()


# Global singleton instance
_GLOBAL_AUTH: Optional[AuthSessionManager] = None


def get_auth_manager() -> AuthSessionManager:
    global _GLOBAL_AUTH
    if _GLOBAL_AUTH is None:
        _GLOBAL_AUTH = AuthSessionManager()
    return _GLOBAL_AUTH

