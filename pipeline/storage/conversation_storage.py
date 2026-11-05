"""
Persistent File-Based Conversation and User Storage.
File: pipeline/storage/conversation_storage.py

Supports:
1. Render Persistent Disk (mounted at /var/data/context or CONTEXT_STORAGE_DIR)
2. Local Development (context/ in repository root)
3. Atomic file writes, path-traversal prevention, concurrency locks, and schema versioning.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from pipeline.storage.contracts import (
    UserProfile,
    UserProfilePublic,
    ChatMessage,
    ConversationSession,
    ConversationSummaryItem,
)

logger = logging.getLogger(__name__)

# Password hasher instance (Argon2id default)
_ph = PasswordHasher()


class StorageSecurityError(Exception):
    """Raised when an unauthorized path traversal or security violation is attempted."""
    pass


class ConversationStorage(abc.ABC):
    """Abstract base class defining the uniform storage contract."""

    @abc.abstractmethod
    def create_user(self, email: str, username: str, password: str, role: str = "analyst") -> UserProfile:
        pass

    @abc.abstractmethod
    def authenticate_user(self, email: str, password: str) -> Optional[UserProfile]:
        pass

    @abc.abstractmethod
    def get_user_by_id(self, user_id: str) -> Optional[UserProfile]:
        pass

    @abc.abstractmethod
    def list_conversations(self, user_id: str) -> List[ConversationSummaryItem]:
        pass

    @abc.abstractmethod
    def get_conversation(self, user_id: str, session_id: str) -> Optional[ConversationSession]:
        pass

    @abc.abstractmethod
    def create_conversation(self, user_id: str, title: str = "New Conversation") -> ConversationSession:
        pass

    @abc.abstractmethod
    def save_message(self, user_id: str, session_id: str, message: ChatMessage) -> Optional[ConversationSession]:
        pass

    @abc.abstractmethod
    def update_rolling_summary(self, user_id: str, session_id: str, summary_text: str, pruned_turns: int) -> bool:
        pass

    @abc.abstractmethod
    def rename_conversation(self, user_id: str, session_id: str, new_title: str) -> bool:
        pass

    @abc.abstractmethod
    def delete_conversation(self, user_id: str, session_id: str) -> bool:
        pass

    @abc.abstractmethod
    def export_conversation(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abc.abstractmethod
    def import_conversation(self, user_id: str, data: Dict[str, Any]) -> Optional[ConversationSession]:
        pass


class FileConversationStorage(ConversationStorage):
    """
    Production-grade file-based storage engine.
    Compatible with Render Persistent Disk mounts and local development environments.
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            env_path = os.environ.get("CONTEXT_STORAGE_DIR")
            if env_path:
                self.base_dir = Path(env_path).resolve()
            elif os.path.exists("/var/data"):
                # Standard Render Persistent Disk mount point
                self.base_dir = Path("/var/data/context").resolve()
            else:
                # Default local clone: context/ inside project root
                project_root = Path(__file__).resolve().parent.parent.parent
                self.base_dir = (project_root / "context").resolve()

        self.users_dir = self.base_dir / "users"
        self.index_file = self.base_dir / "users_index.json"
        self._lock = threading.RLock()

        # Initialize base directory structure
        self._init_storage()

    def _init_storage(self) -> None:
        """Ensures storage directories and index files exist."""
        with self._lock:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self.users_dir.mkdir(parents=True, exist_ok=True)
            if not self.index_file.exists():
                self._atomic_write_json(self.index_file, {"email_to_id": {}, "updated_at": time.time()})
            logger.info(f"Initialized FileConversationStorage at: {self.base_dir}")

    def _validate_safe_path(self, target_path: Path, expected_parent: Path) -> Path:
        """Guards against directory traversal attacks (e.g. ../../etc/passwd)."""
        resolved_target = target_path.resolve()
        resolved_parent = expected_parent.resolve()
        try:
            resolved_target.relative_to(resolved_parent)
        except ValueError:
            logger.critical(f"Path traversal attempt blocked: {resolved_target} outside {resolved_parent}")
            raise StorageSecurityError(f"Access denied: Path {target_path} is outside allowed boundary.")
        return resolved_target

    def _atomic_write_json(self, file_path: Path, data: Any) -> None:
        """
        Safely writes JSON payload using temporary file and atomic rename.
        Prevents corrupted files during power loss or abrupt process restarts.
        """
        parent = file_path.parent
        parent.mkdir(parents=True, exist_ok=True)

        # Create temporary file in same directory to ensure atomic rename across filesystem boundaries
        temp_fd, temp_path_str = tempfile.mkstemp(dir=str(parent), prefix=".tmp_write_", suffix=".json")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            os.replace(temp_path_str, str(file_path))
        except Exception:
            if os.path.exists(temp_path_str):
                try:
                    os.remove(temp_path_str)
                except OSError:
                    pass
            raise

    def _read_json(self, file_path: Path) -> Optional[Any]:
        """Reads and parses JSON file gracefully."""
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading JSON from {file_path}: {e}")
            return None

    def _get_user_dir(self, user_id: str) -> Path:
        clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "", user_id)
        if clean_id != user_id:
            raise StorageSecurityError(f"Access denied: Illegal characters or path traversal attempt in user_id '{user_id}'.")
        user_path = self.users_dir / clean_id
        return self._validate_safe_path(user_path, self.users_dir)

    def _get_conversations_dir(self, user_id: str) -> Path:
        user_dir = self._get_user_dir(user_id)
        conv_dir = user_dir / "conversations"
        return self._validate_safe_path(conv_dir, user_dir)

    # =========================================================================
    # User Management & Authentication
    # =========================================================================

    def create_user(self, email: str, username: str, password: str, role: str = "analyst") -> UserProfile:
        """Registers a new user with Argon2id hashed password."""
        email_clean = email.strip().lower()
        if not email_clean or "@" not in email_clean:
            raise ValueError("Invalid email address format.")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters long.")

        with self._lock:
            index_data = self._read_json(self.index_file) or {"email_to_id": {}}
            if email_clean in index_data.get("email_to_id", {}):
                raise ValueError("An account with this email address already exists.")

            pwd_hash = _ph.hash(password)
            user = UserProfile(
                email=email_clean,
                username=username.strip() or email_clean.split("@")[0],
                password_hash=pwd_hash,
                role=role,
            )

            user_dir = self._get_user_dir(user.user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            self._get_conversations_dir(user.user_id).mkdir(parents=True, exist_ok=True)

            # Save profile
            profile_path = user_dir / "profile.json"
            self._atomic_write_json(profile_path, user.model_dump())

            # Update index
            index_data["email_to_id"][email_clean] = user.user_id
            index_data["updated_at"] = time.time()
            self._atomic_write_json(self.index_file, index_data)

            logger.info(f"Registered user '{user.username}' ({user.email}) -> {user.user_id}")
            return user

    def authenticate_user(self, email: str, password: str) -> Optional[UserProfile]:
        """Authenticates user credentials using Argon2id verification."""
        email_clean = email.strip().lower()
        with self._lock:
            index_data = self._read_json(self.index_file) or {}
            user_id = index_data.get("email_to_id", {}).get(email_clean)
            if not user_id:
                return None

            user = self.get_user_by_id(user_id)
            if not user:
                return None

            try:
                _ph.verify(user.password_hash, password)
                # Check if hash needs rehash due to parameter updates
                if _ph.check_needs_rehash(user.password_hash):
                    user.password_hash = _ph.hash(password)
                    profile_path = self._get_user_dir(user.user_id) / "profile.json"
                    self._atomic_write_json(profile_path, user.model_dump())
                return user
            except (VerifyMismatchError, InvalidHashError):
                return None
            except Exception as e:
                logger.error(f"Authentication error for {email_clean}: {e}")
                return None

    def get_user_by_id(self, user_id: str) -> Optional[UserProfile]:
        """Loads user profile record by user_id."""
        try:
            user_dir = self._get_user_dir(user_id)
            profile_path = user_dir / "profile.json"
            data = self._read_json(profile_path)
            if data:
                return UserProfile(**data)
            return None
        except Exception as e:
            logger.error(f"Failed to load user {user_id}: {e}")
            return None

    # =========================================================================
    # Conversation Session Management
    # =========================================================================

    def list_conversations(self, user_id: str) -> List[ConversationSummaryItem]:
        """Lists all conversations owned by the user, ordered by last update (newest first)."""
        conv_dir = self._get_conversations_dir(user_id)
        if not conv_dir.exists():
            return []

        summaries = []
        with self._lock:
            for file_path in conv_dir.glob("*.json"):
                if file_path.name.startswith(".tmp_"):
                    continue
                try:
                    data = self._read_json(file_path)
                    if not data:
                        continue
                    session = ConversationSession(**data)
                    preview = ""
                    if session.messages:
                        last_msg = session.messages[-1].content
                        preview = (last_msg[:90] + "...") if len(last_msg) > 90 else last_msg

                    summaries.append(
                        ConversationSummaryItem(
                            session_id=session.session_id,
                            title=session.title,
                            message_count=len(session.messages),
                            created_at=session.created_at,
                            updated_at=session.updated_at,
                            preview=preview,
                            has_summary=bool(session.rolling_summary),
                        )
                    )
                except Exception as e:
                    logger.warning(f"Skipping corrupted conversation file {file_path.name}: {e}")

        # Sort descending by updated_at
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    def get_conversation(self, user_id: str, session_id: str) -> Optional[ConversationSession]:
        """
        Retrieves a complete conversation session.
        Enforces strict user ownership: cannot access sessions of another user.
        """
        clean_session = re.sub(r"[^a-zA-Z0-9_\-]", "", session_id)
        if clean_session != session_id:
            raise StorageSecurityError(f"Access denied: Illegal characters or path traversal attempt in session_id '{session_id}'.")
        conv_dir = self._get_conversations_dir(user_id)
        file_path = self._validate_safe_path(conv_dir / f"{clean_session}.json", conv_dir)

        data = self._read_json(file_path)
        if not data:
            return None

        session = ConversationSession(**data)
        # Double check owner ID matches
        if session.user_id != user_id:
            logger.critical(f"IDOR violation attempt! User '{user_id}' tried to read session '{session_id}' of owner '{session.user_id}'")
            return None

        return session

    def create_conversation(self, user_id: str, title: str = "New Conversation") -> ConversationSession:
        """Creates a new empty conversation session for the user."""
        conv_dir = self._get_conversations_dir(user_id)
        conv_dir.mkdir(parents=True, exist_ok=True)

        session = ConversationSession(
            user_id=user_id,
            title=title.strip() or "New Conversation",
            messages=[],
        )

        file_path = conv_dir / f"{session.session_id}.json"
        with self._lock:
            self._atomic_write_json(file_path, session.model_dump())
        logger.info(f"Created conversation '{session.session_id}' for user '{user_id}'")
        return session

    def save_message(self, user_id: str, session_id: str, message: ChatMessage) -> Optional[ConversationSession]:
        """Appends a new turn and updates the session atomically."""
        with self._lock:
            session = self.get_conversation(user_id, session_id)
            if not session:
                # If session doesn't exist, create it
                session = self.create_conversation(user_id=user_id, title=message.content[:45] or "New Chat")

            # Auto-title if it's the first user message and title is default
            if message.role == "user" and (session.title in ("New Conversation", "New Chat") or len(session.messages) == 0):
                first_line = message.content.strip().split("\n")[0]
                session.title = (first_line[:48] + "...") if len(first_line) > 48 else first_line

            session.messages.append(message)
            session.updated_at = time.time()

            conv_dir = self._get_conversations_dir(user_id)
            file_path = conv_dir / f"{session.session_id}.json"
            self._atomic_write_json(file_path, session.model_dump())
            return session

    def update_rolling_summary(self, user_id: str, session_id: str, summary_text: str, pruned_turns: int) -> bool:
        """Updates the rolling summary and accumulated pruned turns count."""
        with self._lock:
            session = self.get_conversation(user_id, session_id)
            if not session:
                return False

            session.rolling_summary = summary_text.strip()
            session.pruned_turns_count += pruned_turns
            session.updated_at = time.time()

            conv_dir = self._get_conversations_dir(user_id)
            file_path = conv_dir / f"{session.session_id}.json"
            self._atomic_write_json(file_path, session.model_dump())
            logger.info(f"Updated rolling summary for session {session_id} (pruned {pruned_turns} turns).")
            return True

    def rename_conversation(self, user_id: str, session_id: str, new_title: str) -> bool:
        """Renames a conversation session with ownership check."""
        clean_title = new_title.strip()
        if not clean_title:
            return False

        with self._lock:
            session = self.get_conversation(user_id, session_id)
            if not session:
                return False

            session.title = clean_title
            session.updated_at = time.time()

            conv_dir = self._get_conversations_dir(user_id)
            file_path = conv_dir / f"{session.session_id}.json"
            self._atomic_write_json(file_path, session.model_dump())
            return True

    def delete_conversation(self, user_id: str, session_id: str) -> bool:
        """Permanently deletes a conversation file with strict ownership check."""
        with self._lock:
            session = self.get_conversation(user_id, session_id)
            if not session:
                return False

            clean_session = re.sub(r"[^a-zA-Z0-9_\-]", "", session_id)
            conv_dir = self._get_conversations_dir(user_id)
            file_path = conv_dir / f"{clean_session}.json"
            if file_path.exists():
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted conversation {session_id} for user {user_id}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to delete {file_path}: {e}")
                    return False
            return False

    def export_conversation(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Exports a conversation thread as an audit-grade JSON payload."""
        session = self.get_conversation(user_id, session_id)
        if not session:
            return None
        payload = session.model_dump()
        payload["exported_at"] = time.time()
        payload["export_source"] = "HUDCO Bot Enterprise Storage"
        return payload

    def import_conversation(self, user_id: str, data: Dict[str, Any]) -> Optional[ConversationSession]:
        """Imports an external conversation JSON into the user's isolated workspace."""
        try:
            # Re-key session to avoid ID collision and force ownership to importing user
            messages_raw = data.get("messages", [])
            messages = [ChatMessage(**m) for m in messages_raw]

            session = ConversationSession(
                user_id=user_id,
                title=f"[Imported] {data.get('title', 'Restored Chat')}",
                messages=messages,
                rolling_summary=data.get("rolling_summary"),
                pruned_turns_count=data.get("pruned_turns_count", 0),
            )

            conv_dir = self._get_conversations_dir(user_id)
            file_path = conv_dir / f"{session.session_id}.json"
            with self._lock:
                self._atomic_write_json(file_path, session.model_dump())
            return session
        except Exception as e:
            logger.error(f"Failed to import conversation for {user_id}: {e}")
            return None


# Global singleton instance
_GLOBAL_STORAGE: Optional[FileConversationStorage] = None


def get_conversation_storage() -> FileConversationStorage:
    global _GLOBAL_STORAGE
    if _GLOBAL_STORAGE is None:
        _GLOBAL_STORAGE = FileConversationStorage()
    return _GLOBAL_STORAGE

