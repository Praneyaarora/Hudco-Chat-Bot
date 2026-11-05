"""
Pipeline Utilities Module.
Exposes conservative text normalization and structured table formatting.
"""

from .text_normalizer import (
    normalize_whitespace,
    normalize_text,
    clean_cell_text,
    is_empty_or_whitespace,
)
from .table_formatter import (
    build_structured_table,
    format_matrix_to_gfm,
    detect_unit_of_measure,
    is_probable_header_row,
)

__all__ = [
    "normalize_whitespace",
    "normalize_text",
    "clean_cell_text",
    "is_empty_or_whitespace",
    "build_structured_table",
    "format_matrix_to_gfm",
    "detect_unit_of_measure",
    "is_probable_header_row",
]
