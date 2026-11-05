"""
Format-Agnostic Structural Analysis Engine.
File: pipeline/core/structural_analyzer.py

Analyzes extracted document payloads (PDF, HTML, etc.) and infers logical section hierarchies
using a strict evidence hierarchy:
1. Native PDF outlines / bookmarks (high confidence)
2. HTML heading tree (high confidence)
3. Document Table of Contents matching against verified printed page labels (medium confidence)
4. Page-top heading signals (medium confidence)
5. Conservative heuristic fallback (low confidence)

Preserves 100% of substantive content blocks with explicit block-accounting verification.
Maintains parent/child heading paths, maps physical and printed pages separately,
records explicit confidence ratings, and never uses fixed page offsets or hardcoded section lists.
"""

from __future__ import annotations

import re
import hashlib
import logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple, Set

from pipeline.core.contracts import (
    DocumentFormat,
    BlockType,
    WarningCategory,
    QualityWarning,
    ContentBlock,
    CanonicalSection,
    DocumentMetadata,
    CanonicalDocument,
    ProcessingStatus,
    PDFSourceLocator,
    HTMLSourceLocator,
)

if TYPE_CHECKING:
    from pipeline.adapters.base import RawExtractionPayload, RawPageRecord

logger = logging.getLogger("StructuralAnalyzer")

# Heuristic pattern to identify Table of Contents headings (handles repeating/glued text like CONTENTSCONTENTS)
TOC_TITLE_REGEX = re.compile(
    r"(?:^\s*(?:table\s+of\s+contents|contents(?:\s*contents)?|index|table\s+des\s+matières)\s*$|CONTENTSCONTENTS)",
    re.IGNORECASE | re.MULTILINE
)

# Pattern to match a TOC entry line: "Title text .......... 52", "Title text | 52", or "Title text 52"
# Groups: (1) Title, (2) Page Number (Arabic or Roman)
TOC_LINE_REGEX = re.compile(
    r"^[ \t]*([A-Za-z][A-Za-z0-9 \t,&’\'\(\)\/\-]{2,})[ \t]*(?:\.{2,}|[-—–]{2,}|\t|\||[ \t]+)[ \t]*([0-9]{1,4}|[ivxlcdm]{1,8})[ \t]*$",
    re.MULTILINE
)

# Negative exclusion for non-TOC lines (dates, currency, running headers, meeting schedules)
TOC_NEGATIVE_REGEX = re.compile(
    r"(?:Date\s*:|Time\s*:|Schedule|CUT-OFF|START\s+DATE|END\s+DATE|`\s*in\s*Crore|\b(?:Rs\.?|INR|USD)\b|\$|€|¥|Tel\s*:|Fax\s*:|Email\s*:|Website\s*:|\b(?:am|pm|ist)\b|\bANNUAL\s+REPORT\b)",
    re.IGNORECASE
)


class StructuralAnalyzer:
    """
    Format-agnostic structural analysis engine.
    Transforms a RawExtractionPayload into a validated CanonicalDocument with section hierarchies.
    """

    def __init__(self):
        pass

    def analyze(
        self,
        payload: RawExtractionPayload,
        metadata: Optional[DocumentMetadata] = None,
        document_id: Optional[str] = None
    ) -> CanonicalDocument:
        """
        Derives section hierarchy from evidence hierarchy and constructs a CanonicalDocument.
        Enforces strict block accounting to guarantee zero missing or duplicated blocks.
        """
        if metadata is None:
            metadata = self._build_default_metadata(payload, document_id)

        warnings: List[QualityWarning] = list(payload.warnings)
        sections: List[CanonicalSection] = []

        # 1. Evidence Hierarchy Execution (Waterfall Architecture)
        # Priority 1: Native PDF outlines (if valid, non-degenerate, and informative)
        if payload.document_format == DocumentFormat.PDF and payload.outline_entries:
            sections, sec_warnings = self._build_from_pdf_outlines(payload)
            warnings.extend(sec_warnings)

        # Priority 2: HTML heading tree
        if not sections and payload.document_format == DocumentFormat.HTML:
            sections, sec_warnings = self._build_from_html_headings(payload)
            warnings.extend(sec_warnings)

        # Priority 3: Table of Contents discovery
        if not sections:
            toc_sections, toc_warnings = self._try_toc_discovery(payload)
            warnings.extend(toc_warnings)
            if toc_sections:
                sections = toc_sections

        # Priority 4: Heading signals / Heading tree fallback
        if not sections:
            if self._has_html_headings(payload):
                heading_sections, heading_warnings = self._build_from_html_headings(payload)
                if heading_sections:
                    sections = heading_sections
                    warnings.extend(heading_warnings)

            if not sections:
                heading_sections, heading_warnings = self._try_page_heading_signals(payload)
                warnings.extend(heading_warnings)
                if heading_sections:
                    sections = heading_sections

        # Priority 5: Conservative Fallback
        if not sections:
            sections, fallback_warnings = self._build_conservative_fallback(payload, metadata)
            warnings.extend(fallback_warnings)

        # 2. Safety Fallback: Ensure at least one section exists
        if not sections:
            sections, fb_warns = self._build_conservative_fallback(payload, metadata)
            warnings.extend(fb_warns)

        # 3. Explicit Source Block Accounting Check
        all_source_blocks: List[ContentBlock] = [b for p in payload.pages for b in p.blocks]
        total_source_blocks = len(all_source_blocks)

        source_id_counts: Dict[str, int] = {}
        for b in all_source_blocks:
            source_id_counts[b.block_id] = source_id_counts.get(b.block_id, 0) + 1

        payload_duplicate_ids = [bid for bid, count in source_id_counts.items() if count > 1]
        has_accounting_anomaly = False

        if payload_duplicate_ids:
            has_accounting_anomaly = True
            dup_instances = sum(count - 1 for count in source_id_counts.values() if count > 1)
            msg = (
                f"Block accounting: Source payload contains {dup_instances} duplicate block ID instance(s) "
                f"across {len(payload_duplicate_ids)} distinct ID(s) (first duplicate: '{payload_duplicate_ids[0]}'). "
                f"Source invariant violated; exactly-once accounting cannot be guaranteed for ambiguous block IDs."
            )
            logger.warning(msg)
            warnings.append(QualityWarning(
                category=WarningCategory.CONTENT_ANOMALY,
                message=msg
            ))

        # Check section assignments
        sec_blocks: List[ContentBlock] = [b for s in sections for b in s.blocks]
        sec_id_counts: Dict[str, int] = {}
        for b in sec_blocks:
            sec_id_counts[b.block_id] = sec_id_counts.get(b.block_id, 0) + 1

        multiply_assigned_ids = [bid for bid, count in sec_id_counts.items() if count > 1]
        if multiply_assigned_ids:
            has_accounting_anomaly = True
            msg = (
                f"Block accounting: {len(multiply_assigned_ids)} block IDs were multiply assigned across sections "
                f"(first duplicate: '{multiply_assigned_ids[0]}')."
            )
            logger.warning(msg)
            warnings.append(QualityWarning(
                category=WarningCategory.CONTENT_ANOMALY,
                message=msg
            ))

        # Check for unassigned/missing blocks by ID
        missing_ids = set(source_id_counts.keys()) - set(sec_id_counts.keys())
        if missing_ids:
            has_accounting_anomaly = True
            missing_blocks = [b for b in all_source_blocks if b.block_id in missing_ids]
            recovery_sec_id = f"sec_{len(sections) + 1:02d}"
            
            missing_pages = [
                getattr(b.locator, "physical_page", 1) for b in missing_blocks
                if b.locator and getattr(b.locator, "physical_page", None) is not None
            ]
            p_start = min(missing_pages) if missing_pages else 1
            p_end = max(missing_pages) if missing_pages else max(1, payload.total_physical_pages or 1)

            recovery_section = CanonicalSection(
                section_id=recovery_sec_id,
                title="Unassigned Content Recovery",
                level=1,
                physical_page_start=p_start,
                physical_page_end=p_end,
                segmentation_method="accounting_recovery",
                confidence="low",
                parent_section_id=None,
                heading_path=["Unassigned Content Recovery"],
                blocks=missing_blocks
            )
            sections.append(recovery_section)

            msg = (
                f"Block accounting: {len(missing_ids)} unassigned source blocks isolated into "
                f"traceable recovery section '{recovery_sec_id}'."
            )
            logger.warning(msg)
            warnings.append(QualityWarning(
                category=WarningCategory.CONTENT_ANOMALY,
                message=msg
            ))

        # Count accounting check: compare total raw source blocks to total assigned blocks
        total_assigned_blocks = sum(len(s.blocks) for s in sections)
        if total_assigned_blocks != total_source_blocks:
            has_accounting_anomaly = True
            msg = (
                f"Block accounting: Exactly-once invariant not satisfied. Payload contains {total_source_blocks} "
                f"source blocks, but sections contain {total_assigned_blocks} assigned blocks "
                f"(discrepancy: {abs(total_source_blocks - total_assigned_blocks)} blocks)."
            )
            logger.warning(msg)
            warnings.append(QualityWarning(
                category=WarningCategory.CONTENT_ANOMALY,
                message=msg
            ))

        # Check for physical page sequence gaps in payload
        has_page_gaps = False
        if payload.pages:
            p_nums = sorted(p.physical_page for p in payload.pages)
            gaps = [
                (p_nums[i], p_nums[i + 1])
                for i in range(len(p_nums) - 1)
                if p_nums[i + 1] > p_nums[i] + 1
            ]
            if gaps:
                has_page_gaps = True
                msg = f"Missing physical page gap detected: extraction stream omitted pages between {gaps}."
                logger.warning(msg)
                warnings.append(QualityWarning(
                    category=WarningCategory.CONTENT_ANOMALY,
                    message=msg
                ))

        # Determine overall processing status per ADR-08
        has_low_confidence = any(s.confidence == "low" for s in sections)
        has_severe_warning = any(
            w.category in {
                WarningCategory.CONTENT_ANOMALY,
                WarningCategory.TABLE_EXTRACTION_FAILED,
            }
            for w in warnings
        )

        if not sections or total_source_blocks == 0:
            final_status = ProcessingStatus.FAILED
        elif has_accounting_anomaly or has_page_gaps or has_low_confidence or has_severe_warning:
            final_status = ProcessingStatus.PARTIAL_SUCCESS
        elif len(warnings) > 0 or not payload.is_clean_success:
            final_status = ProcessingStatus.SUCCESS_WITH_WARNINGS
        else:
            final_status = ProcessingStatus.SUCCESS

        # 4. Construct validated CanonicalDocument
        return CanonicalDocument(
            metadata=metadata,
            sections=sections,
            warnings=warnings,
            processing_status=final_status
        )

    # =========================================================================
    # Priority 1: Native PDF Outlines
    # =========================================================================

    GENERIC_EXPORT_PATTERN = re.compile(
        r"^(?:final_?final.*|untitled.*|export.*|document\s*\d*|new\s+document.*|cover\s*\d*|page\s*\d+)$|"
        r".*\.(?:pdf|indd|ai|qxp)$",
        re.IGNORECASE
    )

    def _validate_pdf_outlines(
        self,
        entries: List[Dict[str, Any]],
        total_pages: int
    ) -> Tuple[bool, List[str]]:
        """
        Conservative semantic validation of PDF native bookmarks.
        Evaluates title quality, generic/numeric export labels, page references, and ordering.
        Returns (is_valid, reasons_for_rejection).
        """
        reasons: List[str] = []
        if not entries or len(entries) < 1:
            return False, ["Outline contains no entries."]

        # 1. Page references validation
        valid_page_entries = 0
        pages: List[int] = []
        for e in entries:
            p = e.get("physical_page")
            if isinstance(p, int) and 1 <= p <= total_pages:
                valid_page_entries += 1
                pages.append(p)

        if valid_page_entries < len(entries) * 0.5:
            reasons.append(
                f"Majority of outline entries ({len(entries) - valid_page_entries}/{len(entries)}) "
                f"have invalid physical page numbers."
            )
            return False, reasons

        # 2. Check for severe non-monotonicity
        inversions = 0
        for i in range(len(pages) - 1):
            if pages[i] > pages[i + 1]:
                inversions += 1
        if inversions > 0 and (inversions / max(1, len(pages) - 1) >= 0.25 or inversions >= 2):
            reasons.append(
                f"Outline entries exhibit non-monotonic page order ({inversions} inversions across {len(pages)} entries)."
            )
            return False, reasons

        # 3. Check for generic / non-semantic / pure-digit export titles
        uninformative_count = 0
        sample_uninformative = []
        for e in entries:
            title = str(e.get("title", "")).strip()
            is_pure_digits = bool(re.fullmatch(r"\d+", title))
            is_generic_export = bool(self.GENERIC_EXPORT_PATTERN.match(title))
            is_too_short = len(title) <= 2 and not any(c.isalpha() for c in title)

            if is_pure_digits or is_generic_export or is_too_short:
                uninformative_count += 1
                if len(sample_uninformative) < 3:
                    sample_uninformative.append(title)

        uninformative_ratio = uninformative_count / len(entries)
        if uninformative_ratio >= 0.40:
            reasons.append(
                f"{uninformative_ratio:.1%} of outline entries ({uninformative_count}/{len(entries)}) "
                f"are generic export artifacts or pure numeric digits (e.g. {sample_uninformative})."
            )
            return False, reasons

        # 4. Check for duplicate collapse
        unique_signatures = {(str(e.get("title", "")).strip().lower(), e.get("physical_page")) for e in entries}
        if len(entries) > 1 and len(unique_signatures) < 2:
            reasons.append("Outline entries collapse to a single distinct title/page destination.")
            return False, reasons

        return True, []

    def _build_from_pdf_outlines(
        self,
        payload: RawExtractionPayload
    ) -> Tuple[List[CanonicalSection], List[QualityWarning]]:
        """Constructs canonical sections from PDF outline bookmarks with hierarchical nesting."""
        warnings: List[QualityWarning] = []
        sections: List[CanonicalSection] = []
        entries = payload.outline_entries
        total_pages = payload.total_physical_pages or len(payload.pages) or 1

        # Perform semantic validation on outline entries
        is_valid, rejection_reasons = self._validate_pdf_outlines(entries, total_pages)
        if not is_valid:
            reason_str = "; ".join(rejection_reasons)
            msg = f"PDF native outline rejected: {reason_str} Falling back to secondary structural evidence."
            logger.warning(msg)
            warnings.append(QualityWarning(
                category=WarningCategory.STRUCTURE_CONFIDENCE,
                message=msg
            ))
            return [], warnings

        # Filter out invalid page references
        valid_entries: List[Dict[str, Any]] = []
        for e in entries:
            p_num = e.get("physical_page")
            if isinstance(p_num, int) and 1 <= p_num <= total_pages:
                valid_entries.append(e)
            else:
                warnings.append(QualityWarning(
                    category=WarningCategory.STRUCTURE_CONFIDENCE,
                    message=f"Outline entry '{e.get('title')}' has invalid physical_page {p_num}; discarded."
                ))

        if not valid_entries:
            return [], [QualityWarning(
                category=WarningCategory.STRUCTURE_CONFIDENCE,
                message="PDF outline entries contained no valid physical page references."
            )]

        # Map pages by physical page number
        page_map: Dict[int, RawPageRecord] = {p.physical_page: p for p in payload.pages}
        assigned_block_ids: Set[str] = set()

        # Check for unclassified front matter before the first outline item
        first_page = min(e["physical_page"] for e in valid_entries)
        if first_page > 1:
            preamble_blocks: List[ContentBlock] = []
            for p_num in range(1, first_page):
                if p_num in page_map:
                    for b in page_map[p_num].blocks:
                        if b.block_id not in assigned_block_ids:
                            preamble_blocks.append(b)
                            assigned_block_ids.add(b.block_id)

            p_first_rec = page_map.get(1)
            p_last_rec = page_map.get(first_page - 1)
            printed_p1 = p_first_rec.printed_page if p_first_rec else None
            printed_pend = p_last_rec.printed_page if p_last_rec else None
            if preamble_blocks:
                sections.append(CanonicalSection(
                    section_id="sec_00",
                    title="Document Front Matter",
                    level=1,
                    physical_page_start=1,
                    physical_page_end=first_page - 1,
                    printed_page_start=printed_p1,
                    printed_page_end=printed_pend,
                    segmentation_method="preamble_unclassified",
                    confidence="medium",
                    parent_section_id=None,
                    heading_path=["Document Front Matter"],
                    blocks=preamble_blocks
                ))

        # Hierarchical outline traversal using parent stack: [(level, section_id, title)]
        active_parents: List[Tuple[int, str, str]] = []
        genuine_sec_idx = 0

        for i, entry in enumerate(valid_entries):
            genuine_sec_idx += 1
            sec_id = f"sec_{genuine_sec_idx:02d}"
            title = entry.get("title", f"Section {genuine_sec_idx}").strip()
            level = min(3, max(1, entry.get("level", 1)))
            start_page = entry["physical_page"]

            # Compute end_page safely without exceeding bounds
            if i + 1 < len(valid_entries):
                next_start = valid_entries[i + 1]["physical_page"]
                end_page = max(start_page, next_start - 1) if next_start > start_page else start_page
            else:
                end_page = max(start_page, total_pages)

            # Resolve parent_section_id and heading_path from active_parents
            while active_parents and active_parents[-1][0] >= level:
                active_parents.pop()

            if active_parents:
                parent_sec_id = active_parents[-1][1]
                heading_path = [p[2] for p in active_parents] + [title]
            else:
                parent_sec_id = None
                heading_path = [title]

            active_parents.append((level, sec_id, title))

            # Collect unassigned blocks in this page range (prevents duplicate blocks on same-page entries)
            sec_blocks: List[ContentBlock] = []
            for p_num in range(start_page, end_page + 1):
                if p_num in page_map:
                    for b in page_map[p_num].blocks:
                        if b.block_id not in assigned_block_ids:
                            sec_blocks.append(b)
                            assigned_block_ids.add(b.block_id)

            confidence = "high"
            if not sec_blocks and start_page in page_map and page_map[start_page].blocks:
                confidence = "low"
                warnings.append(QualityWarning(
                    category=WarningCategory.STRUCTURE_CONFIDENCE,
                    message=(
                        f"Outline entry '{title}' (p.{start_page}) received 0 blocks; "
                        f"page content was already assigned to a preceding bookmark on the same page."
                    ),
                    physical_page=start_page,
                    section_id=sec_id
                ))

            p_start_rec = page_map.get(start_page)
            p_end_rec = page_map.get(end_page)
            printed_start = p_start_rec.printed_page if p_start_rec else None
            printed_end = p_end_rec.printed_page if p_end_rec else None

            sections.append(CanonicalSection(
                section_id=sec_id,
                title=title,
                level=level,
                physical_page_start=start_page,
                physical_page_end=end_page,
                printed_page_start=printed_start,
                printed_page_end=printed_end,
                segmentation_method="native_outline",
                confidence=confidence,
                parent_section_id=parent_sec_id,
                heading_path=heading_path,
                blocks=sec_blocks
            ))

        return sections, warnings

    # =========================================================================
    # Priority 2: HTML Heading Tree
    # =========================================================================

    def _has_html_headings(self, payload: RawExtractionPayload) -> bool:
        """Checks if payload contains any explicit heading blocks."""
        for p in payload.pages:
            for b in p.blocks:
                if b.block_type == BlockType.HEADING:
                    return True
        return False

    def _build_from_html_headings(
        self,
        payload: RawExtractionPayload
    ) -> Tuple[List[CanonicalSection], List[QualityWarning]]:
        """
        Constructs canonical sections using explicit HTML heading hierarchy (h1-h6).
        Preserves content before first heading in sec_00, handles skipped levels,
        retains heading blocks exactly once, and maintains ancestral breadcrumbs.

        Provenance Note:
        ----------------
        HTML documents are continuous DOM structures without physical paper pages.
        physical_page_start and physical_page_end represent document partition indices
        (defaulting to 1 for standard single-page HTML documents), mapped from
        RawPageRecord.physical_page. Provenance for HTML blocks is maintained via
        HTMLSourceLocator (source_url, css_selector, heading_hierarchy).
        """
        warnings: List[QualityWarning] = []
        sections: List[CanonicalSection] = []

        all_blocks: List[ContentBlock] = [b for p in payload.pages for b in p.blocks]
        if not all_blocks:
            return [], [QualityWarning(
                category=WarningCategory.STRUCTURE_CONFIDENCE,
                message="HTML payload contains zero content blocks."
            )]

        # Map block IDs to their containing RawPageRecord partition index
        block_to_partition: Dict[str, int] = {
            b.block_id: p.physical_page for p in payload.pages for b in p.blocks
        }

        # Find first heading index
        first_heading_idx = -1
        for idx, b in enumerate(all_blocks):
            if b.block_type == BlockType.HEADING:
                first_heading_idx = idx
                break

        assigned_block_ids: Set[str] = set()

        # Handle content before the first heading
        if first_heading_idx > 0:
            preamble = all_blocks[:first_heading_idx]
            for b in preamble:
                assigned_block_ids.add(b.block_id)

            p_parts = [block_to_partition.get(b.block_id, 1) for b in preamble]
            p_start = min(p_parts) if p_parts else 1
            p_end = max(p_parts) if p_parts else p_start

            sections.append(CanonicalSection(
                section_id="sec_00",
                title="Document Overview",
                level=1,
                physical_page_start=p_start,
                physical_page_end=p_end,
                segmentation_method="preamble_unclassified",
                confidence="medium",
                parent_section_id=None,
                heading_path=["Document Overview"],
                blocks=preamble
            ))
            remaining_blocks = all_blocks[first_heading_idx:]
        elif first_heading_idx == 0:
            remaining_blocks = all_blocks
        else:
            # No headings found at all
            return self._build_conservative_fallback(payload, self._build_default_metadata(payload))

        # Hierarchical grouping by headings: [(level, section_id, title)]
        active_parents: List[Tuple[int, str, str]] = []
        genuine_sec_idx = 0

        current_heading_block: Optional[ContentBlock] = None
        current_blocks: List[ContentBlock] = []

        def _flush_html_section():
            nonlocal current_heading_block, current_blocks, active_parents, sections, genuine_sec_idx
            if not current_heading_block and not current_blocks:
                return

            genuine_sec_idx += 1
            sec_id = f"sec_{genuine_sec_idx:02d}"
            title = current_heading_block.text_content.strip() if current_heading_block else f"Section {genuine_sec_idx}"
            level = min(3, max(1, current_heading_block.heading_level or 1)) if current_heading_block else 1

            # Resolve parent_section_id and heading_path
            while active_parents and active_parents[-1][0] >= level:
                active_parents.pop()

            if active_parents:
                parent_sec_id = active_parents[-1][1]
                heading_path = [p[2] for p in active_parents] + [title]
            else:
                parent_sec_id = None
                heading_path = [title]

            active_parents.append((level, sec_id, title))

            # Assemble blocks for this section
            sec_blocks = []
            if current_heading_block and current_heading_block.block_id not in assigned_block_ids:
                sec_blocks.append(current_heading_block)
                assigned_block_ids.add(current_heading_block.block_id)

            for b in current_blocks:
                if b.block_id not in assigned_block_ids:
                    sec_blocks.append(b)
                    assigned_block_ids.add(b.block_id)

            sec_parts = [block_to_partition.get(b.block_id, 1) for b in sec_blocks]
            p_start = min(sec_parts) if sec_parts else 1
            p_end = max(sec_parts) if sec_parts else p_start

            method_name = "html_heading_tree" if payload.document_format == DocumentFormat.HTML else "pdf_heading_hierarchy"
            sections.append(CanonicalSection(
                section_id=sec_id,
                title=title,
                level=level,
                physical_page_start=p_start,
                physical_page_end=p_end,
                segmentation_method=method_name,
                confidence="high",
                parent_section_id=parent_sec_id,
                heading_path=heading_path,
                blocks=sec_blocks
            ))

            current_heading_block = None
            current_blocks = []

        for block in remaining_blocks:
            if block.block_type == BlockType.HEADING:
                _flush_html_section()
                current_heading_block = block
            else:
                current_blocks.append(block)

        _flush_html_section()

        return sections, warnings

    # =========================================================================
    # Priority 3: Table of Contents Matching
    # =========================================================================

    def _try_toc_discovery(
        self,
        payload: RawExtractionPayload
    ) -> Tuple[List[CanonicalSection], List[QualityWarning]]:
        """
        Attempts to discover sections by parsing Table of Contents entries on early pages
        (or captured in payload metadata) and matching them against verified printed page labels.
        """
        warnings: List[QualityWarning] = []
        total_pages = payload.total_physical_pages or len(payload.pages) or 1
        search_limit = min(15, len(payload.pages))

        # 1. Locate candidate TOC text
        toc_text: Optional[str] = None
        toc_source_page: Optional[int] = None

        for p in payload.pages[:search_limit]:
            if TOC_TITLE_REGEX.search(p.text):
                toc_text = p.text
                toc_source_page = p.physical_page
                break

        if not toc_text and payload.metadata.get("toc_text"):
            toc_text = str(payload.metadata.get("toc_text"))
            toc_source_page = payload.metadata.get("toc_page")

        if not toc_text:
            return [], []

        # 2. Extract and filter TOC entries: (title, printed_page_label)
        raw_matches = TOC_LINE_REGEX.findall(toc_text)
        clean_matches: List[Tuple[str, str]] = []
        for title, label in raw_matches:
            clean_t = title.strip()
            clean_l = label.strip()
            if TOC_NEGATIVE_REGEX.search(clean_t):
                continue
            if clean_t.lower() in {"contents", "contentscontents", "table of contents", "index"}:
                continue
            if clean_t.isdigit():
                continue
            if len(clean_t) < 3:
                continue
            clean_matches.append((clean_t, clean_l))

        if len(clean_matches) < 2:
            return [], []

        # 3. Match against detected printed page labels in payload
        printed_to_physical: Dict[str, int] = {}
        for p in payload.pages:
            if p.printed_page:
                printed_to_physical[p.printed_page.strip().lower()] = p.physical_page

        matched_sections: List[Tuple[str, int, str]] = []
        for title, label in clean_matches:
            phys_page = printed_to_physical.get(label.lower())
            if phys_page is not None:
                matched_sections.append((title, phys_page, label))

        # Fallback to automated TOC page offset calibration if direct matches are insufficient
        if len(matched_sections) < 3 and len(clean_matches) >= 3:
            calibrated_offset, cal_matches = self._calibrate_toc_offset(clean_matches, payload)
            if calibrated_offset is not None and len(cal_matches) >= 3:
                matched_sections = cal_matches
                msg = (
                    f"Calibrated TOC page offset: physical_page = printed_page + {calibrated_offset} "
                    f"(matched {len(matched_sections)}/{len(clean_matches)} sections with strict monotonic page ordering)."
                )
                logger.info(msg)
                warnings.append(QualityWarning(
                    category=WarningCategory.TOC_UNCERTAIN_OFFSET,
                    message=msg,
                    physical_page=toc_source_page
                ))

        # Special Case: Pre-TOC Front Matter / Preamble preservation
        # If TOC entries exist with high confidence, but all of them point to pages AFTER
        # the current extraction window (e.g. pages 1-19 sample where first TOC entry is p.18),
        # the current window is genuinely Document Front Matter.
        earliest_numeric_toc_page = None
        for _, label in clean_matches:
            if label.isdigit():
                val = int(label)
                if earliest_numeric_toc_page is None or val < earliest_numeric_toc_page:
                    earliest_numeric_toc_page = val

        max_printed_in_payload = None
        for p in payload.pages:
            if p.printed_page and p.printed_page.isdigit():
                val = int(p.printed_page)
                if max_printed_in_payload is None or val > max_printed_in_payload:
                    max_printed_in_payload = val

        max_phys_in_payload = max(p.physical_page for p in payload.pages) if payload.pages else 0
        is_pre_toc_window = (
            not matched_sections and 
            earliest_numeric_toc_page is not None and 
            (
                (max_printed_in_payload is not None and max_printed_in_payload < earliest_numeric_toc_page) or
                (max_printed_in_payload is None and max_phys_in_payload < earliest_numeric_toc_page)
            )
        )

        if is_pre_toc_window:
            
            all_blocks: List[ContentBlock] = [b for p in payload.pages for b in p.blocks]
            min_phys = min(p.physical_page for p in payload.pages)
            max_phys = max(p.physical_page for p in payload.pages)
            printed_start = payload.pages[0].printed_page if payload.pages else None
            printed_end = payload.pages[-1].printed_page if payload.pages else None

            front_matter_sec = CanonicalSection(
                section_id="sec_01",
                title="Document Front Matter",
                level=1,
                physical_page_start=min_phys,
                physical_page_end=max_phys,
                printed_page_start=printed_start,
                printed_page_end=printed_end,
                segmentation_method="toc_preamble",
                confidence="high",
                parent_section_id=None,
                heading_path=["Document Front Matter"],
                blocks=all_blocks
            )
            msg = (
                f"TOC detected on page {toc_source_page} with {len(clean_matches)} sections "
                f"starting at printed page {earliest_numeric_toc_page}. "
                f"Extraction window (pages {min_phys}-{max_phys}, printed {printed_start}-{printed_end}) "
                f"precedes first TOC section; preserved as Document Front Matter."
            )
            logger.info(msg)
            warnings.append(QualityWarning(
                category=WarningCategory.STRUCTURE_CONFIDENCE,
                message=msg,
                physical_page=toc_source_page,
                section_id="sec_01"
            ))
            return [front_matter_sec], warnings

        if not matched_sections:
            warnings.append(QualityWarning(
                category=WarningCategory.STRUCTURE_CONFIDENCE,
                message=f"TOC detected on page {toc_source_page}, but 0/{len(clean_matches)} entries matched verified printed page numbers in current payload."
            ))
            return [], warnings

        # Verify monotonic page ordering
        for i in range(len(matched_sections) - 1):
            if matched_sections[i][1] > matched_sections[i + 1][1]:
                warnings.append(QualityWarning(
                    category=WarningCategory.STRUCTURE_CONFIDENCE,
                    message="TOC entries resolved to non-monotonic physical page numbers; discarding TOC."
                ))
                return [], warnings

        # 4. Construct sections from matched TOC items
        page_map = {p.physical_page: p for p in payload.pages}
        sections: List[CanonicalSection] = []
        assigned_block_ids: Set[str] = set()

        first_matched_phys = matched_sections[0][1]
        min_payload_phys = min(p.physical_page for p in payload.pages)

        if first_matched_phys > min_payload_phys:
            preamble_blocks: List[ContentBlock] = []
            for p_num in range(min_payload_phys, first_matched_phys):
                if p_num in page_map:
                    for b in page_map[p_num].blocks:
                        if b.block_id not in assigned_block_ids:
                            preamble_blocks.append(b)
                            assigned_block_ids.add(b.block_id)

            p_first_rec = page_map.get(min_payload_phys)
            p_last_rec = page_map.get(first_matched_phys - 1)
            printed_p1 = p_first_rec.printed_page if p_first_rec else None
            printed_pend = p_last_rec.printed_page if p_last_rec else None
            if preamble_blocks:
                sections.append(CanonicalSection(
                    section_id="sec_00",
                    title="Document Front Matter",
                    level=1,
                    physical_page_start=min_payload_phys,
                    physical_page_end=first_matched_phys - 1,
                    printed_page_start=printed_p1,
                    printed_page_end=printed_pend,
                    segmentation_method="preamble_unclassified",
                    confidence="medium",
                    parent_section_id=None,
                    heading_path=["Document Front Matter"],
                    blocks=preamble_blocks
                ))

        genuine_sec_idx = 0
        for i, (title, start_page, start_label) in enumerate(matched_sections):
            genuine_sec_idx += 1
            sec_id = f"sec_{genuine_sec_idx:02d}"
            if i + 1 < len(matched_sections):
                next_start = matched_sections[i + 1][1]
                end_page = max(start_page, next_start - 1) if next_start > start_page else start_page
            else:
                end_page = max(start_page, total_pages)

            sec_blocks: List[ContentBlock] = []
            for p_num in range(start_page, end_page + 1):
                if p_num in page_map:
                    for b in page_map[p_num].blocks:
                        if b.block_id not in assigned_block_ids:
                            sec_blocks.append(b)
                            assigned_block_ids.add(b.block_id)

            confidence = "medium"
            if not sec_blocks and start_page in page_map and page_map[start_page].blocks:
                confidence = "low"
                warnings.append(QualityWarning(
                    category=WarningCategory.STRUCTURE_CONFIDENCE,
                    message=(
                        f"TOC section '{title}' (p.{start_page}) received 0 blocks; "
                        f"page content was already assigned to preceding section."
                    ),
                    physical_page=start_page,
                    section_id=sec_id
                ))

            p_end_rec = page_map.get(end_page)
            printed_end = p_end_rec.printed_page if p_end_rec else None

            sections.append(CanonicalSection(
                section_id=sec_id,
                title=title,
                level=1,
                physical_page_start=start_page,
                physical_page_end=end_page,
                printed_page_start=start_label,
                printed_page_end=printed_end,
                segmentation_method="toc_page_discovery",
                confidence=confidence,
                parent_section_id=None,
                heading_path=[title],
                blocks=sec_blocks
            ))

        return sections, warnings

    def _calibrate_toc_offset(
        self,
        clean_matches: List[Tuple[str, str]],
        payload: RawExtractionPayload,
    ) -> Tuple[Optional[int], List[Tuple[str, int, str]]]:
        """
        Calibrates physical page offset for TOC entries when explicit printed page headers
        are absent or sparse in the document body (e.g. standalone first-line page numbers).
        Tests candidate offsets (e.g. -2 to +12) and checks if key title words appear on
        the calculated physical page (printed_num + offset).
        Returns:
            (best_offset, matched_sections) if calibration succeeds with high confidence,
            else (None, []).
        """
        numeric_entries: List[Tuple[str, int, str]] = []
        for title, label in clean_matches:
            if label.strip().isdigit():
                numeric_entries.append((title, int(label.strip()), label.strip()))

        if len(numeric_entries) < 3:
            return None, []

        page_text_map: Dict[int, str] = {p.physical_page: p.text for p in payload.pages}

        def _title_matches_page(title: str, text: str) -> bool:
            clean_title = re.sub(r"[^a-zA-Z0-9\s]", " ", title).lower()
            words = [w for w in clean_title.split() if len(w) > 3 and w not in {"report", "annual", "hudco"}]
            if not words:
                words = [w for w in clean_title.split() if len(w) > 2]
            if not words:
                return False
            clean_page = re.sub(r"[^a-zA-Z0-9\s]", " ", text).lower()
            matches = sum(1 for w in words if w in clean_page)
            required = min(len(words), 2 if len(words) >= 2 else 1)
            return matches >= required

        best_offset: Optional[int] = None
        best_matches: List[Tuple[str, int, str]] = []
        max_matched = 0

        for offset in range(-2, 13):
            candidate_matches: List[Tuple[str, int, str]] = []
            for title, printed_num, label_str in numeric_entries:
                phys = printed_num + offset
                if phys in page_text_map:
                    if _title_matches_page(title, page_text_map[phys]):
                        candidate_matches.append((title, phys, label_str))

            # Verify strictly monotonic ordering
            is_monotonic = True
            for i in range(len(candidate_matches) - 1):
                if candidate_matches[i][1] >= candidate_matches[i + 1][1]:
                    is_monotonic = False
                    break

            if is_monotonic and len(candidate_matches) > max_matched:
                max_matched = len(candidate_matches)
                best_offset = offset
                best_matches = candidate_matches

        # Require at least 3 matches and at least 30% of numeric entries
        if best_offset is not None and max_matched >= 3 and (max_matched >= len(numeric_entries) * 0.3):
            return best_offset, best_matches

        return None, []

    # =========================================================================
    # Priority 4: Page-Level Heading Signals
    # =========================================================================

    def _try_page_heading_signals(
        self,
        payload: RawExtractionPayload
    ) -> Tuple[List[CanonicalSection], List[QualityWarning]]:
        """Discovers sections from prominent chapter headings at the top of pages."""
        candidate_headings: List[Tuple[int, str]] = []
        for p in payload.pages:
            lines = [line.strip() for line in p.text.split("\n") if line.strip()]
            if lines:
                first_line = lines[0]
                if 5 < len(first_line) < 80:
                    if (first_line.isupper() or first_line.istitle()) and not any(c.isdigit() for c in first_line[:3]):
                        candidate_headings.append((p.physical_page, first_line))

        # Filter out running headers or slogans that repeat across 3 or more pages
        from collections import Counter
        heading_counts = Counter(h for _, h in candidate_headings)
        candidate_headings = [(p, h) for p, h in candidate_headings if heading_counts[h] < 3]

        if len(candidate_headings) < 2:
            return [], []

        total_pages = payload.total_physical_pages or len(payload.pages) or 1
        page_map = {p.physical_page: p for p in payload.pages}
        sections: List[CanonicalSection] = []
        assigned_block_ids: Set[str] = set()

        for i, (start_page, title) in enumerate(candidate_headings):
            sec_idx = i + 1
            sec_id = f"sec_{sec_idx:02d}"
            if i + 1 < len(candidate_headings):
                next_start = candidate_headings[i + 1][0]
                end_page = max(start_page, next_start - 1) if next_start > start_page else start_page
            else:
                end_page = max(start_page, total_pages)

            sec_blocks: List[ContentBlock] = []
            for p_num in range(start_page, end_page + 1):
                if p_num in page_map:
                    for b in page_map[p_num].blocks:
                        if b.block_id not in assigned_block_ids:
                            sec_blocks.append(b)
                            assigned_block_ids.add(b.block_id)

            p_start_rec = page_map.get(start_page)
            p_end_rec = page_map.get(end_page)
            printed_start = p_start_rec.printed_page if p_start_rec else None
            printed_end = p_end_rec.printed_page if p_end_rec else None

            sections.append(CanonicalSection(
                section_id=sec_id,
                title=title,
                level=1,
                physical_page_start=start_page,
                physical_page_end=end_page,
                printed_page_start=printed_start,
                printed_page_end=printed_end,
                segmentation_method="heading_heuristic",
                confidence="medium",
                parent_section_id=None,
                heading_path=[title],
                blocks=sec_blocks
            ))

        return sections, []

    # =========================================================================
    # Priority 5: Conservative Heuristic Fallback
    # =========================================================================

    def _build_conservative_fallback(
        self,
        payload: RawExtractionPayload,
        metadata: DocumentMetadata
    ) -> Tuple[List[CanonicalSection], List[QualityWarning]]:
        """Conservative fallback when no structural evidence is detectable. Zero content loss."""
        all_blocks: List[ContentBlock] = [b for p in payload.pages for b in p.blocks]
        total_pages = payload.total_physical_pages or len(payload.pages) or 1
        title = metadata.title_hint or payload.metadata.get("Title") or payload.metadata.get("title") or "Document Body"

        printed_start = payload.pages[0].printed_page if payload.pages else None
        printed_end = payload.pages[-1].printed_page if payload.pages else None

        section = CanonicalSection(
            section_id="sec_01",
            title=title,
            level=1,
            physical_page_start=1,
            physical_page_end=max(1, total_pages),
            printed_page_start=printed_start,
            printed_page_end=printed_end,
            segmentation_method="fallback",
            confidence="low",
            parent_section_id=None,
            heading_path=[title],
            blocks=all_blocks
        )

        warning = QualityWarning(
            category=WarningCategory.STRUCTURE_CONFIDENCE,
            message="No explicit outline, TOC, or heading hierarchy detected; document treated as single unified section."
        )

        return [section], [warning]

    # =========================================================================
    # Helper: Synthesize Default DocumentMetadata
    # =========================================================================

    def _build_default_metadata(
        self,
        payload: RawExtractionPayload,
        document_id: Optional[str] = None
    ) -> DocumentMetadata:
        """Constructs canonical DocumentMetadata from extraction payload."""
        total_pages = payload.total_physical_pages or len(payload.pages) or 1
        full_text = "".join(p.text for p in payload.pages)
        sha256_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", payload.source_filename.rsplit(".", 1)[0]).lower()
        doc_id = document_id or f"doc_{clean_name}"

        return DocumentMetadata(
            document_id=doc_id,
            source_id=f"src_{clean_name}",
            version_id=f"{doc_id}_v1_{sha256_hash[:8]}",
            version_number=1,
            source_filename=payload.source_filename,
            source_url=payload.metadata.get("source_url"),
            document_format=payload.document_format,
            content_sha256=sha256_hash,
            file_size_bytes=len(full_text.encode("utf-8")),
            total_physical_pages=total_pages,
            title_hint=payload.metadata.get("Title") or payload.metadata.get("title")
        )
