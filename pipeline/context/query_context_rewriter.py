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
        re.compile(r"\b(job|naukri|career|apply|vacancy|recruitment|bharti)\b", re.IGNORECASE),
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


class QueryContextRewriter:
    """
    Enriches conversational follow-ups and informal Hinglish queries into canonical,
    self-contained search queries for retrieval.
    """

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    def needs_rewriting(self, query: str, recent_turns: List[ChatMessage]) -> bool:
        """Determines if the query is a follow-up or requires entity augmentation."""
        q_strip = query.strip()
        word_count = len(q_strip.split())

        # If it's a short reply (e.g. "Haryana mein", "Gurgaon mein kya?", "aur loans?")
        if recent_turns and word_count <= 6:
            return True

        if recent_turns and (PRONOUN_PATTERN.search(q_strip) or FOLLOW_UP_STARTERS.search(q_strip)):
            return True

        # Check if query mentions a location or office intent informally
        if any(w in q_strip.lower() for w in ["haryana", "gurgaon", "punjab", "chandigarh", "delhi", "bhopal", "patna", "jaipur"]):
            if "hudco" not in q_strip.lower():
                return True

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
            last_bot_content = last_turn.content.lower() if last_turn.role == "assistant" else ""

            # If previous bot response asked for a location / city / state:
            if any(term in last_bot_content for term in ["city or state", "regional office", "registered head office", "sheher ya rajya"]):
                clean_loc = re.sub(r"\b(mein|me|mien|bhi|ka|ki|ke|hai|ha|near)\b", "", q_strip, flags=re.IGNORECASE).strip()
                if clean_loc:
                    rewritten = f"HUDCO regional branch office {clean_loc} location address contact details"
                    logger.info("Clarification location resolved: '%s' -> '%s'", current_query, rewritten)
                    return rewritten

        # 2. Check if query is an informal Hinglish office inquiry with location
        # e.g., "mereko hudco jana ha haryana mien office ha kya?" or "hudco ka office gurgaon mein hai kya?"
        loc_match = re.search(r"\b(haryana|gurgaon|gurugram|chandigarh|punjab|delhi|mumbai|chennai|kolkata|bangalore|bengaluru|hyderabad|lucknow|ahmedabad|patna|jaipur|bhopal|shimla|ranchi|bhubaneswar|dehradun|guwahati|thiruvananthapuram)\b", q_lower)
        if loc_match and any(w in q_lower for w in ["office", "branch", "jana", "visit", "kahan", "kaha", "hai kya", "kaha ha"]):
            city = loc_match.group(1).title()
            rewritten = f"HUDCO regional branch office in {city} address contact location"
            logger.info("Informal Hinglish location query canonicalized: '%s' -> '%s'", current_query, rewritten)
            return rewritten

        # 3. Check for specific informal Hinglish intents (complaint, careers, financials)
        if "hudco" not in q_lower:
            # Check if current turn is asking about complaint, jobs, or profit
            for pattern, canonical_text in INTENT_NORMALIZATIONS:
                if pattern.search(q_lower):
                    logger.info("Intent normalized: '%s' -> '%s'", current_query, canonical_text)
                    return canonical_text

        # 4. Standard Multi-turn Pronoun Resolution
        if not self.needs_rewriting(current_query, recent_turns):
            return current_query

        # Extract last user query and entities
        last_user_query = ""
        for msg in reversed(recent_turns):
            if msg.role == "user":
                last_user_query = msg.content.strip()
                break

        keywords = []
        for word in last_user_query.split():
            clean = re.sub(r"[^\w]", "", word)
            if clean.lower() not in {"what", "is", "the", "are", "of", "and", "in", "to", "for", "a", "an", "hudco", "hai", "kya", "ka", "ki", "ke"}:
                keywords.append(clean)

        topic = " ".join(keywords[:4])
        if topic:
            rewritten = PRONOUN_PATTERN.sub(topic, current_query, count=1)
            if rewritten.lower() != current_query.lower():
                logger.info("Contextually rewritten query: '%s' -> '%s'", current_query, rewritten)
                return rewritten
            enhanced = f"{current_query} ({topic})"
            logger.info("Enhanced follow-up query: '%s' -> '%s'", current_query, enhanced)
            return enhanced

        return current_query
