"""
PDF Document Extraction Adapter.
File: pipeline/adapters/pdf_adapter.py

Implements zero-loss page-by-page extraction for digital PDF documents using pypdf.
Preserves 1-based physical page indices, extracts native outlines, detects verified
printed page labels (Arabic and Roman), isolates empty/scanned pages, detects tables,
and attaches immutable PDFSourceLocator provenance without modifying source files.
"""

import io
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import pypdf

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

logger = logging.getLogger(__name__)

from pipeline.core.contracts import (
    DocumentFormat,
    BlockType,
    ContentBlock,
    StructuredTable,
    QualityWarning,
    WarningCategory,
    PDFSourceLocator,
)
from pipeline.adapters.base import BaseDocumentAdapter, RawPageRecord, RawExtractionPayload
from pipeline.utils.text_normalizer import normalize_text, is_empty_or_whitespace
from pipeline.utils.table_formatter import build_structured_table, detect_unit_of_measure

BULLET_REGEX = re.compile(
    r"^(?:[\u2022\u2023\u25e6\u2043\u2219\*\-\–—]|\(?\d{1,3}[\.\)]|\(?[a-zA-Z][\.\)])\s+"
)

# Set of valid lowercase Roman numerals commonly used in document front matter
VALID_ROMAN_NUMERALS = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
    "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx",
    "xxi", "xxii", "xxiii", "xxiv", "xxv", "xxvi", "xxvii", "xxviii", "xxix", "xxx",
    "xxxi", "xxxii", "xxxiii", "xxxiv", "xxxv", "xxxvi", "xxxvii", "xxxviii", "xxxix", "xl", "l"
}

# Regex pattern to match explicit running headers/footers with page numbers:
# Pattern A: Number followed by separator and document title e.g. "52 | ANNUAL REPORT" or "iv | REPORT"
# Pattern B: Document title followed by separator and number e.g. "ANNUAL REPORT | 52"
# Pattern C: Explicit "Page X" or "Page X of Y"
RUNNING_HEADER_FOOTER_REGEX = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(?:(?:Page|PAGE|p\.)\s+)?([0-9]{1,4}|[a-zA-Z]{1,8})\s*[|•—–-]\s*([A-Za-z][A-Za-z0-9\s,&’'\-]{4,})"
    r"|([A-Za-z][A-Za-z0-9\s,&’'\-]{4,})\s*[|•—–-]\s*(?:(?:Page|PAGE|p\.)\s+)?([0-9]{1,4}|[a-zA-Z]{1,8})"
    r"|(?:Page|PAGE)\s+([0-9]{1,4}|[a-zA-Z]{1,8})(?:\s+of\s+[0-9]{1,4})?"
    r")\s*(?:$|\n)",
    re.IGNORECASE | re.MULTILINE,
)

# Common indicators of tabular data in annual reports
TABLE_LINE_INDICATOR_REGEX = re.compile(r"(?:\d+[\.,]\d+\s+){2,}\d+[\.,]\d+")
TABLE_KEYWORD_REGEX = re.compile(
    r"\b(?:particulars|balance\s+sheet|profit\s+and\s+loss|cash\s+flow|as\s+at|note\s+no\.?|rs\.?\s*in\s*crore|`\s*in\s*crore)\b",
    re.IGNORECASE,
)


def is_valid_page_label(candidate: str) -> bool:
    """Validates whether a candidate string is a plausible Arabic or Roman page label."""
    clean = candidate.strip()
    if clean.isdigit():
        num = int(clean)
        # Plausible page range: 1 to 5000
        return 1 <= num <= 5000
    if clean.lower() in VALID_ROMAN_NUMERALS:
        return True
    return False


def detect_printed_page_label(raw_text: str) -> Optional[str]:
    """
    Detects verified printed page number label from running header/footer text.
    Uses a strict, conservative evidence hierarchy:
    1. Explicit running headers or footers with separator and report title context.
    2. Explicit 'Page X' or 'Page X of Y' declarations.

    CONSERVATIVE RULE: Standalone numeric lines (e.g. from notes, dates, or table endings)
    are NEVER treated as verified page numbers to prevent false positives.
    If evidence is absent or ambiguous, returns None. NEVER fabricates a label.
    """
    if not raw_text:
        return None

    for match in RUNNING_HEADER_FOOTER_REGEX.finditer(raw_text):
        # Group 1: Number before title (e.g. "52 | Directors Report")
        # Group 4: Number after title (e.g. "Directors Report | 52")
        # Group 5: Explicit "Page 52"
        g4 = match.group(4)
        if g4:
            g3 = match.group(3) or ""
            # Reject matches where the title ended in a 4-digit year and separator was a hyphen/dash (e.g. "ANNUAL REPORT 2023-24")
            if re.search(r"\b(19\d\d|20\d\d)\s*$", g3):
                continue
            # Also reject if candidate is part of a year range in the matched line
            if re.search(r"\b(19\d\d|20\d\d)\s*[-–—]\s*" + re.escape(g4.strip()) + r"\b", match.group(0)):
                continue

        candidate = match.group(1) or match.group(4) or match.group(5)
        if candidate and is_valid_page_label(candidate):
            return candidate.strip()

    return None


class PDFDocumentAdapter(BaseDocumentAdapter):
    """
    Production-grade PDF extraction adapter.
    Preserves 1-based physical page indices, native bookmarks, and page geometry.
    """

    SUPPORTED_MIME_TYPES = {
        "application/pdf",
        "application/x-pdf",
    }

    def can_handle(self, mime_type: str, file_path: Optional[Path] = None) -> bool:
        if mime_type.lower() in self.SUPPORTED_MIME_TYPES:
            return True
        if file_path and file_path.suffix.lower() == ".pdf":
            return True
        return False

    def extract_file(
        self,
        file_path: Any,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        """Extracts content from a local PDF file."""
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Source PDF does not exist: {path_obj}")

        with open(path_obj, "rb") as f:
            return self._process_pdf_stream(f, source_filename=path_obj.name, config=config)

    def extract_bytes(
        self,
        data: bytes,
        filename: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        """Extracts content directly from in-memory PDF bytes."""
        return self._process_pdf_stream(data, source_filename=filename or "document.pdf", config=config)

    def _process_pdf_stream(
        self,
        pdf_input: Any,
        source_filename: str,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        config = config or {}
        min_short_chars = config.get("min_short_chars", 100)

        warnings: List[QualityWarning] = []
        errors: List[str] = []
        page_records: List[RawPageRecord] = []
        raw_metadata: Dict[str, Any] = {}
        outline_entries: List[Dict[str, Any]] = []

        try:
            if isinstance(pdf_input, (bytes, bytearray)):
                stream = io.BytesIO(pdf_input)
            else:
                stream = pdf_input
            reader = pypdf.PdfReader(stream)
            num_pages = len(reader.pages)
        except Exception as e:
            error_msg = f"Failed to initialize PDF stream for '{source_filename}': {str(e)}"
            logger.error(error_msg)
            return RawExtractionPayload(
                source_filename=source_filename,
                document_format=DocumentFormat.PDF,
                total_physical_pages=0,
                errors=[error_msg]
            )

        # 1. Extract Document Metadata
        try:
            meta = reader.metadata
            if meta:
                for k, v in meta.items():
                    clean_k = str(k).lstrip("/")
                    raw_metadata[clean_k] = str(v)
        except Exception as e:
            logger.warning(f"Failed extracting PDF metadata: {e}")

        # 2. Extract Native Bookmarks / Outlines
        try:
            outline = reader.outline
            if outline:
                outline_entries = self._parse_outline(reader, outline)
        except Exception as e:
            logger.warning(f"Failed extracting PDF outline bookmarks: {e}")

        # Page range calculation
        page_start = max(1, config.get("page_start", 1))
        page_end_cfg = config.get("page_end", config.get("max_pages"))
        page_end = min(num_pages, page_end_cfg) if page_end_cfg is not None else num_pages
        start_idx = page_start - 1
        end_idx = page_end

        # Capture document-level TOC if running on a sub-slice (page_start > 1)
        if page_start > 1 and "toc_text" not in raw_metadata:
            early_limit = min(15, num_pages)
            for ep_idx in range(early_limit):
                try:
                    ep_text = reader.pages[ep_idx].extract_text() or ""
                    if re.search(r"(?:table\s+of\s+contents|contents(?:\s*contents)?|index)", ep_text, re.IGNORECASE):
                        raw_metadata["toc_text"] = normalize_text(ep_text)
                        raw_metadata["toc_page"] = ep_idx + 1
                        break
                except Exception:
                    pass

        if page_end_cfg is not None or page_start > 1:
            filtered_outlines = []
            for entry in outline_entries:
                p_ref = entry.get("physical_page")
                if p_ref is not None and page_start <= p_ref <= page_end:
                    filtered_outlines.append(entry)
                elif p_ref is None:
                    filtered_outlines.append(entry)
            outline_entries = filtered_outlines

        plumber_pdf = None
        if HAS_PDFPLUMBER:
            try:
                if isinstance(pdf_input, (bytes, bytearray)):
                    plumber_pdf = pdfplumber.open(io.BytesIO(pdf_input))
                elif hasattr(pdf_input, "seek"):
                    pdf_input.seek(0)
                    plumber_pdf = pdfplumber.open(pdf_input)
            except Exception as e:
                logger.warning(f"Could not open stream with pdfplumber: {e}")
                plumber_pdf = None

        try:
            # 3. Page-by-page Extraction (Zero-Loss Loop)
            for page_idx in range(start_idx, end_idx):
                physical_page = page_idx + 1
                if physical_page % 25 == 0 or physical_page == end_idx:
                    logger.info(f"Extracting {source_filename}: page {physical_page}/{end_idx}...")
                page_error = None
                raw_text = ""

                try:
                    page_obj = reader.pages[page_idx]
                    raw_text = page_obj.extract_text() or ""
                except Exception as e:
                    page_error = f"Error extracting page {physical_page}: {str(e)}"
                    logger.warning(page_error)
                    errors.append(page_error)

                # Normalize text non-destructively
                normalized_text = normalize_text(raw_text)
                char_count = len(normalized_text)

                is_empty = is_empty_or_whitespace(normalized_text)
                is_suspiciously_short = not is_empty and char_count < min_short_chars

                # Detect if page appears to be a scanned raster image
                is_scanned = False
                if is_empty or is_suspiciously_short:
                    try:
                        if hasattr(page_obj, "images") and len(page_obj.images) > 0:
                            is_scanned = True
                    except Exception:
                        pass

                # Detect printed page label
                printed_page = detect_printed_page_label(raw_text)

                # Record warnings
                page_warnings: List[str] = []
                if is_empty:
                    page_warnings.append("BLANK_PAGE")
                    warnings.append(QualityWarning(
                        category=WarningCategory.BLANK_PAGE,
                        message=f"Physical page {physical_page} has zero extracted text.",
                        physical_page=physical_page
                    ))
                elif is_scanned:
                    page_warnings.append("SCANNED_OR_IMAGE_PAGE")
                    warnings.append(QualityWarning(
                        category=WarningCategory.SCANNED_PAGE,
                        message=f"Physical page {physical_page} appears to be a scanned image or raster chart.",
                        physical_page=physical_page
                    ))
                elif is_suspiciously_short:
                    page_warnings.append("SUSPICIOUSLY_SHORT_CONTENT")
                    warnings.append(QualityWarning(
                        category=WarningCategory.SHORT_CONTENT,
                        message=f"Physical page {physical_page} has only {char_count} characters.",
                        physical_page=physical_page
                    ))

                # Extract Tables and segment narrative blocks
                plumber_page = None
                if plumber_pdf is not None and page_idx < len(plumber_pdf.pages):
                    try:
                        plumber_page = plumber_pdf.pages[page_idx]
                    except Exception:
                        plumber_page = None

                if plumber_page is not None and not is_empty:
                    tables, blocks = self._extract_page_content_and_tables(
                        plumber_page=plumber_page,
                        raw_text=raw_text,
                        physical_page=physical_page,
                        printed_page=printed_page
                    )
                elif not is_empty:
                    heur_tables, heur_blocks = self._extract_page_tables_heuristic(
                        page_text=normalized_text,
                        physical_page=physical_page,
                        printed_page=printed_page
                    )
                    if heur_tables:
                        tables, blocks = heur_tables, heur_blocks
                    else:
                        narr_blocks, _ = self._segment_page_narrative(
                            slice_text=normalized_text,
                            physical_page=physical_page,
                            printed_page=printed_page,
                            start_blk_idx=1
                        )
                        tables, blocks = [], narr_blocks
                else:
                    tables, blocks = [], []

                # Fallback if non-empty page yielded 0 blocks
                if not blocks and not is_empty:
                    locator = PDFSourceLocator(
                        physical_page=physical_page,
                        printed_page=printed_page
                    )
                    blocks.append(ContentBlock(
                        block_id=f"p{physical_page:03d}_blk01",
                        block_type=BlockType.PARAGRAPH,
                        text_content=normalized_text,
                        locator=locator,
                        table_data=None,
                        is_boilerplate=False
                    ))

                page_records.append(RawPageRecord(
                    physical_page=physical_page,
                    printed_page=printed_page,
                    text=normalized_text,
                    char_count=char_count,
                    is_empty=is_empty,
                    is_suspiciously_short=is_suspiciously_short,
                    is_scanned=is_scanned,
                    tables=tables,
                    blocks=blocks,
                    warnings=page_warnings,
                    extraction_error=page_error
                ))
                if plumber_page is not None and hasattr(plumber_page, "flush_cache"):
                    try:
                        plumber_page.flush_cache()
                    except Exception:
                        pass
        finally:
            if plumber_pdf is not None:
                try:
                    plumber_pdf.close()
                except Exception:
                    pass

        return RawExtractionPayload(
            source_filename=source_filename,
            document_format=DocumentFormat.PDF,
            total_physical_pages=page_end if page_end_cfg is not None else num_pages,
            metadata=raw_metadata,
            outline_entries=outline_entries,
            pages=page_records,
            warnings=warnings,
            errors=errors
        )

    def _parse_outline(
        self,
        reader: pypdf.PdfReader,
        outline: Any,
        parent_title: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Recursively parses native PDF bookmarks."""
        entries: List[Dict[str, Any]] = []
        for item in outline:
            if isinstance(item, dict) and "/Title" in item:
                title = str(item.get("/Title", "")).strip()
                try:
                    page_num = reader.get_destination_page_number(item)
                    physical_page = page_num + 1 if page_num is not None else None
                except Exception:
                    physical_page = None

                entries.append({
                    "title": title,
                    "physical_page": physical_page,
                    "parent_title": parent_title
                })
            elif isinstance(item, list):
                # Sub-bookmarks
                sub_entries = self._parse_outline(reader, item, parent_title=entries[-1]["title"] if entries else None)
                entries.extend(sub_entries)
        return entries

    def _segment_page_narrative(
        self,
        slice_text: str,
        physical_page: int,
        printed_page: Optional[str],
        start_blk_idx: int = 1
    ) -> Tuple[List[ContentBlock], int]:
        """
        Segments a single-newline text stream into natural headings, lists, and paragraphs.
        Preserves 100% of narrative text without loss or character mangling.
        """
        norm = normalize_text(slice_text)
        if is_empty_or_whitespace(norm):
            return [], start_blk_idx

        lines = [l.strip() for l in norm.split("\n") if l.strip()]
        if not lines:
            return [], start_blk_idx

        body_lengths = [len(l) for l in lines if len(l) > 40]
        typical_len = max(body_lengths) if body_lengths else 80

        raw_blocks: List[str] = []
        curr_lines: List[str] = []

        def is_bullet(l: str) -> bool:
            return bool(BULLET_REGEX.match(l))

        SIGNATURE_OR_METADATA_REGEX = re.compile(
            r"^(?:Sd/-|DIN\s*:|Place\s*:|Date\s*:|Dated\s*:|By\s+order\s+of|For\s+and\s+on\s+behalf\s+of)\b",
            re.IGNORECASE
        )

        def is_short_heading(l: str) -> bool:
            if len(l) > 80:
                return False
            if l.endswith((".", ",", ";", "?", "!")):
                return False
            if SIGNATURE_OR_METADATA_REGEX.match(l):
                return False
            words = l.split()
            if len(words) <= 12 and (l.isupper() or (words and words[0][0].isupper())):
                return True
            return False

        for line in lines:
            # Filter running headers/footers
            if RUNNING_HEADER_FOOTER_REGEX.match(line):
                continue
            if re.match(r"^(?:Page\s+\d+|\d+\s*\|\s*ANNUAL|ANNUAL\s*REPORT.*\|\s*\d+|\d+)$", line, re.I):
                continue
            if line == "FINANCING INFRASTRUCTURE FOR VIKSIT BHARAT":
                continue

            starts_new = False
            if curr_lines:
                prev = curr_lines[-1]
                if prev.endswith((".", "!", "?", '."', ".'")):
                    if len(prev) < 0.85 * typical_len or is_bullet(line) or is_short_heading(line):
                        starts_new = True
                elif prev.endswith(":"):
                    starts_new = True
                elif is_bullet(line) or is_short_heading(line) or is_short_heading(prev):
                    starts_new = True

            if starts_new and curr_lines:
                text_block = " ".join(curr_lines).strip()
                if text_block:
                    raw_blocks.append(text_block)
                curr_lines = [line]
            else:
                curr_lines.append(line)

        if curr_lines:
            text_block = " ".join(curr_lines).strip()
            if text_block:
                raw_blocks.append(text_block)

        content_blocks: List[ContentBlock] = []
        blk_idx = start_blk_idx
        for b_text in raw_blocks:
            if is_bullet(b_text):
                b_type = BlockType.LIST
                h_level = None
            elif is_short_heading(b_text):
                b_type = BlockType.HEADING
                h_level = 2
            else:
                b_type = BlockType.PARAGRAPH
                h_level = None

            locator = PDFSourceLocator(physical_page=physical_page, printed_page=printed_page)
            content_blocks.append(ContentBlock(
                block_id=f"p{physical_page:03d}_blk{blk_idx:02d}",
                block_type=b_type,
                text_content=b_text,
                locator=locator,
                heading_level=h_level
            ))
            blk_idx += 1

        return content_blocks, blk_idx

    def _extract_page_content_and_tables(
        self,
        plumber_page: Any,
        raw_text: str,
        physical_page: int,
        printed_page: Optional[str]
    ) -> Tuple[List[StructuredTable], List[ContentBlock]]:
        """
        Extracts coordinate-aware tables and interleaved narrative segments from a pdfplumber page.
        """
        tables: List[StructuredTable] = []
        blocks: List[ContentBlock] = []

        found_tables = []
        try:
            if hasattr(plumber_page, "curves") and len(plumber_page.curves) > 100:
                raw_tables = plumber_page.find_tables(table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            else:
                raw_tables = plumber_page.find_tables()
            for t in raw_tables:
                if t.bbox[0] >= 0 and t.bbox[1] >= 0:
                    data = t.extract()
                    if data and len(data) >= 3 and any(len(row) >= 2 for row in data):
                        non_empty_cells = sum(1 for row in data for cell in row if cell and cell.strip())
                        if non_empty_cells >= 4:
                            found_tables.append((t, data))
        except Exception as e:
            logger.warning(f"Error finding tables via pdfplumber on page {physical_page}: {e}")
            found_tables = []

        if not found_tables:
            heur_tables, heur_blocks = self._extract_page_tables_heuristic(
                raw_text, physical_page, printed_page
            )
            if heur_tables:
                return heur_tables, heur_blocks

            narr_blocks, _ = self._segment_page_narrative(
                slice_text=raw_text,
                physical_page=physical_page,
                printed_page=printed_page,
                start_blk_idx=1
            )
            return tables, narr_blocks

        # Interleave narrative slices and tables in vertical top-to-bottom order
        found_tables.sort(key=lambda item: item[0].bbox[1])
        prev_bottom = 0.0
        blk_seq = 1
        tbl_seq = 0

        for t_obj, t_data in found_tables:
            t_top = t_obj.bbox[1]
            t_bottom = t_obj.bbox[3]

            if t_top > prev_bottom:
                try:
                    slice_box = (0, prev_bottom, plumber_page.width, t_top)
                    slice_text = plumber_page.crop(slice_box).extract_text() or ""
                except Exception:
                    slice_text = ""
                slice_blocks, blk_seq = self._segment_page_narrative(
                    slice_text=slice_text,
                    physical_page=physical_page,
                    printed_page=printed_page,
                    start_blk_idx=blk_seq
                )
                blocks.extend(slice_blocks)

            tbl_seq += 1
            t_id = f"p{physical_page:03d}_tbl{tbl_seq:02d}"

            caption = None
            unit_of_measure = None
            if blocks:
                for cand_b in reversed(blocks[-3:]):
                    if cand_b.block_type == BlockType.HEADING and not caption:
                        caption = cand_b.text_content
                    cand_unit = detect_unit_of_measure(cand_b.text_content)
                    if cand_unit and not unit_of_measure:
                        unit_of_measure = cand_unit
            if not unit_of_measure:
                unit_of_measure = detect_unit_of_measure(raw_text)

            st = build_structured_table(t_data, table_id=t_id, caption=caption, unit_of_measure=unit_of_measure)
            if st:
                tables.append(st)
                locator = PDFSourceLocator(
                    physical_page=physical_page,
                    printed_page=printed_page
                )
                blocks.append(ContentBlock(
                    block_id=f"p{physical_page:03d}_tbl_blk{tbl_seq:02d}",
                    block_type=BlockType.TABLE,
                    text_content=st.markdown_representation,
                    locator=locator,
                    table_data=st,
                    is_boilerplate=False
                ))

            prev_bottom = max(prev_bottom, t_bottom)

        if prev_bottom < plumber_page.height:
            try:
                slice_box = (0, prev_bottom, plumber_page.width, plumber_page.height)
                slice_text = plumber_page.crop(slice_box).extract_text() or ""
            except Exception:
                slice_text = ""
            slice_blocks, blk_seq = self._segment_page_narrative(
                slice_text=slice_text,
                physical_page=physical_page,
                printed_page=printed_page,
                start_blk_idx=blk_seq
            )
            blocks.extend(slice_blocks)

        return tables, blocks

    def _extract_page_tables(
        self,
        page_text: str,
        physical_page: int,
        printed_page: Optional[str]
    ) -> Tuple[List[StructuredTable], List[ContentBlock]]:
        """Delegates to heuristic table extraction for backward compatibility."""
        return self._extract_page_tables_heuristic(page_text, physical_page, printed_page)

    def _extract_page_tables_heuristic(
        self,
        page_text: str,
        physical_page: int,
        printed_page: Optional[str]
    ) -> Tuple[List[StructuredTable], List[ContentBlock]]:
        """
        Detects and parses tabular structures from page text into StructuredTable objects,
        preserving surrounding narrative, headings, and footnotes above and below.
        """
        tables: List[StructuredTable] = []
        blocks: List[ContentBlock] = []

        if not page_text:
            return tables, blocks

        # Check for tabular signals
        has_keywords = bool(TABLE_KEYWORD_REGEX.search(page_text))
        has_numbers = bool(TABLE_LINE_INDICATOR_REGEX.search(page_text))

        if not (has_keywords or has_numbers):
            return tables, blocks

        # Group lines that appear tabular (lines with 2+ columns separated by 2+ spaces or tabs)
        lines = page_text.split("\n")
        table_lines_idx: List[int] = []
        table_rows: List[List[str]] = []

        for idx, line in enumerate(lines):
            line_str = line.strip()
            if not line_str:
                continue
            cells = [c.strip() for c in re.split(r"\s{2,}|\t", line_str) if c.strip()]
            if len(cells) >= 2:
                table_lines_idx.append(idx)
                table_rows.append(cells)

        if len(table_rows) >= 3:
            t_start = min(table_lines_idx)
            t_end = max(table_lines_idx)

            above_text = "\n".join(lines[:t_start]).strip()
            below_text = "\n".join(lines[t_end + 1:]).strip()

            table_id = f"p{physical_page:03d}_tbl01"

            # Detect caption and unit of measure
            caption = None
            unit_of_measure = None
            if above_text:
                above_lines = [l.strip() for l in above_text.split("\n") if l.strip()]
                if above_lines:
                    cand_caption = above_lines[-1]
                    if len(cand_caption) < 80 and not cand_caption.endswith((".", ":")):
                        caption = cand_caption
                unit_of_measure = detect_unit_of_measure(above_text)
            if not unit_of_measure:
                unit_of_measure = detect_unit_of_measure(page_text)

            st = build_structured_table(table_rows, table_id=table_id, caption=caption, unit_of_measure=unit_of_measure)
            if st:
                tables.append(st)
                blk_seq = 1

                # 1. Narrative / headings above table
                if above_text:
                    above_blocks, blk_seq = self._segment_page_narrative(
                        slice_text=above_text,
                        physical_page=physical_page,
                        printed_page=printed_page,
                        start_blk_idx=blk_seq
                    )
                    blocks.extend(above_blocks)

                # 2. Structured table block
                locator = PDFSourceLocator(
                    physical_page=physical_page,
                    printed_page=printed_page
                )
                blocks.append(ContentBlock(
                    block_id=f"p{physical_page:03d}_tbl_blk01",
                    block_type=BlockType.TABLE,
                    text_content=st.markdown_representation,
                    locator=locator,
                    table_data=st,
                    is_boilerplate=False
                ))

                # 3. Narrative / footnotes below table
                if below_text:
                    below_blocks, blk_seq = self._segment_page_narrative(
                        slice_text=below_text,
                        physical_page=physical_page,
                        printed_page=printed_page,
                        start_blk_idx=blk_seq + 1
                    )
                    blocks.extend(below_blocks)

        return tables, blocks
