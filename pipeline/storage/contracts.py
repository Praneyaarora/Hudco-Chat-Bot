"""
Data Contracts for User Authentication and Persistent Conversation Storage.
File: pipeline/storage/contracts.py
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """User account record persisted in user directory."""
    user_id: str = Field(default_factory=lambda: f"user_{uuid.uuid4().hex[:12]}")
    email: str
    username: str
    password_hash: str
    role: str = "analyst"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def to_public(self) -> UserProfilePublic:
        return UserProfilePublic(
            user_id=self.user_id,
            email=self.email,
            username=self.username,
            role=self.role,
            created_at=self.created_at,
        )


class UserProfilePublic(BaseModel):
    """Safe user profile for client consumption (zero credentials exposed)."""
    user_id: str
    email: str
    username: str
    role: str
    created_at: float


class ChatMessage(BaseModel):
    """Single message turn in a conversation."""
    message_id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    timestamp: float = Field(default_factory=time.time)
    token_count: int = 0
    evidence_payload: List[Dict[str, Any]] = Field(default_factory=list)
    provider_used: Optional[str] = None
    model_name: Optional[str] = None


class ConversationSession(BaseModel):
    """Full persistent conversation thread with rolling summary and messages."""
    schema_version: str = "1.0"
    session_id: str = Field(default_factory=lambda: f"conv_{uuid.uuid4().hex[:12]}")
    user_id: str
    title: str = "New Conversation"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    messages: List[ChatMessage] = Field(default_factory=list)
    rolling_summary: Optional[str] = None
    pruned_turns_count: int = 0


class ConversationSummaryItem(BaseModel):
    """Brief metadata for conversation listing in sidebar."""
    session_id: str
    title: str
    message_count: int
    created_at: float
    updated_at: float
    preview: str = ""
    has_summary: bool = False


class ContextUsageTelemetry(BaseModel):
    """Real-time token and context budget metrics."""
    used_tokens: int
    max_budget: int
    percentage: float
    system_tokens: int = 0
    summary_tokens: int = 0
    history_tokens: int = 0
    evidence_tokens: int = 0
    query_tokens: int = 0
    has_rolling_summary: bool = False
    active_turns_count: int = 0
    pruned_turns_count: int = 0
    is_estimated: bool = False
    warning_message: Optional[str] = None

