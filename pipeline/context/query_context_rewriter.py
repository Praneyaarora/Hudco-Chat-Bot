"""
HUDCO Bot — Contextual & Cross-Lingual Query Rewriter
File: pipeline/context/query_context_rewriter.py

Enriches follow-up questions, Hinglish phrases, and elliptical answers with necessary
conversational entities so that hybrid retrieval (BM25 + Dense Semantic) and Web Search
retrieve high-precision evidence chunks.
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional
from pipeline.storage.contracts import ChatMessage

logger = logging.getLogger("hudco_bot.query_rewriter")

# English & Hinglish pronoun patterns
PRONOUN_PATTERN = re.compile(
    r"\b(it|its|they|them|their|this|that|these|those|there|he|she|his|her|the same|above|mentioned|"
    r"iska|iski|iske|unka|unki|unke|ismein|isme|wahan|vahan|ye|woh|wo|uske|usme)\b",
    re.IGNORECASE
)

# Follow-up starters (English & Hinglish)
FOLLOW_UP_STARTERS = re.compile(
    r"^(and\b|what about\b|how about\b|when was it\b|who was\b|why\b|where is it\b|tell me more\b|also\b|in addition\b|"
    r"aur\b|or\b|kab\b|kahan\b|kaha\b|kaise\b|kitna\b|uska\b|iska\b)",
    re.IGNORECASE
)

# Hinglish intent normalization mappings for semantic/keyword retrieval
INTENT_NORMALIZATIONS = [
    # Grievance / Complaint
    (
        re.compile(r"\b(complaint|shikayat|grievance|complain|dispute|problem)\b", re.IGNORECASE),
        "HUDCO grievance redressal officer complaint contact CPGRAMS portal"
    ),
    # Careers / Jobs
    (
        re.compile(r"\b(job|naukri|career|careers|vacancy|vacancies|recruitment|bharti)\b", re.IGNORECASE),
        "HUDCO recruitment careers apply job vacancies official portal"
    ),
    # Office visit / Location inquiries
    (
        re.compile(r"\b(jana|visit|office|branch|karyalay|pata|address|location)\b", re.IGNORECASE),
        "HUDCO office branch address location contact"
    ),
    # Profits / Financials
    (
        re.compile(r"\b(profit|munafa|kamai|earnings|net worth|pat)\b", re.IGNORECASE),
        "HUDCO Net Profit Profit After Tax Net Worth financial results"
    ),
    # Loans / Disbursements
    (
        re.compile(r"\b(loan|karza|disbursement|sanction|rin)\b", re.IGNORECASE),
        "HUDCO loan sanctions disbursements housing urban infrastructure"
    ),
]


def _get_turn_role(turn: Any) -> str:
    if isinstance(turn, dict):
        return turn.get("role", "")
    return getattr(turn, "role", "")


def _get_turn_content(turn: Any) -> str:
    if isinstance(turn, dict):
        return turn.get("content", "")
    return getattr(turn, "content", "")


class QueryContextRewriter:
    """
    Enriches conversational follow-ups and informal Hinglish queries into canonical,
    self-contained search queries for retrieval.
    """

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    def needs_rewriting(self, query: str, recent_turns: List[ChatMessage]) -> bool:
        """Determines if the query is a follow-up or requires entity augmentation."""
        if not recent_turns:
            return False

        q_strip = query.strip()
        q_lower = q_strip.lower()

        # 1. An explicit pronoun or follow-up starter definitely needs resolution
        if PRONOUN_PATTERN.search(q_strip) or FOLLOW_UP_STARTERS.search(q_strip):
            return True

        # 2. Incomplete elliptical follow-up fragments (e.g. "and loans?", "aur dividend?", "what about 54ec?")
        if any(q_lower.startswith(prefix) for prefix in ["and ", "what about ", "how about ", "also ", "aur ", "or ", "in addition "]):
            return True

        # 3. Location clarification replies (e.g. "Haryana mein", "Gurgaon mein kya?")
        if any(w in q_lower for w in ["haryana", "gurgaon", "gurugram", "chandigarh", "punjab", "delhi", "mumbai", "chennai", "kolkata", "bangalore", "bengaluru", "hyderabad", "lucknow", "patna", "jaipur", "bhopal"]):
            if "hudco" not in q_lower and len(q_strip.split()) <= 4:
                return True

        # If query is a complete grammatically independent question with its own subject
        # (e.g., "who is the head of hr?", "who are the board members?", "what is the share price of hudco?"),
        # NEVER rewrite or contaminate with previous turn's entities.
        return False

    def rewrite_query(
        self,
        current_query: str,
        recent_turns: List[ChatMessage],
        rolling_summary: Optional[str] = None
    ) -> str:
        """
        Produces a standalone, retrieval-optimized search query.
        """
        q_strip = current_query.strip()
        q_lower = q_strip.lower()

        # 1. Check if previous bot response was asking for location clarification
        if recent_turns:
            last_turn = recent_turns[-1]
            last_bot_content = _get_turn_content(last_turn).lower() if _get_turn_role(last_turn) == "assistant" else ""

            # If previous bot response asked for a location / city / state:
            if any(term in last_bot_content for term in ["city or state", "regional office", "registered head office", "sheher ya rajya"]):
                clean_loc = re.sub(r"\b(mein|me|mien|bhi|ka|ki|ke|hai|ha|near)\b", "", q_strip, flags=re.IGNORECASE).strip()
                if clean_loc:
                    rewritten = f"HUDCO regional branch office {clean_loc} location address contact details"
                    logger.info("Clarification location resolved: '%s' -> '%s'", current_query, rewritten)
                    return rewritten

        # 2. Check if query is an informal Hinglish office inquiry with location
        loc_match = re.search(r"\b(haryana|gurgaon|gurugram|chandigarh|punjab|delhi|mumbai|chennai|kolkata|bangalore|bengaluru|hyderabad|lucknow|ahmedabad|patna|jaipur|bhopal|shimla|ranchi|bhubaneswar|dehradun|guwahati|thiruvananthapuram)\b", q_lower)
        if loc_match and any(w in q_lower for w in ["office", "branch", "jana", "visit", "kahan", "kaha", "hai kya", "kaha ha"]):
            city = loc_match.group(1).title()
            rewritten = f"HUDCO regional branch office in {city} address contact location"
            logger.info("Informal Hinglish location query canonicalized: '%s' -> '%s'", current_query, rewritten)
            return rewritten

        # 3. Standard Multi-turn Pronoun & Elliptical Resolution
        if self.needs_rewriting(current_query, recent_turns):
            # Extract core entity from prior user / assistant turns
            stop_words = {
                "what", "is", "the", "are", "of", "and", "in", "to", "for", "a", "an", "hudco",
                "hai", "kya", "ka", "ki", "ke", "tell", "me", "about", "explain", "give", "details",
                "information", "please", "batao", "bataiye", "how", "can", "i", "we", "do", "you",
                "know", "show", "many", "much", "sir", "madam", "who", "whom"
            }

            prior_entity = ""
            # Search backwards through user messages first for the primary topic
            for msg in reversed(recent_turns):
                if _get_turn_role(msg) == "user":
                    words = [re.sub(r"[^\w]", "", w) for w in _get_turn_content(msg).split()]
                    meaningful = [w for w in words if w.lower() not in stop_words and len(w) > 1]
                    if meaningful:
                        prior_entity = " ".join(meaningful[:2])
                        break

            if not prior_entity:
                for msg in reversed(recent_turns):
                    words = [re.sub(r"[^\w]", "", w) for w in _get_turn_content(msg).split()]
                    meaningful = [w for w in words if w.lower() not in stop_words and len(w) > 1]
                    if meaningful:
                        prior_entity = " ".join(meaningful[:2])
                        break

            if prior_entity:
                # If current query contains a pronoun, replace the pronoun directly with the prior entity
                if PRONOUN_PATTERN.search(current_query):
                    rewritten = PRONOUN_PATTERN.sub(prior_entity, current_query, count=1)
                    logger.info("Contextual pronoun resolved: '%s' -> '%s'", current_query, rewritten)
                    return rewritten

                # If current query is an elliptical follow-up starter (e.g. "and loans?", "aur dividend?"):
                if FOLLOW_UP_STARTERS.search(current_query):
                    enhanced = f"{current_query} ({prior_entity})"
                    logger.info("Enhanced elliptical follow-up: '%s' -> '%s'", current_query, enhanced)
                    return enhanced

        # 4. Check for standalone informal Hinglish intents (complaint, careers, financials)
        if "hudco" not in q_lower:
            for pattern, canonical_text in INTENT_NORMALIZATIONS:
                if pattern.search(q_lower):
                    logger.info("Intent normalized: '%s' -> '%s'", current_query, canonical_text)
                    return canonical_text

        return current_query
