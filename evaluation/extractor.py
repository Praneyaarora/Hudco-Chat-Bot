"""
Document Extraction Module for HUDCO Evaluation Harness.
Extracts text page-by-page from raw and section PDFs, preserving physical PDF
page numbers (1-based) and detecting verified printed page numbers.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pypdf

from evaluation.config import (
    RAW_PDF_PATH,
    SECTIONS_DIR,
    STAGE1_MANIFEST_PATH,
    EXTRACTED_PAGES_FILE,
    EXTRACTION_SUMMARY_FILE,
    MIN_PAGE_CHAR_WARN,
    init_eval_directories,
)
from evaluation.schemas import PageExtractionRecord

logger = logging.getLogger("EvaluationExtractor")

# Regex pattern to match running headers/footers with printed page numbers
# Examples: "18     |   ANNUAL REPORT 2025-26" or "ANNUAL REPORT 2025-26   |      19"
PRINTED_PAGE_REGEX = re.compile(
    r"(?:^|\n)\s*(?:(\d{1,4})\s*\|\s*ANNUAL REPORT|ANNUAL REPORT[^\n|]*\|\s*(\d{1,4}))\s*(?:$|\n)",
    re.IGNORECASE | re.MULTILINE,
)

# Common indicators of tabular data in HUDCO annual report
TABLE_INDICATORS = [
    re.compile(r"\b(?:particulars|balance sheet|profit and loss|cash flow)\b", re.IGNORECASE),
    re.compile(r"\b(?:rs\.?\s*in\s*crore|`\s*in\s*crore|in\s*lakhs)\b", re.IGNORECASE),
    re.compile(r"\b(?:as at|for the year ended|note no\.?)\b", re.IGNORECASE),
    re.compile(r"\b(?:\d{4}-\d{2,4}\s+\d{4}-\d{2,4})\b"),  # e.g. "2024-25 2023-24"
    re.compile(r"(?:\d+[\.,]\d+\s+){2,}\d+[\.,]\d+"),       # Multiple tabular numbers in a row
]


def detect_printed_page(raw_text: str) -> Optional[int]:
    """Detects printed page number from running header/footer text."""
    if not raw_text:
        return None
    match = PRINTED_PAGE_REGEX.search(raw_text)
    if match:
        p_str = match.group(1) or match.group(2)
        try:
            return int(p_str)
        except (ValueError, TypeError):
            return None
    return None


def detect_table(raw_text: str) -> bool:
    """Checks if the page text contains tabular structures or financial metrics."""
    if not raw_text:
        return False
    hits = sum(1 for pattern in TABLE_INDICATORS if pattern.search(raw_text))
    return hits >= 2 or (hits >= 1 and len(re.findall(r"\b\d+[\.,]\d+\b", raw_text)) >= 4)


def load_section_manifest() -> List[Dict[str, Any]]:
    """Loads section boundary plan from Stage 1 manifest, or falls back to known defaults."""
    if STAGE1_MANIFEST_PATH.exists():
        with open(STAGE1_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("sections", {}).get("items", [])
    logger.warning("Stage 1 manifest not found. Falling back to default section catalog.")
    return []


def extract_page_text(page: pypdf.PageObject) -> str:
    """Extracts raw text from a pypdf PageObject."""
    try:
        return page.extract_text() or ""
    except Exception as e:
        logger.warning(f"Failed extracting text: {e}")
        return ""


def clean_page_text(text: str) -> str:
    """Performs non-destructive normalization: trims whitespace and standardizes line breaks."""
    if not text:
        return ""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 4+ newlines to double newline
    text = re.sub(r"\n{4,}", "\n\n", text)
    return text.strip()


class EvaluationDocumentExtractor:
    """Extracts all 520 pages of ar26.pdf (including front matter pages 1-19)."""

    def __init__(self, raw_pdf_path: Path = RAW_PDF_PATH):
        self.raw_pdf_path = raw_pdf_path
        self.manifest_sections = load_section_manifest()
        init_eval_directories()

    def _build_page_section_map(self, total_pages: int) -> Dict[int, Tuple[str, str]]:
        """Maps each physical page index (1..total_pages) to (section_id, section_title)."""
        mapping: Dict[int, Tuple[str, str]] = {}

        # 1. Map physical pages 1-19 to Front Matter & Contents
        for p in range(1, 20):
            mapping[p] = ("sec_00", "Front Matter & Contents")

        # 2. Map sections from Stage 1 manifest
        for sec in self.manifest_sections:
            sec_id = sec.get("section_id", "sec_unknown")
            title = sec.get("title", "Unknown Section")
            p_start = sec.get("physical_page_start", 1)
            p_end = sec.get("physical_page_end", total_pages)
            for p in range(p_start, p_end + 1):
                mapping[p] = (sec_id, title)

        # 3. Default any uncovered pages
        for p in range(1, total_pages + 1):
            if p not in mapping:
                mapping[p] = ("sec_unmapped", "Unmapped Section")

        return mapping

    def extract_all(self, document_id: str = "HUDCO_AR_2025_26_c412ce14") -> List[PageExtractionRecord]:
        """
        Executes page-by-page extraction over the entire source PDF.
        Returns a list of PageExtractionRecord instances.
        """
        if not self.raw_pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found at: {self.raw_pdf_path}")

        logger.info(f"Opening source PDF: {self.raw_pdf_path}")
        reader = pypdf.PdfReader(str(self.raw_pdf_path))
        total_pages = len(reader.pages)
        page_section_map = self._build_page_section_map(total_pages)

        records: List[PageExtractionRecord] = []
        empty_count = 0
        short_count = 0
        table_count = 0

        for p_idx in range(total_pages):
            phys_page = p_idx + 1
            sec_id, sec_title = page_section_map.get(phys_page, ("sec_unknown", "Unknown"))

            raw_text = extract_page_text(reader.pages[p_idx])
            cleaned_text = clean_page_text(raw_text)
            char_count = len(cleaned_text)

            printed_page = detect_printed_page(raw_text)
            has_table = detect_table(cleaned_text)
            is_empty = (char_count == 0)
            is_short = (0 < char_count < MIN_PAGE_CHAR_WARN)

            warnings: List[str] = []
            if is_empty:
                warnings.append("EMPTY_PAGE: No embedded text found (likely image/scanned or blank)")
                empty_count += 1
            elif is_short:
                warnings.append(f"SHORT_PAGE: Under {MIN_PAGE_CHAR_WARN} chars (likely photo spread or divider)")
                short_count += 1

            if has_table:
                warnings.append("TABLE_DETECTED: Page contains financial tabular structures")
                table_count += 1

            rec = PageExtractionRecord(
                document_id=document_id,
                source_filename=self.raw_pdf_path.name,
                section_id=sec_id,
                section_title=sec_title,
                physical_page=phys_page,
                printed_page=printed_page,
                char_count=char_count,
                is_empty=is_empty,
                is_suspiciously_short=is_short,
                has_table=has_table,
                text=cleaned_text,
                warnings=warnings,
            )
            records.append(rec)

        # Save extracted pages to JSONL
        with open(EXTRACTED_PAGES_FILE, "w", encoding="utf-8") as f:
            for r in records:
                f.write(r.model_dump_json() + "\n")

        # Save summary report
        summary = {
            "source_file": str(self.raw_pdf_path),
            "document_id": document_id,
            "total_physical_pages": total_pages,
            "empty_pages": empty_count,
            "suspiciously_short_pages": short_count,
            "table_pages": table_count,
            "pages_with_detected_printed_label": sum(1 for r in records if r.printed_page is not None),
            "sections_covered": len(set(r.section_id for r in records)),
            "extracted_pages_file": str(EXTRACTED_PAGES_FILE),
        }
        with open(EXTRACTION_SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info(
            f"Extraction complete: {total_pages} pages extracted "
            f"({empty_count} empty, {short_count} short, {table_count} tables)."
        )
        return records
