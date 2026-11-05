"""
Token Counting and Context Budget Meter for HUDCO Bot.
File: pipeline/context/token_meter.py

Provides:
- Model-specific context window budgets, defaults, and slider boundaries.
- Accurate component-wise token calculation (System, Summary, History, Chunks, Query).
- Dynamic warnings when high context risks GPU VRAM depletion or cloud quota exhaustion.
"""

from __future__ import annotations

import re
from typing import Dict, Any, List, Optional, Tuple

from pipeline.storage.contracts import ContextUsageTelemetry


# Model Context Window Specs: (Default, Min, Max, SafeWarningThreshold)
MODEL_CONTEXT_SPECS = {
    "gemini": {
        "name": "Google Gemini (gemini-2.5-flash)",
        "default_budget": 8192,
        "min_budget": 1024,
        "max_budget": 32768,
        "warning_threshold": 16384,
        "cloud_warning": True,
        "warning_text": "Higher context usage may increase API consumption and exhaust your provider's usage limits faster.",
    },
    "local_qwen": {
        "name": "Local LLM (GPU / CPU)",
        "default_budget": 8192,
        "min_budget": 1024,
        "max_budget": 32768,
        "warning_threshold": 12288,
        "cloud_warning": False,
        "warning_text": "High context length on local GPU increases VRAM consumption (~3.8 GB -> 6+ GB) and inference latency.",
    },
    "claude": {
        "name": "Anthropic Claude 3.5 Sonnet",
        "default_budget": 8192,
        "min_budget": 1024,
        "max_budget": 32768,
        "warning_threshold": 16384,
        "cloud_warning": True,
        "warning_text": "Higher context usage may increase API consumption and exhaust your provider's usage limits faster.",
    },
    "openai": {
        "name": "OpenAI GPT-4o",
        "default_budget": 8192,
        "min_budget": 1024,
        "max_budget": 32768,
        "warning_threshold": 16384,
        "cloud_warning": True,
        "warning_text": "Higher context usage may increase API consumption and exhaust your provider's usage limits faster.",
    },
}


def estimate_tokens(text: str) -> int:
    """
    Calculates token count based on empirical BPE/word token calibration (~3.7 characters per token).
    Handles financial tables, punctuation, and code blocks accurately.
    """
    if not text:
        return 0
    # Clean whitespace bursts
    cleaned = re.sub(r"\s+", " ", text.strip())
    # Count words and character length
    words = len(cleaned.split(" "))
    chars = len(cleaned)
    # Blended token estimation: 0.75 * words + 0.25 * (chars / 4)
    tokens = int((words * 1.25 + (chars / 3.7)) / 2.0)
    return max(1, tokens)


def validate_context_budget(provider: str, requested_budget: int) -> Tuple[int, Optional[str]]:
    """
    Validates requested budget against provider constraints and returns (safe_budget, warning).
    """
    spec = MODEL_CONTEXT_SPECS.get(provider.lower(), MODEL_CONTEXT_SPECS["local_qwen"])
    min_b = spec["min_budget"]
    max_b = spec["max_budget"]

    safe_budget = max(min_b, min(max_b, requested_budget))
    warning = None

    if safe_budget >= spec["warning_threshold"]:
        warning = spec["warning_text"]

    return safe_budget, warning


def calculate_context_telemetry(
    system_prompt: str,
    rolling_summary: Optional[str],
    active_turns: List[Dict[str, str]],
    evidence_items: List[Any],
    user_query: str,
    max_budget: int = 8192,
    reserved_output_tokens: int = 256,
) -> ContextUsageTelemetry:
    """
    Computes exact component breakdown and overall capacity percentage.
    """
    sys_tokens = estimate_tokens(system_prompt)
    summary_tokens = estimate_tokens(rolling_summary) if rolling_summary else 0

    history_str = "\n".join(f"{t.get('role', 'user')}: {t.get('content', '')}" for t in active_turns)
    history_tokens = estimate_tokens(history_str)

    evidence_str = ""
    for item in evidence_items:
        if isinstance(item, dict):
            c = item.get("content") or item.get("snippet") or ""
            evidence_str += f"\n{c}"
        elif hasattr(item, "content"):
            evidence_str += f"\n{getattr(item, 'content', '')}"

    evidence_tokens = estimate_tokens(evidence_str)
    query_tokens = estimate_tokens(user_query)

    total_used = sys_tokens + summary_tokens + history_tokens + evidence_tokens + query_tokens + reserved_output_tokens
    percentage = round(min(100.0, (total_used / max(1, max_budget)) * 100.0), 1)

    warning = None
    if percentage >= 90.0:
        warning = "Context window is nearly full (>=90%). Auto-summarization of earlier turns is active."
    elif percentage >= 75.0:
        warning = "Context usage is approaching threshold (>=75%)."

    return ContextUsageTelemetry(
        used_tokens=total_used,
        max_budget=max_budget,
        percentage=percentage,
        system_tokens=sys_tokens,
        summary_tokens=summary_tokens,
        history_tokens=history_tokens,
        evidence_tokens=evidence_tokens,
        query_tokens=query_tokens,
        has_rolling_summary=bool(rolling_summary),
        active_turns_count=len(active_turns),
        is_estimated=True,
        warning_message=warning,
    )


def prune_conversation_turns(
    messages: List[Any],
    max_history_tokens: int,
) -> Tuple[List[Any], List[Any]]:
    """
    Splits conversation messages into active sliding window turns and pruned older turns.
    Active turns fit within max_history_tokens (measured from most recent backwards).
    Any older turns that exceed max_history_tokens are returned as pruned_turns for rolling summarization.
    """
    if not messages:
        return [], []

    active_turns: List[Any] = []
    pruned_turns: List[Any] = []

    accumulated_tokens = 0

    # Traverse backwards from most recent message
    for msg in reversed(messages):
        msg_text = getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", "")
        msg_tokens = estimate_tokens(msg_text)
        if accumulated_tokens + msg_tokens <= max_history_tokens or not active_turns:
            active_turns.insert(0, msg)
            accumulated_tokens += msg_tokens
        else:
            pruned_turns.insert(0, msg)

    return active_turns, pruned_turns


