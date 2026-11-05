"""
Financial-Aware Lexical Tokenizer for Layer 4 Retrieval.
File: pipeline/retrieval/tokenizer.py

Specialized tokenizer for Indian public-sector financial disclosures.
Handles fiscal year compounds, numeric values with commas, currency terms,
and abbreviations without dropping financial signals.
"""

import re
from typing import List, Set

# Regex pattern matching alphanumeric tokens and financial identifiers
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_₹\u20b9\.\-]+")

# Standard English stopwords (excluding financial/domain terms like 'in', 'as', 'at' when part of phrases)
STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "through", "after", "before",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "this", "that", "these", "those", "it",
    "its", "as", "if", "each", "which", "who", "whom", "what", "where",
    "when", "why", "how", "all", "any", "both", "such", "other",
    "he", "she", "him", "his", "her", "they", "them", "their", "we", "us", "our", "you", "your", "my", "me", "i"
}

# Regex to detect fiscal year pattern e.g. 2025-26 or 2024-2025
FISCAL_YEAR_REGEX = re.compile(r"^(\d{4})-(\d{2,4})$")

# Canonical lemma mapping for financial and corporate terminology (avoids token duplication inflation)
LEMMA_MAP: dict[str, str] = {
    "offices": "office",
    "branches": "branch",
    "reports": "report",
    "statements": "statement",
    "directors": "director",
    "highlights": "highlight",
    "dividends": "dividend",
    "tel": "telephone",
    "phone": "telephone",
    "ph": "telephone",
    "e-mail": "email",
    "appointed": "appoint",
    "appointment": "appoint",
    "appointments": "appoint",
    "appointing": "appoint",
}


def tokenize(text: str) -> List[str]:
    """
    Tokenizes text with financial and numerical normalization.
    
    1. Normalizes commas in numbers (e.g. '13,150.40' -> '13150.40' and '13,150.40').
    2. Splits fiscal year hyphenated strings (e.g. '2025-26' emits '2025-26', '2025', '2026').
    3. Normalizes Rupee symbols ('₹' -> 'rs').
    4. Canonicalizes morphological variants and contact abbreviations (e.g. 'offices' -> 'office', 'tel' -> 'telephone').
    5. Filters common grammatical stopwords.
    """
    if not text:
        return []

    tokens: List[str] = []
    
    # Pre-clean: normalize unicode rupee to 'rs' for consistent keyword matching
    cleaned = text.replace("₹", " rs ").replace("` in crore", " rs in crore ")
    
    # Extract raw candidate words
    raw_words = re.findall(r"[A-Za-z0-9_,\.\-]+", cleaned)

    for word in raw_words:
        w_lower = word.lower().strip(".,;:?!'\"()[]{}")
        if not w_lower or len(w_lower) < 2:
            continue

        # Handle numeric values with commas (e.g. '10,348.50')
        if "," in w_lower and re.match(r"^\d{1,3}(,\d{2,3})+(\.\d+)?$", w_lower):
            uncomma = w_lower.replace(",", "")
            tokens.append(uncomma)
            tokens.append(w_lower)
            continue

        # Handle fiscal year compound (e.g. '2025-26')
        fy_match = FISCAL_YEAR_REGEX.match(w_lower)
        if fy_match:
            y1, y2 = fy_match.groups()
            tokens.append(w_lower)
            tokens.append(y1)
            # Expand 2-digit trailing year to 4-digit if applicable
            if len(y2) == 2 and len(y1) == 4:
                full_y2 = y1[:2] + y2
                tokens.append(full_y2)
            else:
                tokens.append(y2)
            continue



        # Apply canonical lemma mapping
        if w_lower in LEMMA_MAP:
            w_lower = LEMMA_MAP[w_lower]

        if w_lower in STOPWORDS:
            continue

        tokens.append(w_lower)

    return tokens

