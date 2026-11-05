"""
Conservative, Non-Destructive Text Normalization Utility.
File: pipeline/utils/text_normalizer.py

Normalizes whitespace, line breaks, and Unicode space anomalies without altering
substantive financial figures, dates, legal clauses, table contents, or authentic
Unicode punctuation (em-dashes, en-dashes, curly quotes, currency symbols).
Whitespace normalization is strictly separated from optional punctuation transformations.
"""

import re
from typing import Optional


# Unicode whitespace mapping to ASCII space:
# \u00a0 = Non-breaking space
# \u2000-\u200a = En quad, em quad, en space, em space, thin space, hair space
# \u202f = Narrow no-break space
# \u205f = Medium mathematical space
# \u3000 = Ideographic space
UNICODE_WHITESPACE_REGEX = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]")

# Optional punctuation mapping (used ONLY when explicitly requested)
OPTIONAL_PUNCTUATION_MAP = {
    "\u2018": "'",  # Left single quote
    "\u2019": "'",  # Right single quote / apostrophe
    "\u201a": "'",  # Single low-9 quote
    "\u201b": "'",  # Single high-reversed-9 quote
    "\u201c": '"',  # Left double quote
    "\u201d": '"',  # Right double quote
    "\u201e": '"',  # Double low-9 quote
    "\u2013": "-",  # En-dash
    "\u2014": "--", # Em-dash
    "\u2026": "...", # Ellipsis
}

# Regex to collapse multiple horizontal spaces/tabs
HORIZONTAL_WHITESPACE_REGEX = re.compile(r"[ \t]+")

# Regex to collapse 3 or more newlines to standard paragraph break (\n\n)
EXCESSIVE_NEWLINES_REGEX = re.compile(r"\n{3,}")


# Legacy Indian Rupee font artifact: In fonts like MCDPKF+RupeeForadian, the Rupee symbol ₹
# is encoded as ASCII 96 (backtick `). Normalize this artifact when used in currency declarations.
RUPEE_FONT_BACKTICK_REGEX = re.compile(
    r"`(?=\s*(?:in\s+(?:crores?|cr\.?|lakhs?|thousands?|millions?|billions?)|[0-9]))",
    re.IGNORECASE
)


def normalize_whitespace(text: Optional[str]) -> str:
    """
    Performs purely conservative whitespace normalization:
    - Standardizes line endings (\r\n and \r to \n).
    - Normalizes Unicode space characters (NBSP, narrow NBSP, thin space) to standard ASCII space.
    - Normalizes legacy Rupee font artifacts (backtick ` representing ₹ in RupeeForadian fonts).
    - Collapses multiple horizontal spaces/tabs on each line to a single space.
    - Collapses 4+ newlines to a standard double newline paragraph break (\n\n).
    - Trims leading and trailing whitespace.

    GUARANTEE: Preserves 100% of authentic Unicode punctuation (em-dashes, en-dashes,
    curly quotes, bullets), currency symbols (₹, $, €, £), numbers, dates, and legal clauses.
    """
    if not text:
        return ""

    # 1. Normalize line endings
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Normalize Unicode whitespace anomalies to standard space
    normalized = UNICODE_WHITESPACE_REGEX.sub(" ", normalized)

    # 3. Normalize legacy Rupee font artifacts (backtick ` representing ₹ in RupeeForadian fonts)
    normalized = RUPEE_FONT_BACKTICK_REGEX.sub("\u20b9", normalized)

    # 3. Collapse runs of horizontal whitespace (spaces, tabs) per line
    lines = normalized.split("\n")
    cleaned_lines = [HORIZONTAL_WHITESPACE_REGEX.sub(" ", line).strip() for line in lines]
    normalized = "\n".join(cleaned_lines)

    # 4. Collapse excessive vertical blank lines (4+ newlines to \n\n)
    normalized = EXCESSIVE_NEWLINES_REGEX.sub("\n\n", normalized)

    return normalized.strip()


def normalize_text(
    text: Optional[str],
    standardize_punctuation: bool = False
) -> str:
    """
    Default text normalization function.
    By default, applies only conservative whitespace normalization (standardize_punctuation=False).
    Only maps typographic quotes/dashes if standardize_punctuation is explicitly enabled.
    """
    if not text:
        return ""

    normalized = normalize_whitespace(text)

    if standardize_punctuation:
        for orig, repl in OPTIONAL_PUNCTUATION_MAP.items():
            if orig in normalized:
                normalized = normalized.replace(orig, repl)

    return normalized


def clean_cell_text(cell: Optional[str]) -> str:
    """
    Normalizes a single table cell string:
    - Replaces internal linebreaks with spaces.
    - Standardizes whitespace.
    - Preserves all Unicode text and numbers intact.
    - Returns empty string if None.
    """
    if cell is None:
        return ""
    text = UNICODE_WHITESPACE_REGEX.sub(" ", str(cell))
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = HORIZONTAL_WHITESPACE_REGEX.sub(" ", text)
    return text.strip()


def is_empty_or_whitespace(text: Optional[str]) -> bool:
    """Checks whether a string is None, empty, or consists only of whitespace."""
    if text is None:
        return True
    return len(text.strip()) == 0
