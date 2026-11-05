"""
Deterministic Document Fingerprinter.
Extracts content-derived and filename-derived identity hints without LLM overhead.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from pypdf import PdfReader

logger = logging.getLogger(__name__)

class DocumentFingerprinter:
    """Extracts structural and semantic identity hints from PDF metadata and initial pages."""

    FY_REGEX = re.compile(r"(?:FY|financial year)?\s*(?:20\d{2}[-–]\d{2,4}|20\d{2})", re.IGNORECASE)
    EDITION_REGEX = re.compile(r"(\d+(?:st|nd|rd|th))\s+annual\s+report", re.IGNORECASE)
    AR_TITLE_REGEX = re.compile(r"(\d+(?:st|nd|rd|th)\s+annual\s+report(?:\s+\d{4}[-–]\d{2,4})?)", re.IGNORECASE)

    @classmethod
    def fingerprint(
        cls,
        pdf_path: str,
        received_filename: str,
        source_url: Optional[str] = None,
        sha256: str = "",
        max_scan_pages: int = 5
    ) -> Dict[str, Any]:
        """
        Inspect initial pages and PDF metadata to extract deterministic document fingerprints.
        """
        reader = PdfReader(pdf_path)
        num_pages = len(reader.pages)

        # 1. PDF Metadata extraction
        raw_meta = reader.metadata or {}
        pdf_meta_title = str(raw_meta.get("/Title") or raw_meta.get("Title") or "").strip()
        pdf_meta_author = str(raw_meta.get("/Author") or raw_meta.get("Author") or "").strip()
        pdf_meta_subject = str(raw_meta.get("/Subject") or raw_meta.get("Subject") or "").strip()

        # 2. Extract text from first N pages
        first_pages_text = []
        scan_limit = min(max_scan_pages, num_pages)
        for i in range(scan_limit):
            try:
                page_text = reader.pages[i].extract_text() or ""
                first_pages_text.append(page_text)
            except Exception as e:
                logger.warning(f"Error extracting text from page {i+1}: {e}")

        combined_text = "\n".join(first_pages_text)

        # 3. Content-derived hints
        content_title_hint = None
        fiscal_year_hint = None
        document_type_hint = "unknown"

        # Check for edition & title in text
        ar_match = cls.AR_TITLE_REGEX.search(combined_text)
        if ar_match:
            content_title_hint = ar_match.group(1).strip()
            document_type_hint = "annual_report"

        # Look for fiscal year in text
        fy_matches = cls.FY_REGEX.findall(combined_text)
        if fy_matches:
            # Clean fiscal year e.g. 2025-26
            for fy in fy_matches:
                clean_fy = re.sub(r"[^\d\-]", "", fy)
                if len(clean_fy) >= 4:
                    fiscal_year_hint = clean_fy
                    break

        if not content_title_hint and "annual report" in combined_text.lower():
            document_type_hint = "annual_report"
            if fiscal_year_hint:
                content_title_hint = f"Annual Report {fiscal_year_hint}"
            else:
                content_title_hint = "HUDCO Annual Report"

        # Fallback to metadata if text had no clear title
        if not content_title_hint and pdf_meta_title:
            content_title_hint = pdf_meta_title

        # 4. Filename-derived hints
        fn_lower = received_filename.lower()
        url_lower = (source_url or "").lower()

        filename_hints = {
            "received_filename": received_filename,
            "url_filename": source_url.split("/")[-1] if source_url else None,
            "suggested_type": "annual_report" if "ar" in fn_lower or "annual" in fn_lower else "document",
            "suggested_year": None
        }

        # Check for numbers in filename like ar26 or 2025-26
        yr_fn_match = re.search(r"(?:ar|report)?(\d{2,4})", fn_lower)
        if yr_fn_match:
            filename_hints["suggested_year"] = yr_fn_match.group(1)

        # 5. Identity conflict detection
        conflicts: List[str] = []
        identity_conflict = False

        if filename_hints["suggested_year"] and fiscal_year_hint:
            # e.g., fn says 26, fiscal_year says 2025-26
            fn_yr = filename_hints["suggested_year"]
            if fn_yr not in fiscal_year_hint and not fiscal_year_hint.endswith(fn_yr):
                conflicts.append(f"Filename year '{fn_yr}' differs from content fiscal year '{fiscal_year_hint}'")
                identity_conflict = True

        # Generate deterministic Canonical Document ID
        short_hash = sha256[:8] if sha256 else "00000000"
        if fiscal_year_hint and document_type_hint == "annual_report":
            clean_fy_str = fiscal_year_hint.replace("-", "_")
            document_id = f"HUDCO_AR_{clean_fy_str}_{short_hash}"
        else:
            document_id = f"HUDCO_DOC_{short_hash}"

        return {
            "document_id": document_id,
            "document_type": document_type_hint,
            "content_title_hint": content_title_hint or "HUDCO Official Publication",
            "fiscal_year_hint": fiscal_year_hint,
            "pdf_metadata": {
                "title": pdf_meta_title,
                "author": pdf_meta_author,
                "subject": pdf_meta_subject,
            },
            "filename_hints": filename_hints,
            "identity_conflict": identity_conflict,
            "conflicts": conflicts,
            "total_pages": num_pages
        }
