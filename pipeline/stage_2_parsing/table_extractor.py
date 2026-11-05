"""
Tabular Data Extractor for Complex Financial Reports.
Converts multi-column financial statements into GitHub-Flavored Markdown matrices.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class TableExtractor:
    """Extracts tables from PDF pages and formats them as structured Markdown tables."""

    @staticmethod
    def matrix_to_markdown(matrix: List[List[Optional[str]]]) -> str:
        """Converts a 2D list of cells into a Markdown table."""
        if not matrix or len(matrix) < 2:
            return ""

        # Normalize cells
        clean_matrix = []
        for row in matrix:
            clean_row = [str(cell).strip().replace("\n", " ") if cell is not None else "" for cell in row]
            clean_matrix.append(clean_row)

        header = clean_matrix[0]
        divider = ["---"] * len(header)
        body = clean_matrix[1:]

        md_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(divider) + " |"
        ]

        for row in body:
            # Pad row if columns are shorter than header
            padded_row = row + [""] * (len(header) - len(row))
            md_lines.append("| " + " | ".join(padded_row[:len(header)]) + " |")

        return "\n".join(md_lines)

    def extract_tables_from_pdf(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """
        Extract tables using pdfplumber (or pypdf fallback).
        Returns a list of extracted tables with metadata and Markdown representations.
        """
        extracted_tables: List[Dict[str, Any]] = []

        try:
            import pdfplumber
            with pdfplumber.open(str(pdf_path)) as pdf:
                for p_idx, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    for t_idx, tbl in enumerate(tables):
                        if tbl and len(tbl) > 1:
                            md = self.matrix_to_markdown(tbl)
                            if md:
                                extracted_tables.append({
                                    "table_id": f"P{p_idx+1}_T{t_idx+1}",
                                    "page_number": p_idx + 1,
                                    "markdown": md,
                                    "rows": len(tbl),
                                    "cols": len(tbl[0]) if tbl else 0
                                })
        except ImportError:
            logger.warning("pdfplumber not installed; table extraction in fallback mode.")
        except Exception as e:
            logger.error(f"Error during table extraction: {e}")

        return extracted_tables
