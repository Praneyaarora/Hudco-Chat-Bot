"""
Text Cleaning & Normalization Worker.
Removes headers, footers, proxy forms, and legal boilerplate from extracted text.
"""

import re
from typing import List

class TextCleaner:
    """Cleans and standardizes raw extracted text from HUDCO documents."""

    # Patterns to strip
    HEADER_FOOTER_PATTERNS = [
        r"(?i)housing and urban development corporation limited",
        r"(?i)\d+(?:st|nd|rd|th)\s+annual report\s+\d{4}-\d{2,4}",
        r"(?i)page\s+\d+\s+of\s+\d+",
        r"^\s*\d+\s*$",  # Lone page numbers
    ]

    BOILERPLATE_PATTERNS = [
        r"(?i)proxy\s+form.*?attendance\s+slip",
        r"(?i)route\s+map\s+to\s+the\s+venue\s+of\s+agm",
        r"(?i)notice\s+of\s+the\s+\d+(?:st|nd|rd|th)\s+annual\s+general\s+meeting",
    ]

    def __init__(self):
        self._compiled_hf = [re.compile(p, re.MULTILINE) for p in self.HEADER_FOOTER_PATTERNS]
        self._compiled_boilerplate = [re.compile(p, re.DOTALL | re.IGNORECASE) for p in self.BOILERPLATE_PATTERNS]

    def clean_text(self, raw_text: str) -> str:
        """Standardize whitespace and remove repetitive headers/footers."""
        if not raw_text:
            return ""

        cleaned = raw_text

        # Strip header/footer noise
        for pattern in self._compiled_hf:
            cleaned = pattern.sub("", cleaned)

        # Remove excessive blank lines and trailing spaces
        cleaned = re.sub(r"\r\n", "\n", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def is_boilerplate(self, section_text: str) -> bool:
        """Detect if an entire section is non-substantive boilerplate (e.g. Proxy Form)."""
        for pattern in self._compiled_boilerplate:
            if pattern.search(section_text):
                return True
        return False
