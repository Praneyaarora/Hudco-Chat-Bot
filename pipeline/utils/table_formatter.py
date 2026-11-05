"""
Structured Table Formatter and GFM Markdown Builder.
File: pipeline/utils/table_formatter.py

Constructs clean, GitHub-Flavored Markdown tables from 2D cell matrices,
preserves row-column coordinates, detects units of measure as advisory metadata,
distinguishes explicit headers from headless data matrices, and handles
jagged/malformed tables gracefully without fabricating cell content.
"""

import re
from typing import List, Optional, Tuple
from pipeline.core.contracts import StructuredTable
from pipeline.utils.text_normalizer import clean_cell_text


# Unit of measure detection regexes common in Indian financial reports
UNIT_PATTERNS = [
    re.compile(r"(?i)\((?:rs\.?|₹|`|inr)\s+in\s+(?:crores?|cr\.?|lakhs?|millions?|billions?)\)"),
    re.compile(r"(?i)\(in\s+(?:crores?|cr\.?|lakhs?|thousands?|millions?|billions?)\)"),
    re.compile(r"(?i)\b(?:rs\.?|₹|`)\s+in\s+(?:crores?|lakhs?)\b"),
    re.compile(r"(?i)\bpercentage\s*\(%\)\b"),
]


def detect_unit_of_measure(text_or_headers: str) -> Optional[str]:
    """
    Inspects table text or header lines for unit of measure declarations.
    Returns advisory string (e.g. 'Rs. in Crore') or None.
    """
    if not text_or_headers:
        return None
    for pattern in UNIT_PATTERNS:
        match = pattern.search(text_or_headers)
        if match:
            return match.group(0).strip("()")
    return None


YEAR_HEADER_REGEX = re.compile(
    r"^(?:(?:19|20)\d{2}(?:-\d{2,4})?|FY\s*\d{2,4}|Q[1-4]\s*(?:FY)?\d{2,4})$",
    re.IGNORECASE
)


def is_probable_header_row(row: List[str]) -> bool:
    """
    Heuristic to determine if the first row is a genuine header row rather than data.
    Returns False if row is mostly numbers, currency, or empty cells.
    Recognizes financial year/period labels (e.g. '2021-22', 'FY24') as valid headers.
    """
    if not row:
        return False

    non_empty = [c for c in row if len(c.strip()) > 0]
    if not non_empty:
        return False

    # Count cells that look strictly numeric (numbers, decimals, commas, currency)
    numeric_count = 0
    for cell in non_empty:
        c_stripped = cell.strip()
        # Financial period headers (e.g. 2021-22, FY25) are valid column headers, not data numbers
        if YEAR_HEADER_REGEX.match(c_stripped):
            continue
        clean = re.sub(r"[,\.₹\$%\s\-]", "", c_stripped)
        if clean.isdigit() or len(clean) == 0:
            numeric_count += 1

    # If more than 60% of non-period cells are purely numeric, it is likely data, not a header
    if numeric_count / len(non_empty) >= 0.6:
        return False

    return True


def format_matrix_to_gfm(headers: List[str], rows: List[List[str]]) -> str:
    """
    Converts headers and 2D rows into a clean GitHub-Flavored Markdown table (advisory display).
    Escapes pipe characters inside cell values to prevent breaking markdown tables.
    """
    if not headers and not rows:
        return ""

    if not headers and rows:
        num_cols = len(rows[0])
        headers = [f"Column_{i+1}" for i in range(num_cols)]

    num_cols = len(headers)

    # Escape pipes and clean cells in headers
    clean_headers = [h.replace("|", "\\|") for h in headers]
    divider = ["---"] * num_cols

    md_lines = [
        "| " + " | ".join(clean_headers) + " |",
        "| " + " | ".join(divider) + " |",
    ]

    for row in rows:
        clean_row = [str(cell).replace("|", "\\|") for cell in row]
        # Pad row if shorter than header
        if len(clean_row) < num_cols:
            clean_row.extend([""] * (num_cols - len(clean_row)))
        # Truncate if longer than header
        clean_row = clean_row[:num_cols]
        md_lines.append("| " + " | ".join(clean_row) + " |")

    return "\n".join(md_lines)


def build_structured_table(
    raw_matrix: List[List[Optional[str]]],
    table_id: str,
    caption: Optional[str] = None,
    unit_of_measure: Optional[str] = None
) -> Optional[StructuredTable]:
    """
    Constructs an immutable StructuredTable model from a raw 2D string matrix.
    Validates dimensional consistency, distinguishes explicit headers from data,
    pads jagged rows without inventing cell values, and produces GFM markdown.
    """
    if not raw_matrix or len(raw_matrix) < 2:
        return None

    # 1. Clean all cell texts
    cleaned_matrix: List[List[str]] = []
    for raw_row in raw_matrix:
        cleaned_row = [clean_cell_text(cell) for cell in raw_row]
        if any(len(c) > 0 for c in cleaned_row):
            cleaned_matrix.append(cleaned_row)

    if len(cleaned_matrix) < 2:
        return None

    max_cols = max(len(row) for row in cleaned_matrix)
    if max_cols == 0:
        return None

    is_malformed = any(len(row) != max_cols for row in cleaned_matrix)

    # 2. Check if row 0 is a genuine header row
    first_row = cleaned_matrix[0]
    has_explicit_headers = is_probable_header_row(first_row)

    if has_explicit_headers:
        raw_header = first_row
        raw_body = cleaned_matrix[1:]
    else:
        # Headless table: generate synthetic column labels for display, keep all rows as data
        raw_header = [f"Column_{i+1}" for i in range(max_cols)]
        raw_body = cleaned_matrix

    # Pad header to max_cols if needed
    header = list(raw_header)
    if len(header) < max_cols:
        header.extend([f"Column_{i+1}" for i in range(len(header), max_cols)])

    # Pad body rows to max_cols with empty strings
    padded_body: List[List[str]] = []
    for row in raw_body:
        padded_row = list(row)
        if len(padded_row) < max_cols:
            padded_row.extend([""] * (max_cols - len(padded_row)))
        padded_body.append(padded_row[:max_cols])

    # 3. Detect unit of measure (advisory)
    inferred_unit = unit_of_measure
    if not inferred_unit:
        header_text = " ".join(header)
        caption_text = caption or ""
        inferred_unit = detect_unit_of_measure(f"{caption_text} {header_text}")

    # 4. Generate GFM markdown
    gfm_markdown = format_matrix_to_gfm(header, padded_body)

    return StructuredTable(
        table_id=table_id,
        caption=caption,
        unit_of_measure=inferred_unit,
        headers=header,
        rows=padded_body,
        markdown_representation=gfm_markdown,
        has_explicit_headers=has_explicit_headers,
        is_malformed=is_malformed,
        row_count=len(padded_body),
        col_count=max_cols
    )
