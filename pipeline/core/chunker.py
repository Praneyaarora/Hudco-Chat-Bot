"""
Hierarchical Section-Aware Chunking Engine.
File: pipeline/core/chunker.py

Consumes a validated CanonicalDocument and produces atomic, section-bounded,
hierarchical CanonicalChunk objects.
Guarantees:
- Strict section boundary respect (chunks never cross sections).
- Table integrity preservation (tables are treated as indivisible units with structured data).
- Paragraph integrity preservation (paragraphs are kept intact where practical).
- Exact heading breadcrumb assignment (text before a heading never inherits subsequent headings).
- Full provenance propagation (locators, physical pages, printed pages, ancestor breadcrumbs).
- Bounded, section-isolated chunk overlap with explicit parameter validation.
- Multi-dimensional deterministic chunk ID generation with content hashes and processing revisions.
- Zero empty/whitespace chunks emitted.
"""

import re
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple

from pipeline.core.contracts import (
    BlockType,
    WarningCategory,
    QualityWarning,
    ContentBlock,
    CanonicalSection,
    CanonicalDocument,
    CanonicalChunk,
    StructuredTable,
    SourceLocator,
)
from pipeline.utils.text_normalizer import is_empty_or_whitespace

logger = logging.getLogger("HierarchicalChunker")


class HierarchicalChunker:
    """
    Produces deterministic, section-bounded knowledge chunks from a CanonicalDocument.

    Chunk Overlap Contract:
    -----------------------
    In this pipeline, `chunk_overlap` specifies a whole-block character budget, NOT an arbitrary
    character-level slice. Slicing narrative text mid-word or mid-sentence creates fragmented tokens,
    destroys financial numbers and entities, and degrades retrieval precision.
    Therefore:
    1. Only complete, intact narrative blocks (PARAGRAPH or LIST) are carried over as overlap.
    2. A trailing block is carried forward if and only if:
       a) block.block_type in {BlockType.PARAGRAPH, BlockType.LIST}
       b) len(block.text_content) <= chunk_overlap
       c) len(block.text_content) + next_block_len <= max_chunk_size (preventing artificial chunk-length warnings)
    3. Tables (BlockType.TABLE) and headings (BlockType.HEADING) are NEVER duplicated as overlap.
    4. Overlap is strictly section-bounded; chunks never cross section boundaries.
    5. Validated contract: 0 <= chunk_overlap < target_chunk_size <= max_chunk_size.
    """

    def __init__(
        self,
        target_chunk_size: int = 1200,
        max_chunk_size: int = 2500,
        chunk_overlap: Optional[int] = None,
        processing_revision: int = 1
    ):
        """
        Initializes HierarchicalChunker.

        :param target_chunk_size: Target soft limit for chunk character length (must be > 0).
        :param max_chunk_size: Hard limit before emitting CHUNK_TOO_LONG warnings (must be >= target_chunk_size).
        :param chunk_overlap: Whole-block character budget for paragraph/list carryover (must satisfy 0 <= chunk_overlap < target_chunk_size).
                              Defaults to min(150, max(0, target_chunk_size // 5)).
        :param processing_revision: Monotonic revision number for chunk ID determinism (must be >= 1).
        """
        if target_chunk_size <= 0:
            raise ValueError(f"target_chunk_size must be positive, got {target_chunk_size}")
        if max_chunk_size < target_chunk_size:
            raise ValueError(f"max_chunk_size ({max_chunk_size}) cannot be less than target_chunk_size ({target_chunk_size})")

        if chunk_overlap is None:
            chunk_overlap = min(150, max(0, target_chunk_size // 5))

        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= target_chunk_size:
            raise ValueError(f"chunk_overlap ({chunk_overlap}) must be strictly less than target_chunk_size ({target_chunk_size})")
        if processing_revision < 1:
            raise ValueError(f"processing_revision must be >= 1, got {processing_revision}")

        self.target_chunk_size = target_chunk_size
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.processing_revision = processing_revision

    def chunk_document(
        self,
        doc: CanonicalDocument
    ) -> Tuple[List[CanonicalChunk], List[QualityWarning]]:
        """
        Processes a CanonicalDocument into an ordered list of CanonicalChunks.
        Preserves section hierarchy, table integrity, and provenance.
        """
        chunks: List[CanonicalChunk] = []
        warnings: List[QualityWarning] = []

        # Track per-(section, page) chunk indexing for deterministic identifiers
        chunk_counters: Dict[Tuple[str, int], int] = {}

        for section in doc.sections:
            sec_chunks, sec_warnings = self._chunk_section(
                doc=doc,
                section=section,
                chunk_counters=chunk_counters
            )
            chunks.extend(sec_chunks)
            warnings.extend(sec_warnings)

        return chunks, warnings

    def _chunk_section(
        self,
        doc: CanonicalDocument,
        section: CanonicalSection,
        chunk_counters: Dict[Tuple[str, int], int]
    ) -> Tuple[List[CanonicalChunk], List[QualityWarning]]:
        """Chunks a single CanonicalSection without crossing boundaries."""
        chunks: List[CanonicalChunk] = []
        warnings: List[QualityWarning] = []

        current_blocks: List[ContentBlock] = []
        current_len = 0
        # Initialize breadcrumbs from section's ancestral heading_path
        active_headings: List[str] = list(section.heading_path) if section.heading_path else [section.title]

        for block in section.blocks:
            if is_empty_or_whitespace(block.text_content):
                continue

            # Case 1: Heading Encountered within section
            if block.block_type == BlockType.HEADING:
                # Flush preceding text with the PRIOR heading ancestry (never inherit future headings)
                if current_blocks:
                    flushed = self._create_chunk(
                        doc=doc,
                        section=section,
                        blocks=current_blocks,
                        ancestor_headings=list(active_headings),
                        chunk_counters=chunk_counters
                    )
                    if flushed:
                        chunks.append(flushed)
                    current_blocks = []
                    current_len = 0

                # Update heading ancestry with this new heading
                heading_text = block.text_content.strip()
                level = min(3, max(1, block.heading_level or 2))
                if level <= len(active_headings):
                    active_headings = active_headings[:level - 1] + [heading_text]
                else:
                    active_headings.append(heading_text)

                current_blocks = [block]
                current_len = len(block.text_content)
                continue

            # Case 2: Indivisible Tables
            if block.block_type == BlockType.TABLE:
                # Flush narrative buffer before emitting table chunk
                if current_blocks:
                    flushed = self._create_chunk(
                        doc=doc,
                        section=section,
                        blocks=current_blocks,
                        ancestor_headings=list(active_headings),
                        chunk_counters=chunk_counters
                    )
                    if flushed:
                        chunks.append(flushed)
                    current_blocks = []
                    current_len = 0

                # Check if table exceeds max_chunk_size
                table_len = len(block.text_content)
                table_warnings: List[str] = []
                if table_len > self.max_chunk_size:
                    msg = f"Table {block.table_data.table_id if block.table_data else 'unknown'} length ({table_len}) exceeds max_chunk_size ({self.max_chunk_size}); preserved intact."
                    table_warnings.append(msg)
                    warnings.append(QualityWarning(
                        category=WarningCategory.CHUNK_TOO_LONG,
                        message=msg,
                        physical_page=getattr(block.locator, "physical_page", section.physical_page_start),
                        section_id=section.section_id,
                        block_id=block.block_id
                    ))

                # Emit dedicated table chunk (tables never carry forward overlap)
                table_chunk = self._create_chunk(
                    doc=doc,
                    section=section,
                    blocks=[block],
                    ancestor_headings=list(active_headings),
                    chunk_counters=chunk_counters,
                    additional_warnings=table_warnings
                )
                if table_chunk:
                    chunks.append(table_chunk)
                continue

            # Case 3: Narrative text blocks (PARAGRAPH, LIST)
            block_len = len(block.text_content)

            # Check if adding this block exceeds target_chunk_size or if block itself exceeds max_chunk_size
            if current_blocks and (current_len + block_len > self.target_chunk_size or block_len > self.max_chunk_size):
                flushed = self._create_chunk(
                    doc=doc,
                    section=section,
                    blocks=current_blocks,
                    ancestor_headings=list(active_headings),
                    chunk_counters=chunk_counters
                )
                if flushed:
                    chunks.append(flushed)

                # Compute bounded whole-block overlap within the section (only if block <= max_chunk_size)
                overlap_blocks: List[ContentBlock] = []
                if self.chunk_overlap > 0 and block_len <= self.max_chunk_size:
                    last_b = current_blocks[-1]
                    if (last_b.block_type in {BlockType.PARAGRAPH, BlockType.LIST}
                            and len(last_b.text_content) <= self.chunk_overlap):
                        if len(last_b.text_content) + block_len <= self.max_chunk_size:
                            overlap_blocks = [last_b]

                current_blocks = overlap_blocks
                current_len = sum(len(b.text_content) for b in current_blocks)

            # Check if block alone exceeds max_chunk_size
            if block_len > self.max_chunk_size:
                msg = f"Narrative block {block.block_id} length ({block_len}) exceeds max_chunk_size ({self.max_chunk_size}); preserved intact."
                warnings.append(QualityWarning(
                    category=WarningCategory.CHUNK_TOO_LONG,
                    message=msg,
                    physical_page=getattr(block.locator, "physical_page", section.physical_page_start),
                    section_id=section.section_id,
                    block_id=block.block_id
                ))
                flushed = self._create_chunk(
                    doc=doc,
                    section=section,
                    blocks=[block],
                    ancestor_headings=list(active_headings),
                    chunk_counters=chunk_counters,
                    additional_warnings=[msg]
                )
                if flushed:
                    chunks.append(flushed)
                current_blocks = []
                current_len = 0
                continue

            current_blocks.append(block)
            current_len += block_len

        # Flush any remaining narrative blocks at the end of the section
        if current_blocks:
            flushed = self._create_chunk(
                doc=doc,
                section=section,
                blocks=current_blocks,
                ancestor_headings=list(active_headings),
                chunk_counters=chunk_counters
            )
            if flushed:
                chunks.append(flushed)

        return chunks, warnings

    def _create_chunk(
        self,
        doc: CanonicalDocument,
        section: CanonicalSection,
        blocks: List[ContentBlock],
        ancestor_headings: List[str],
        chunk_counters: Dict[Tuple[str, int], int],
        additional_warnings: Optional[List[str]] = None
    ) -> Optional[CanonicalChunk]:
        """Constructs and validates a single CanonicalChunk from buffered blocks."""
        if not blocks:
            return None

        content = "\n\n".join(b.text_content for b in blocks).strip()
        if is_empty_or_whitespace(content):
            return None

        char_count = len(content)
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        token_estimate = max(1, char_count // 4)

        # Primary locator and page resolution across all contributing blocks
        primary_block = blocks[0]
        locator: Optional[SourceLocator] = primary_block.locator

        phys_pages_set = set()
        print_pages_list: List[str] = []
        for b in blocks:
            loc = b.locator
            if loc and getattr(loc, "physical_page", None) is not None:
                phys_pages_set.add(loc.physical_page)
            if loc and getattr(loc, "printed_page", None) is not None:
                p_str = str(loc.printed_page).strip()
                if p_str and p_str not in print_pages_list:
                    print_pages_list.append(p_str)

        if not phys_pages_set:
            phys_pages = [section.physical_page_start]
        else:
            phys_pages = sorted(phys_pages_set)

        phys_page_start = phys_pages[0]
        phys_page_end = phys_pages[-1] if len(phys_pages) > 1 else None

        print_page_start = print_pages_list[0] if print_pages_list else (section.printed_page_start or None)
        print_page_end = print_pages_list[-1] if len(print_pages_list) > 1 else None

        # Increment (section, page) chunk index for deterministic ID based on start page
        key = (section.section_id, phys_page_start)
        chunk_idx = chunk_counters.get(key, 0)
        chunk_counters[key] = chunk_idx + 1

        chunk_id = CanonicalChunk.generate_chunk_id(
            document_id=doc.metadata.document_id,
            version_number=doc.metadata.version_number,
            content_sha256=content_sha256,
            section_id=section.section_id,
            physical_page=phys_page_start,
            chunk_index=chunk_idx,
            processing_revision=self.processing_revision
        )

        tables: List[StructuredTable] = [b.table_data for b in blocks if b.table_data is not None]
        has_table = len(tables) > 0

        warnings_list: List[str] = list(additional_warnings or [])
        if any(t.is_malformed for t in tables):
            warnings_list.append("CONTAINS_MALFORMED_TABLE")

        return CanonicalChunk(
            chunk_id=chunk_id,
            document_id=doc.metadata.document_id,
            version_id=doc.metadata.version_id,
            source_id=doc.metadata.source_id,
            source_filename=doc.metadata.source_filename,
            section_id=section.section_id,
            section_title=section.title,
            physical_page=phys_page_start,
            physical_page_end=phys_page_end,
            physical_pages=phys_pages,
            printed_page=print_page_start,
            printed_page_end=print_page_end,
            printed_pages=print_pages_list,
            chunk_index_in_page=chunk_idx,
            has_table=has_table,
            char_count=char_count,
            token_estimate=token_estimate,
            content=content,
            content_sha256=content_sha256,
            structured_tables=tables,
            ancestor_headings=ancestor_headings,
            source_block_ids=[b.block_id for b in blocks],
            locator=locator,
            warnings=warnings_list,
            is_stale=False,
            processing_revision=self.processing_revision,
            fiscal_year=getattr(doc.metadata, "fiscal_year", None) or getattr(doc.metadata, "fiscal_year_hint", None),
            reporting_period=None,
            report_title=getattr(doc.metadata, "report_title", None) or getattr(doc.metadata, "title_hint", None),
        )

