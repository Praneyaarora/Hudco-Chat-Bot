"""
Table Linearization Module for Layer 4 Retrieval.
File: pipeline/retrieval/table_linearizer.py

Converts 2D StructuredTable matrices into search-optimized textual representations
that explicitly bind column headers, row labels, metric values, and units of measure.
"""

from typing import List
from pipeline.core.contracts import StructuredTable


def linearize_table(table: StructuredTable) -> str:
    """
    Produces a search-optimized textual representation of a StructuredTable.
    
    For each data row:
    - Binds the row label (first column or particulars) with every column header and cell value.
    - Annotates with table caption and unit of measure (e.g. '₹ in Crore').
    
    Example output lines:
      [Table: FINANCIAL HIGHLIGHTS | Unit: ₹ in Crore]
      Revenue from Operations | 2021-22: 6,954.08 | 2022-23: 7,049.46 | 2025-26: 13,150.40
    """
    if not table.rows:
        return ""

    lines: List[str] = []
    
    # Header descriptor line
    caption_part = f"Table: {table.caption}" if table.caption else f"Table: {table.table_id}"
    unit_part = f"Unit: {table.unit_of_measure}" if table.unit_of_measure else ""
    meta_header = " | ".join(part for part in [caption_part, unit_part] if part)
    if meta_header:
        lines.append(f"[{meta_header}]")

    headers = table.headers or []
    
    for row in table.rows:
        if not row:
            continue
        
        # Row label is typically the first non-empty cell (e.g. Particulars / Metric)
        row_label = row[0].strip() if len(row) > 0 else ""
        row_pairs: List[str] = []
        
        for col_idx in range(1, len(row)):
            val = row[col_idx].strip()
            if not val:
                continue
            col_name = headers[col_idx].strip() if col_idx < len(headers) else f"Col{col_idx}"
            row_pairs.append(f"{col_name}: {val}")
        
        if row_label and row_pairs:
            line = f"{row_label} | " + " | ".join(row_pairs)
            if table.unit_of_measure:
                line += f" ({table.unit_of_measure})"
            lines.append(line)
        elif row_pairs:
            lines.append(" | ".join(row_pairs))
        elif row_label:
            lines.append(row_label)

    return "\n".join(lines)


def build_searchable_chunk_text(
    content: str,
    structured_tables: List[StructuredTable],
    section_title: str = "",
    ancestor_headings: List[str] = None,
    associated_text: str = ""
) -> str:
    """
    Constructs the combined searchable representation for a CanonicalChunk.
    Includes:
    1. Ancestor section breadcrumbs (e.g. 'Financial Statements > Standalone')
    2. Primary chunk content (narrative or markdown table)
    3. Associated directory or companion contact attributes (if applicable)
    4. Linearized table lines for deep column-row-cell lexical binding
    """
    parts: List[str] = []

    # 1. Section hierarchy breadcrumbs (with deduplication)
    breadcrumbs = []
    if ancestor_headings:
        for h in ancestor_headings:
            if h and (not breadcrumbs or breadcrumbs[-1] != h):
                breadcrumbs.append(h)
    if section_title and section_title not in breadcrumbs:
        breadcrumbs.append(section_title)
    if breadcrumbs:
        parts.append("Section: " + " > ".join(breadcrumbs))

    # 2. Primary text content
    if content:
        parts.append(content)

    # 3. Associated contact or companion directory text
    if associated_text:
        parts.append(associated_text)

    # 4. Linearized table content for structured tables
    if structured_tables:
        for st in structured_tables:
            lin = linearize_table(st)
            if lin:
                parts.append(lin)

    return "\n\n".join(parts)

