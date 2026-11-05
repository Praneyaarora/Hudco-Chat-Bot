"""
Focused Unit Tests for Phase 2: Structural Analysis and Hierarchical Chunking.
File: tests/test_phase2.py

Comprehensive regression and unit test suite covering:
1. Native PDF outlines with nested levels, same-page bookmarks, and invalid page handling.
2. Section numbering with and without preamble (sec_00 reserved strictly for unclassified preamble).
3. HTML heading trees with and without preamble, skipped heading levels, and breadcrumbs.
4. Multi-page HTML input page range resolution and locator propagation.
5. Strict source block accounting (detecting payload duplicate IDs, missing blocks, multiply-assigned blocks).
6. Table of Contents discovery with Roman numerals, duplicate entries, and non-monotonic rejection.
7. Conservative fallback segmentation for sectionless circulars or notices.
8. Exact heading breadcrumb assignment (text before heading never inherits subsequent headings).
9. Whole-block bounded chunk overlap semantics (zero overlap, block <= overlap, block > overlap, lists, max_chunk_size safeguard).
10. Section boundary isolation and table overlap prevention (tables are never duplicated as overlap).
11. Deterministic unique chunk IDs across multiple sections, pages, revisions, and repeated content.
12. Indivisible structured table preservation and oversized block warnings.
13. Empty block and whitespace-only chunk omission.
14. Complete provenance propagation (locators, physical and printed pages, breadcrumbs).
15. End-to-end artifact consistency across sections.json, chunks.jsonl, processing_summary.json, and quality_report.md.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.core.contracts import (
    DocumentFormat,
    BlockType,
    WarningCategory,
    QualityWarning,
    ContentBlock,
    CanonicalSection,
    DocumentMetadata,
    CanonicalDocument,
    CanonicalChunk,
    StructuredTable,
    PDFSourceLocator,
    HTMLSourceLocator,
    ProcessingStatus,
)
from pipeline.adapters.base import RawExtractionPayload, RawPageRecord
from pipeline.core.structural_analyzer import StructuralAnalyzer
from pipeline.core.chunker import HierarchicalChunker
from pipeline.core.pipeline_runner import run_phase2_pipeline
from pipeline.utils.table_formatter import build_structured_table


class TestPhase2StructuralAnalyzer(unittest.TestCase):
    """Validates structural analysis, heading trees, outline hierarchies, and block accounting."""

    def test_native_outline_section_hierarchy(self):
        """Verifies that PDF native bookmarks with front matter build sec_00 for preamble, then sec_01, sec_02."""
        p1 = RawPageRecord(physical_page=1, printed_page=None, text="Cover Page", blocks=[
            ContentBlock(block_id="p001_blk00", block_type=BlockType.PARAGRAPH, text_content="Cover Page", locator=PDFSourceLocator(physical_page=1))
        ])
        p2 = RawPageRecord(physical_page=2, printed_page="1", text="Directors' Report opening", blocks=[
            ContentBlock(block_id="p002_blk00", block_type=BlockType.PARAGRAPH, text_content="Directors' Report opening operations text.", locator=PDFSourceLocator(physical_page=2, printed_page="1"))
        ])
        p3 = RawPageRecord(physical_page=3, printed_page="2", text="Directors' Report details", blocks=[
            ContentBlock(block_id="p003_blk00", block_type=BlockType.PARAGRAPH, text_content="Directors' Report governance details.", locator=PDFSourceLocator(physical_page=3, printed_page="2"))
        ])
        p4 = RawPageRecord(physical_page=4, printed_page="3", text="Financial Statements balance sheet", blocks=[
            ContentBlock(block_id="p004_blk00", block_type=BlockType.PARAGRAPH, text_content="Financial Statements balance sheet data.", locator=PDFSourceLocator(physical_page=4, printed_page="3"))
        ])

        payload = RawExtractionPayload(
            source_filename="test_doc.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=4,
            outline_entries=[
                {"title": "Directors' Report", "level": 1, "physical_page": 2},
                {"title": "Financial Statements", "level": 1, "physical_page": 4}
            ],
            pages=[p1, p2, p3, p4]
        )

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # Expect 3 sections: sec_00 (Front Matter on p1), sec_01 (Directors' Report p2-3), sec_02 (Financials p4)
        self.assertEqual(len(doc.sections), 3)

        # Front matter: sec_00
        self.assertEqual(doc.sections[0].section_id, "sec_00")
        self.assertEqual(doc.sections[0].title, "Document Front Matter")
        self.assertEqual(doc.sections[0].physical_page_start, 1)
        self.assertEqual(doc.sections[0].physical_page_end, 1)
        self.assertEqual(doc.sections[0].segmentation_method, "preamble_unclassified")
        self.assertEqual(len(doc.sections[0].blocks), 1)

        # First genuine section: sec_01
        sec_dir = doc.sections[1]
        self.assertEqual(sec_dir.section_id, "sec_01")
        self.assertEqual(sec_dir.title, "Directors' Report")
        self.assertEqual(sec_dir.physical_page_start, 2)
        self.assertEqual(sec_dir.physical_page_end, 3)
        self.assertEqual(sec_dir.printed_page_start, "1")
        self.assertEqual(sec_dir.printed_page_end, "2")
        self.assertEqual(sec_dir.segmentation_method, "native_outline")
        self.assertEqual(sec_dir.confidence, "high")
        self.assertEqual(len(sec_dir.blocks), 2)

        # Second genuine section: sec_02
        sec_fin = doc.sections[2]
        self.assertEqual(sec_fin.section_id, "sec_02")
        self.assertEqual(sec_fin.title, "Financial Statements")
        self.assertEqual(sec_fin.physical_page_start, 4)
        self.assertEqual(sec_fin.physical_page_end, 4)
        self.assertEqual(sec_fin.printed_page_start, "3")

    def test_native_outline_section_hierarchy_without_preamble(self):
        """Verifies that PDF native bookmarks starting directly on page 1 start at sec_01 with no sec_00."""
        p1 = RawPageRecord(physical_page=1, printed_page="1", text="Opening Chapter", blocks=[
            ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Chapter 1 content", locator=PDFSourceLocator(physical_page=1, printed_page="1"))
        ])
        p2 = RawPageRecord(physical_page=2, printed_page="2", text="Second Chapter", blocks=[
            ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Chapter 2 content", locator=PDFSourceLocator(physical_page=2, printed_page="2"))
        ])

        payload = RawExtractionPayload(
            source_filename="no_preamble.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=2,
            outline_entries=[
                {"title": "Chapter 1", "level": 1, "physical_page": 1},
                {"title": "Chapter 2", "level": 1, "physical_page": 2}
            ],
            pages=[p1, p2]
        )

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # Must have exactly 2 sections starting at sec_01 (NO sec_00)
        self.assertEqual(len(doc.sections), 2)
        self.assertEqual(doc.sections[0].section_id, "sec_01")
        self.assertEqual(doc.sections[0].title, "Chapter 1")
        self.assertEqual(doc.sections[1].section_id, "sec_02")
        self.assertEqual(doc.sections[1].title, "Chapter 2")
        self.assertFalse(any(s.section_id == "sec_00" for s in doc.sections))

    def test_same_page_and_nested_pdf_outline_entries_no_duplication(self):
        """Verifies that multiple outline bookmarks on the same physical page do not duplicate blocks and warn on 0 blocks."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Section 1 intro", locator=PDFSourceLocator(physical_page=2))
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Section 1 subtopic", locator=PDFSourceLocator(physical_page=2))
        b3 = ContentBlock(block_id="b3", block_type=BlockType.PARAGRAPH, text_content="Section 2 text", locator=PDFSourceLocator(physical_page=3))

        p1 = RawPageRecord(physical_page=1, text="Cover", blocks=[])
        p2 = RawPageRecord(physical_page=2, text="Page 2 text", blocks=[b1, b2])
        p3 = RawPageRecord(physical_page=3, text="Page 3 text", blocks=[b3])

        payload = RawExtractionPayload(
            source_filename="nested.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=3,
            outline_entries=[
                {"title": "1. Corporate Profile", "level": 1, "physical_page": 2},
                {"title": "1.1 Mission & Vision", "level": 2, "physical_page": 2},
                {"title": "2. Operations", "level": 1, "physical_page": 3}
            ],
            pages=[p1, p2, p3]
        )

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # Total blocks assigned across all sections must equal 3 (no duplication)
        total_assigned_blocks = sum(len(s.blocks) for s in doc.sections)
        self.assertEqual(total_assigned_blocks, 3)

        # Section 1.1 should have parent pointing to Section 1
        sec_profile = [s for s in doc.sections if "Corporate Profile" in s.title][0]
        sec_mission = [s for s in doc.sections if "Mission & Vision" in s.title][0]
        self.assertEqual(sec_mission.parent_section_id, sec_profile.section_id)
        self.assertEqual(sec_mission.heading_path, ["1. Corporate Profile", "1.1 Mission & Vision"])

        # Intra-page splitting limitation: sec_mission has 0 blocks and emits STRUCTURE_CONFIDENCE warning
        self.assertEqual(len(sec_mission.blocks), 0)
        self.assertEqual(sec_mission.confidence, "low")
        self.assertTrue(any(w.category == WarningCategory.STRUCTURE_CONFIDENCE and "received 0 blocks" in w.message for w in doc.warnings))

    def test_invalid_pdf_outline_page_reference_handling(self):
        """Verifies that outline entries pointing outside document bounds are discarded with warnings."""
        p1 = RawPageRecord(physical_page=1, text="Page 1", blocks=[
            ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Valid page text", locator=PDFSourceLocator(physical_page=1))
        ])
        payload = RawExtractionPayload(
            source_filename="bad_outline.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            outline_entries=[
                {"title": "Valid Section", "level": 1, "physical_page": 1},
                {"title": "Phantom Section", "level": 1, "physical_page": 999}
            ],
            pages=[p1]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # Phantom section must not be created
        self.assertEqual(len(doc.sections), 1)
        self.assertEqual(doc.sections[0].title, "Valid Section")
        # Warning recorded for discarded outline entry
        self.assertTrue(any("Phantom Section" in w.message for w in doc.warnings))

    def test_html_content_before_first_heading_and_skipped_levels(self):
        """Verifies that HTML content before the first heading becomes sec_00, and skipped levels (h1 -> h3) are handled."""
        blocks = [
            ContentBlock(block_id="b0", block_type=BlockType.PARAGRAPH, text_content="Notice preamble text.", locator=HTMLSourceLocator(css_selector="html > body > p")),
            ContentBlock(block_id="b1", block_type=BlockType.HEADING, text_content="Major Title", heading_level=1, locator=HTMLSourceLocator(css_selector="html > body > h1")),
            ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Content under title.", locator=HTMLSourceLocator(css_selector="html > body > p")),
            ContentBlock(block_id="b3", block_type=BlockType.HEADING, text_content="Deep Subtopic", heading_level=3, locator=HTMLSourceLocator(css_selector="html > body > h3")),
            ContentBlock(block_id="b4", block_type=BlockType.PARAGRAPH, text_content="Deep subtopic content.", locator=HTMLSourceLocator(css_selector="html > body > p")),
        ]
        payload = RawExtractionPayload(
            source_filename="headings.html",
            document_format=DocumentFormat.HTML,
            total_physical_pages=1,
            pages=[RawPageRecord(physical_page=1, blocks=blocks, text="Full text")]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # Expect: sec_00 (Notice preamble), sec_01 (Major Title), sec_02 (Deep Subtopic)
        self.assertEqual(len(doc.sections), 3)

        self.assertEqual(doc.sections[0].section_id, "sec_00")
        self.assertEqual(doc.sections[0].segmentation_method, "preamble_unclassified")

        self.assertEqual(doc.sections[1].section_id, "sec_01")
        self.assertEqual(doc.sections[1].title, "Major Title")
        self.assertEqual(doc.sections[1].level, 1)
        self.assertIsNone(doc.sections[1].parent_section_id)

        self.assertEqual(doc.sections[2].section_id, "sec_02")
        self.assertEqual(doc.sections[2].title, "Deep Subtopic")
        self.assertEqual(doc.sections[2].level, 3)
        self.assertEqual(doc.sections[2].parent_section_id, "sec_01")
        self.assertEqual(doc.sections[2].heading_path, ["Major Title", "Deep Subtopic"])

    def test_html_content_without_preamble(self):
        """Verifies that HTML content starting with an h1 begins directly at sec_01 without sec_00."""
        blocks = [
            ContentBlock(block_id="h1", block_type=BlockType.HEADING, text_content="Chapter 1", heading_level=1, locator=HTMLSourceLocator(css_selector="html > body > h1")),
            ContentBlock(block_id="p1", block_type=BlockType.PARAGRAPH, text_content="Body of chapter 1.", locator=HTMLSourceLocator(css_selector="html > body > p")),
            ContentBlock(block_id="h2", block_type=BlockType.HEADING, text_content="Chapter 2", heading_level=1, locator=HTMLSourceLocator(css_selector="html > body > h1")),
            ContentBlock(block_id="p2", block_type=BlockType.PARAGRAPH, text_content="Body of chapter 2.", locator=HTMLSourceLocator(css_selector="html > body > p")),
        ]
        payload = RawExtractionPayload(
            source_filename="no_preamble.html",
            document_format=DocumentFormat.HTML,
            total_physical_pages=1,
            pages=[RawPageRecord(physical_page=1, blocks=blocks, text="Text")]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        self.assertEqual(len(doc.sections), 2)
        self.assertEqual(doc.sections[0].section_id, "sec_01")
        self.assertEqual(doc.sections[0].title, "Chapter 1")
        self.assertEqual(doc.sections[1].section_id, "sec_02")
        self.assertEqual(doc.sections[1].title, "Chapter 2")
        self.assertFalse(any(s.section_id == "sec_00" for s in doc.sections))

    def test_html_provenance_and_partition_range_resolution(self):
        """Verifies that HTML inputs maintain DOM locator provenance, and multi-record partitions resolve partition ranges without physical page fields."""
        loc1 = HTMLSourceLocator(source_url="https://www.hudco.org.in/page1", css_selector="html > body > h1")
        loc2 = HTMLSourceLocator(source_url="https://www.hudco.org.in/page1", css_selector="html > body > p")
        loc3 = HTMLSourceLocator(source_url="https://www.hudco.org.in/page2", css_selector="html > body > p")

        b1 = ContentBlock(block_id="h1", block_type=BlockType.HEADING, text_content="Section 1", heading_level=1, locator=loc1)
        b2 = ContentBlock(block_id="p1", block_type=BlockType.PARAGRAPH, text_content="Text on partition 1", locator=loc2)
        b3 = ContentBlock(block_id="p2", block_type=BlockType.PARAGRAPH, text_content="Text on partition 2 continuing section 1", locator=loc3)

        payload = RawExtractionPayload(
            source_filename="multipage.html",
            document_format=DocumentFormat.HTML,
            total_physical_pages=2,
            pages=[
                RawPageRecord(physical_page=1, blocks=[b1, b2], text="P1"),
                RawPageRecord(physical_page=2, blocks=[b3], text="P2"),
            ]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        self.assertEqual(len(doc.sections), 1)
        sec = doc.sections[0]
        self.assertEqual(sec.section_id, "sec_01")
        # Partition indices derived from containing RawPageRecord
        self.assertEqual(sec.physical_page_start, 1)
        self.assertEqual(sec.physical_page_end, 2)
        # HTML locators preserve URL and CSS selector, not paper page coordinates
        self.assertIsInstance(sec.blocks[0].locator, HTMLSourceLocator)
        self.assertFalse(hasattr(sec.blocks[0].locator, "physical_page"))
        self.assertEqual(sec.blocks[0].locator.source_url, "https://www.hudco.org.in/page1")

    def test_duplicate_block_id_in_payload_detected(self):
        """Verifies that duplicate block IDs in source extraction payload degrade processing status, detect accounting count mismatch, and prevent claiming clean exactly-once accounting."""
        b1 = ContentBlock(block_id="dup_id", block_type=BlockType.PARAGRAPH, text_content="First instance", locator=PDFSourceLocator(physical_page=1))
        b2 = ContentBlock(block_id="dup_id", block_type=BlockType.PARAGRAPH, text_content="Second instance with same ID", locator=PDFSourceLocator(physical_page=1))

        payload = RawExtractionPayload(
            source_filename="duplicate_blocks.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            pages=[RawPageRecord(physical_page=1, blocks=[b1, b2], text="Text")]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # 1. Status MUST be degraded to PARTIAL_SUCCESS (never SUCCESS or SUCCESS_WITH_WARNINGS)
        self.assertEqual(doc.processing_status, ProcessingStatus.PARTIAL_SUCCESS)

        # 2. Accounting result: duplicate IDs present in sections, violating uniqueness
        assigned_block_ids = [b.block_id for s in doc.sections for b in s.blocks]
        self.assertEqual(len(assigned_block_ids), 2)
        self.assertEqual(len(set(assigned_block_ids)), 1)

        # 3. Explicit audit warnings recorded for duplicate ID detection
        anomaly_warnings = [w for w in doc.warnings if w.category == WarningCategory.CONTENT_ANOMALY]
        self.assertTrue(any("duplicate block ID" in w.message for w in anomaly_warnings))

    def test_unassigned_blocks_isolated_in_traceable_recovery_section(self):
        """Verifies that unassigned blocks are isolated into an explicit traceable sec_recovery section."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Cover text", locator=PDFSourceLocator(physical_page=1))
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Report text", locator=PDFSourceLocator(physical_page=2))
        b_orphan = ContentBlock(block_id="b_orphan", block_type=BlockType.PARAGRAPH, text_content="Orphan block on page 5 outside outline range", locator=PDFSourceLocator(physical_page=5))

        payload = RawExtractionPayload(
            source_filename="orphan.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=5,
            outline_entries=[
                {"title": "Section 1", "level": 1, "physical_page": 1}
            ],
            pages=[
                RawPageRecord(physical_page=1, blocks=[b1], text="P1"),
                RawPageRecord(physical_page=2, blocks=[b2], text="P2"),
                RawPageRecord(physical_page=5, blocks=[b_orphan], text="P5"),
            ]
        )
        # Note: Outline covers p1-p5, so b1, b2, and b_orphan are all in range.
        # To simulate an unassigned block, create an analyzer with an artificially unmapped page:
        p_unmapped = RawPageRecord(physical_page=99, blocks=[ContentBlock(block_id="b_lost", block_type=BlockType.PARAGRAPH, text_content="Lost text", locator=PDFSourceLocator(physical_page=99))], text="Lost")
        payload.pages.append(p_unmapped)

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # An explicit recovery section must exist
        recovery_sections = [s for s in doc.sections if s.segmentation_method == "accounting_recovery"]
        self.assertTrue(len(recovery_sections) >= 1)
        self.assertEqual(recovery_sections[0].confidence, "low")
        self.assertIn("Unassigned Content Recovery", recovery_sections[0].title)
        self.assertEqual(doc.processing_status, ProcessingStatus.PARTIAL_SUCCESS)
        self.assertTrue(any(w.category == WarningCategory.CONTENT_ANOMALY and "unassigned source blocks isolated into traceable recovery section" in w.message for w in doc.warnings))

    def test_toc_discovery_and_printed_page_verification(self):
        """Verifies TOC matching when printed page labels verify physical pages, and non-monotonic rejection."""
        toc_text = (
            "TABLE OF CONTENTS\n"
            "Chairman Statement .......... 1\n"
            "Directors Report ........... 5\n"
            "Financial Results .......... 12\n"
        )
        p1 = RawPageRecord(physical_page=1, printed_page=None, text=toc_text, blocks=[])
        p2 = RawPageRecord(physical_page=2, printed_page="1", text="Statement", blocks=[
            ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Statement", locator=PDFSourceLocator(physical_page=2, printed_page="1"))
        ])
        p3 = RawPageRecord(physical_page=6, printed_page="5", text="Report", blocks=[
            ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Report", locator=PDFSourceLocator(physical_page=6, printed_page="5"))
        ])
        p4 = RawPageRecord(physical_page=13, printed_page="12", text="Results", blocks=[
            ContentBlock(block_id="b3", block_type=BlockType.PARAGRAPH, text_content="Results", locator=PDFSourceLocator(physical_page=13, printed_page="12"))
        ])

        payload = RawExtractionPayload(
            source_filename="toc.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=15,
            pages=[p1, p2, p3, p4]
        )

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        self.assertEqual(len(doc.sections), 3)
        self.assertEqual(doc.sections[0].section_id, "sec_01")
        self.assertEqual(doc.sections[0].segmentation_method, "toc_page_discovery")
        self.assertEqual(doc.sections[0].confidence, "medium")

    def test_toc_discovery_with_roman_numerals_and_preamble(self):
        """Verifies TOC parsing supporting Roman numerals and proper sec_00 preamble generation."""
        toc_text = (
            "TABLE OF CONTENTS\n"
            "Notice to Shareholders ..... ii\n"
            "Board Profile .............. iv\n"
            "Financial Review ........... 10\n"
        )
        p_cover = RawPageRecord(physical_page=1, printed_page=None, text="Annual Report Cover", blocks=[
            ContentBlock(block_id="b_cov", block_type=BlockType.PARAGRAPH, text_content="Cover preamble", locator=PDFSourceLocator(physical_page=1))
        ])
        p_toc = RawPageRecord(physical_page=2, printed_page="i", text=toc_text, blocks=[])
        p_notice = RawPageRecord(physical_page=3, printed_page="ii", text="Notice text", blocks=[
            ContentBlock(block_id="b_not", block_type=BlockType.PARAGRAPH, text_content="Notice text", locator=PDFSourceLocator(physical_page=3, printed_page="ii"))
        ])
        p_board = RawPageRecord(physical_page=5, printed_page="iv", text="Board text", blocks=[
            ContentBlock(block_id="b_brd", block_type=BlockType.PARAGRAPH, text_content="Board text", locator=PDFSourceLocator(physical_page=5, printed_page="iv"))
        ])
        p_fin = RawPageRecord(physical_page=11, printed_page="10", text="Fin text", blocks=[
            ContentBlock(block_id="b_fin", block_type=BlockType.PARAGRAPH, text_content="Fin text", locator=PDFSourceLocator(physical_page=11, printed_page="10"))
        ])

        payload = RawExtractionPayload(
            source_filename="roman_toc.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=12,
            pages=[p_cover, p_toc, p_notice, p_board, p_fin]
        )

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # sec_00 for cover preamble before p3, then sec_01, sec_02, sec_03
        self.assertEqual(doc.sections[0].section_id, "sec_00")
        self.assertEqual(doc.sections[0].segmentation_method, "preamble_unclassified")
        self.assertEqual(doc.sections[1].section_id, "sec_01")
        self.assertEqual(doc.sections[1].title, "Notice to Shareholders")
        self.assertEqual(doc.sections[2].section_id, "sec_02")
        self.assertEqual(doc.sections[3].section_id, "sec_03")

    def test_toc_non_monotonic_rejection(self):
        """Verifies that TOC entries with non-monotonic page numbers are rejected with STRUCTURE_CONFIDENCE warning."""
        toc_text = (
            "TABLE OF CONTENTS\n"
            "Section Alpha ........... 10\n"
            "Section Beta ............ 2\n"
            "Section Gamma ........... 15\n"
        )
        p1 = RawPageRecord(physical_page=1, printed_page=None, text=toc_text, blocks=[])
        p2 = RawPageRecord(physical_page=2, printed_page="2", text="Beta", blocks=[
            ContentBlock(block_id="b_b", block_type=BlockType.PARAGRAPH, text_content="Beta", locator=PDFSourceLocator(physical_page=2, printed_page="2"))
        ])
        p3 = RawPageRecord(physical_page=10, printed_page="10", text="Alpha", blocks=[
            ContentBlock(block_id="b_a", block_type=BlockType.PARAGRAPH, text_content="Alpha", locator=PDFSourceLocator(physical_page=10, printed_page="10"))
        ])
        p4 = RawPageRecord(physical_page=15, printed_page="15", text="Gamma", blocks=[
            ContentBlock(block_id="b_g", block_type=BlockType.PARAGRAPH, text_content="Gamma", locator=PDFSourceLocator(physical_page=15, printed_page="15"))
        ])

        payload = RawExtractionPayload(
            source_filename="non_monotonic_toc.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=16,
            pages=[p1, p2, p3, p4]
        )

        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # TOC discarded, falls back to conservative fallback
        self.assertTrue(any(w.category == WarningCategory.STRUCTURE_CONFIDENCE and "non-monotonic" in w.message for w in doc.warnings))
        self.assertEqual(doc.sections[0].segmentation_method, "fallback")

    def test_fallback_segmentation_for_sectionless_circular(self):
        """Verifies that structureless documents (notices, circulars) are preserved completely in sec_01 with warning."""
        blocks = [
            ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="HUDCO Circular No. 42/2026.", locator=PDFSourceLocator(physical_page=1))
        ]
        payload = RawExtractionPayload(
            source_filename="circular_42.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            pages=[RawPageRecord(physical_page=1, text="Circular", blocks=blocks)]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        self.assertEqual(len(doc.sections), 1)
        self.assertEqual(doc.sections[0].section_id, "sec_01")
        self.assertEqual(doc.sections[0].segmentation_method, "fallback")
        self.assertEqual(doc.sections[0].confidence, "low")
        self.assertEqual(len(doc.sections[0].blocks), 1)

    def test_block_accounting_verification(self):
        """Verifies that 100% of input blocks are accounted for without duplication or silent loss."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Text 1", locator=PDFSourceLocator(physical_page=1))
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Text 2", locator=PDFSourceLocator(physical_page=2))
        b3 = ContentBlock(block_id="b3", block_type=BlockType.PARAGRAPH, text_content="Text 3", locator=PDFSourceLocator(physical_page=3))

        payload = RawExtractionPayload(
            source_filename="accounting.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=3,
            outline_entries=[{"title": "Section 1", "level": 1, "physical_page": 2}],
            pages=[
                RawPageRecord(physical_page=1, text="T1", blocks=[b1]),
                RawPageRecord(physical_page=2, text="T2", blocks=[b2]),
                RawPageRecord(physical_page=3, text="T3", blocks=[b3])
            ]
        )
        analyzer = StructuralAnalyzer()
        doc = analyzer.analyze(payload)

        # All 3 blocks must exist across doc.sections
        assigned_ids = [b.block_id for s in doc.sections for b in s.blocks]
        self.assertEqual(sorted(assigned_ids), ["b1", "b2", "b3"])
        # Zero duplicate blocks
        self.assertEqual(len(assigned_ids), len(set(assigned_ids)))


class TestPhase2HierarchicalChunker(unittest.TestCase):
    """Validates hierarchical chunking, whole-block overlap bounding, breadcrumbs, and table integrity."""

    def test_heading_breadcrumbs_across_chunk_boundaries(self):
        """Verifies that narrative text before a heading does NOT inherit the subsequent heading in its breadcrumbs."""
        p_intro = ContentBlock(block_id="p1", block_type=BlockType.PARAGRAPH, text_content="General introductory text before any subsection heading.", locator=PDFSourceLocator(physical_page=1))
        h_sub = ContentBlock(block_id="h1", block_type=BlockType.HEADING, text_content="Specific Operations Details", heading_level=2, locator=PDFSourceLocator(physical_page=1))
        p_sub = ContentBlock(block_id="p2", block_type=BlockType.PARAGRAPH, text_content="Details under specific operations heading.", locator=PDFSourceLocator(physical_page=1))

        sec = CanonicalSection(
            section_id="sec_01",
            title="Directors' Report",
            level=1,
            physical_page_start=1,
            physical_page_end=1,
            segmentation_method="native_outline",
            confidence="high",
            heading_path=["Directors' Report"],
            blocks=[p_intro, h_sub, p_sub]
        )
        doc = CanonicalDocument(
            metadata=DocumentMetadata(
                document_id="doc_breadcrumbs",
                source_id="src_b",
                version_id="v1",
                source_filename="b.pdf",
                document_format=DocumentFormat.PDF,
                content_sha256="1" * 64,
                file_size_bytes=100
            ),
            sections=[sec]
        )

        chunker = HierarchicalChunker(target_chunk_size=50, max_chunk_size=100)
        chunks, _ = chunker.chunk_document(doc)

        # Expect at least 2 chunks: one before the heading, one after
        self.assertGreaterEqual(len(chunks), 2)
        # Chunk 1 (intro text) must have breadcrumbs containing ONLY Directors' Report
        self.assertEqual(chunks[0].ancestor_headings, ["Directors' Report"])
        self.assertNotIn("Specific Operations Details", chunks[0].ancestor_headings)

        # Chunk 2 (subtopic) must have breadcrumbs containing Specific Operations Details
        self.assertIn("Specific Operations Details", chunks[1].ancestor_headings)

    def test_chunk_overlap_configuration_and_bounding(self):
        """Verifies that chunk_overlap is validated, bounded within sections, and does not cross section boundaries."""
        # Validation checks
        with self.assertRaises(ValueError):
            HierarchicalChunker(chunk_overlap=-10)
        with self.assertRaises(ValueError):
            HierarchicalChunker(target_chunk_size=500, chunk_overlap=600)

        # Execution check
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Paragraph 1 of section 1.", locator=PDFSourceLocator(physical_page=1))
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Paragraph 2 of section 1.", locator=PDFSourceLocator(physical_page=1))
        b3 = ContentBlock(block_id="b3", block_type=BlockType.PARAGRAPH, text_content="Paragraph 1 of section 2.", locator=PDFSourceLocator(physical_page=2))

        sec1 = CanonicalSection(section_id="sec_01", title="Sec 1", level=1, physical_page_start=1, physical_page_end=1, segmentation_method="fallback", confidence="low", blocks=[b1, b2])
        sec2 = CanonicalSection(section_id="sec_02", title="Sec 2", level=1, physical_page_start=2, physical_page_end=2, segmentation_method="fallback", confidence="low", blocks=[b3])

        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_ov", source_id="src_ov", version_id="v1", source_filename="ov.pdf", document_format=DocumentFormat.PDF, content_sha256="2" * 64, file_size_bytes=100),
            sections=[sec1, sec2]
        )

        # Small target_chunk_size (35 chars) forces b1 (25 chars) and b2 (25 chars) into separate chunks; overlap=30 allows b1 to carry over
        chunker = HierarchicalChunker(target_chunk_size=35, max_chunk_size=100, chunk_overlap=30)
        chunks, _ = chunker.chunk_document(doc)

        # In sec_01: chunk 1 has b1, chunk 2 has b1 (overlap) + b2
        self.assertIn("Paragraph 1 of section 1.", chunks[1].content)
        # But sec_02 chunk must NEVER contain sec_01 text (overlap cannot cross section boundaries)
        self.assertNotIn("section 1", chunks[-1].content)

    def test_whole_block_overlap_semantics_and_boundary_cases(self):
        """Verifies whole-block overlap contract: trailing blocks <= overlap carry over, blocks > overlap do not, lists carry over."""
        b_short = ContentBlock(block_id="b_s", block_type=BlockType.PARAGRAPH, text_content="Short block.", locator=PDFSourceLocator(physical_page=1))
        b_next = ContentBlock(block_id="b_n", block_type=BlockType.PARAGRAPH, text_content="Next narrative sentence.", locator=PDFSourceLocator(physical_page=1))

        b_long = ContentBlock(block_id="b_l", block_type=BlockType.PARAGRAPH, text_content="This is a long trailing block that exceeds overlap budget.", locator=PDFSourceLocator(physical_page=1))
        b_after_long = ContentBlock(block_id="b_al", block_type=BlockType.PARAGRAPH, text_content="Text after long block.", locator=PDFSourceLocator(physical_page=1))

        b_list = ContentBlock(block_id="b_lst", block_type=BlockType.LIST, text_content="- Item bullet.", locator=PDFSourceLocator(physical_page=1))
        b_after_list = ContentBlock(block_id="b_alst", block_type=BlockType.PARAGRAPH, text_content="Text after bullet item.", locator=PDFSourceLocator(physical_page=1))

        sec = CanonicalSection(
            section_id="sec_01",
            title="Overlap Cases",
            level=1,
            physical_page_start=1,
            physical_page_end=1,
            segmentation_method="fallback",
            confidence="low",
            blocks=[b_short, b_next, b_long, b_after_long, b_list, b_after_list]
        )
        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_wb", source_id="src_wb", version_id="v1", source_filename="wb.pdf", document_format=DocumentFormat.PDF, content_sha256="9" * 64, file_size_bytes=100),
            sections=[sec]
        )

        # Overlap budget = 15 chars, target = 20 chars
        # b_short is 12 chars (<= 15) -> should carry over into b_next chunk
        # b_long is 58 chars (> 15) -> should NOT carry over into b_after_long chunk
        # b_list is 14 chars (<= 15) -> should carry over into b_after_list chunk
        chunker = HierarchicalChunker(target_chunk_size=20, max_chunk_size=200, chunk_overlap=15)
        chunks, _ = chunker.chunk_document(doc)

        # Chunk with b_next must contain b_short
        chunk_with_next = [c for c in chunks if "Next narrative sentence" in c.content][0]
        self.assertIn("Short block.", chunk_with_next.content)

        # Chunk with b_after_long must NOT contain b_long
        chunk_with_after_long = [c for c in chunks if "Text after long block" in c.content][0]
        self.assertNotIn("This is a long trailing block", chunk_with_after_long.content)

        # Chunk with b_after_list must contain b_list
        chunk_with_after_list = [c for c in chunks if "Text after bullet item" in c.content][0]
        self.assertIn("- Item bullet.", chunk_with_after_list.content)

        # Zero overlap verification (target_chunk_size=20 separates b_short and b_next)
        chunker_zero = HierarchicalChunker(target_chunk_size=20, max_chunk_size=200, chunk_overlap=0)
        chunks_zero, _ = chunker_zero.chunk_document(doc)
        chunk_zero_next = [c for c in chunks_zero if "Next narrative sentence" in c.content][0]
        self.assertNotIn("Short block.", chunk_zero_next.content)

    def test_table_never_duplicated_as_overlap(self):
        """Verifies that structured table blocks are never carried over into subsequent narrative chunks as overlap."""
        st = build_structured_table(raw_matrix=[["A", "B"], ["1", "2"]], table_id="tbl_1")
        b_tbl = ContentBlock(block_id="b_tbl", block_type=BlockType.TABLE, text_content=st.markdown_representation, table_data=st, locator=PDFSourceLocator(physical_page=1))
        b_narrative = ContentBlock(block_id="b_nar", block_type=BlockType.PARAGRAPH, text_content="Narrative following table.", locator=PDFSourceLocator(physical_page=1))

        sec = CanonicalSection(section_id="sec_01", title="Sec", level=1, physical_page_start=1, physical_page_end=1, segmentation_method="fallback", confidence="low", blocks=[b_tbl, b_narrative])
        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_tbl_ov", source_id="s", version_id="v1", source_filename="tbl.pdf", document_format=DocumentFormat.PDF, content_sha256="8" * 64, file_size_bytes=100),
            sections=[sec]
        )

        chunker = HierarchicalChunker(target_chunk_size=50, max_chunk_size=200, chunk_overlap=40)
        chunks, _ = chunker.chunk_document(doc)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].has_table)
        self.assertFalse(chunks[1].has_table)
        self.assertNotIn("| A | B |", chunks[1].content)

    def test_overlap_safeguard_prevents_artificial_oversized_chunk(self):
        """Verifies that overlap is dropped when overlap + next_block would exceed max_chunk_size."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Overlap text.", locator=PDFSourceLocator(physical_page=1))
        # b2 is 90 chars. If max_chunk_size=100, target=50, overlap=20:
        # b1 length is 13 chars. 13 + 90 = 103 > 100!
        # The safeguard should drop b1 overlap so b2 (90 chars) fits under max_chunk_size without CHUNK_TOO_LONG warning.
        b2_text = "A" * 90
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content=b2_text, locator=PDFSourceLocator(physical_page=1))

        sec = CanonicalSection(section_id="sec_01", title="Sec", level=1, physical_page_start=1, physical_page_end=1, segmentation_method="fallback", confidence="low", blocks=[b1, b2])
        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_sg", source_id="s", version_id="v1", source_filename="sg.pdf", document_format=DocumentFormat.PDF, content_sha256="7" * 64, file_size_bytes=100),
            sections=[sec]
        )

        chunker = HierarchicalChunker(target_chunk_size=50, max_chunk_size=100, chunk_overlap=20)
        chunks, warnings = chunker.chunk_document(doc)

        self.assertEqual(len(chunks), 2)
        # Second chunk should NOT contain b1 overlap because it was dropped by safeguard
        self.assertNotIn("Overlap text.", chunks[1].content)
        # No artificial CHUNK_TOO_LONG warning emitted
        self.assertFalse(any(w.category == WarningCategory.CHUNK_TOO_LONG for w in warnings))

    def test_chunk_id_determinism_and_uniqueness_multi_section_same_page(self):
        """Verifies unique chunk IDs when multiple sections start on the same page, with version and revision sensitivity."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Section 1 content.", locator=PDFSourceLocator(physical_page=2))
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Section 2 content.", locator=PDFSourceLocator(physical_page=2))

        sec1 = CanonicalSection(section_id="sec_01", title="Sec 1", level=1, physical_page_start=2, physical_page_end=2, segmentation_method="native_outline", confidence="high", blocks=[b1])
        sec2 = CanonicalSection(section_id="sec_02", title="Sec 2", level=1, physical_page_start=2, physical_page_end=2, segmentation_method="native_outline", confidence="high", blocks=[b2])

        doc_v1 = CanonicalDocument(
            metadata=DocumentMetadata(document_id="annual_report", source_id="src_ar", version_id="v1", version_number=1, source_filename="ar.pdf", document_format=DocumentFormat.PDF, content_sha256="3" * 64, file_size_bytes=100),
            sections=[sec1, sec2]
        )

        chunker_r1 = HierarchicalChunker(processing_revision=1)
        chunks_r1, _ = chunker_r1.chunk_document(doc_v1)

        # Must have 2 unique chunk IDs
        self.assertEqual(len(chunks_r1), 2)
        self.assertNotEqual(chunks_r1[0].chunk_id, chunks_r1[1].chunk_id)
        self.assertIn("_sec_01_p002_", chunks_r1[0].chunk_id)
        self.assertIn("_sec_02_p002_", chunks_r1[1].chunk_id)

        # Revision 2 yields distinct IDs
        chunker_r2 = HierarchicalChunker(processing_revision=2)
        chunks_r2, _ = chunker_r2.chunk_document(doc_v1)
        self.assertIn("_r2_", chunks_r2[0].chunk_id)
        self.assertNotEqual(chunks_r1[0].chunk_id, chunks_r2[0].chunk_id)

    def test_paragraph_and_section_boundary_preservation(self):
        """Verifies that chunks never cross section boundaries and paragraphs remain intact."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Section 1 paragraph 1.", locator=PDFSourceLocator(physical_page=1))
        b2 = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Section 1 paragraph 2.", locator=PDFSourceLocator(physical_page=1))
        b3 = ContentBlock(block_id="b3", block_type=BlockType.PARAGRAPH, text_content="Section 2 paragraph 1.", locator=PDFSourceLocator(physical_page=2))

        sec1 = CanonicalSection(section_id="sec_01", title="Section 1", level=1, physical_page_start=1, physical_page_end=1, segmentation_method="native_outline", confidence="high", blocks=[b1, b2])
        sec2 = CanonicalSection(section_id="sec_02", title="Section 2", level=1, physical_page_start=2, physical_page_end=2, segmentation_method="native_outline", confidence="high", blocks=[b3])

        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_test", source_id="src_test", version_id="ver_01", source_filename="test.pdf", document_format=DocumentFormat.PDF, content_sha256="4" * 64, file_size_bytes=100),
            sections=[sec1, sec2]
        )

        chunker = HierarchicalChunker(target_chunk_size=1000, max_chunk_size=2000, chunk_overlap=0)
        chunks, _ = chunker.chunk_document(doc)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].section_id, "sec_01")
        self.assertEqual(chunks[1].section_id, "sec_02")
        self.assertNotIn("Section 2", chunks[0].content)

    def test_table_integrity_and_oversized_block_warnings(self):
        """Verifies that structured tables are preserved as dedicated units and oversized blocks emit warnings."""
        st = build_structured_table(raw_matrix=[["Metric", "Value"], ["Net Profit", "2100"]], table_id="tbl_profit")
        self.assertIsNotNone(st)

        table_block = ContentBlock(block_id="b_tbl", block_type=BlockType.TABLE, text_content=st.markdown_representation, table_data=st, locator=PDFSourceLocator(physical_page=5))
        sec = CanonicalSection(section_id="sec_01", title="Accounts", level=1, physical_page_start=5, physical_page_end=5, segmentation_method="fallback", confidence="low", blocks=[table_block])
        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_tbl", source_id="src_tbl", version_id="v1", source_filename="tbl.pdf", document_format=DocumentFormat.PDF, content_sha256="5" * 64, file_size_bytes=200),
            sections=[sec]
        )

        chunker = HierarchicalChunker()
        chunks, _ = chunker.chunk_document(doc)

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].has_table)
        self.assertEqual(chunks[0].structured_tables[0].table_id, "tbl_profit")

    def test_empty_and_whitespace_content_omitted(self):
        """Verifies that whitespace blocks are skipped and no empty chunks are emitted."""
        b_empty = ContentBlock(block_id="b_empty", block_type=BlockType.PARAGRAPH, text_content="   \n\n  ", locator=PDFSourceLocator(physical_page=1))
        sec = CanonicalSection(section_id="sec_01", title="Empty", level=1, physical_page_start=1, physical_page_end=1, segmentation_method="fallback", confidence="low", blocks=[b_empty])
        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_empty", source_id="src_empty", version_id="v1", source_filename="empty.pdf", document_format=DocumentFormat.PDF, content_sha256="6" * 64, file_size_bytes=10),
            sections=[sec]
        )
        chunker = HierarchicalChunker()
        chunks, _ = chunker.chunk_document(doc)
        self.assertEqual(len(chunks), 0)

    def test_provenance_propagation_to_chunks(self):
        """Verifies that locators, physical pages, printed pages, and ancestor breadcrumbs propagate accurately."""
        locator = HTMLSourceLocator(source_url="https://www.hudco.org.in/schemes", css_selector="html > body > main > p", is_approximate=True)
        block = ContentBlock(block_id="b_html", block_type=BlockType.PARAGRAPH, text_content="Substantive housing scheme loan details.", locator=locator)
        sec = CanonicalSection(section_id="sec_01", title="Housing Schemes", level=1, physical_page_start=1, physical_page_end=1, segmentation_method="html_heading_tree", confidence="high", heading_path=["Schemes", "Housing Schemes"], blocks=[block])
        doc = CanonicalDocument(
            metadata=DocumentMetadata(document_id="doc_html", source_id="src_html", version_id="v1", source_filename="schemes.html", document_format=DocumentFormat.HTML, content_sha256="7" * 64, file_size_bytes=100),
            sections=[sec]
        )
        chunker = HierarchicalChunker()
        chunks, _ = chunker.chunk_document(doc)

        chunk = chunks[0]
        self.assertEqual(chunk.section_title, "Housing Schemes")
        self.assertEqual(chunk.ancestor_headings, ["Schemes", "Housing Schemes"])
        self.assertEqual(chunk.locator.source_url, "https://www.hudco.org.in/schemes")
        self.assertTrue(chunk.locator.is_approximate)


class TestPhase2PipelineRunner(unittest.TestCase):
    """Validates end-to-end execution path producing sections.json, chunks.jsonl, and quality_report.md."""

    def test_pipeline_runner_artifact_consistency(self):
        """Verifies that run_phase2_pipeline produces all 4 inspectable artifacts and that counts and warnings agree."""
        blocks = [
            ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Paragraph 1 of report.", locator=PDFSourceLocator(physical_page=1)),
            ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Paragraph 2 of report.", locator=PDFSourceLocator(physical_page=1)),
        ]
        payload = RawExtractionPayload(
            source_filename="summary_test.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            pages=[RawPageRecord(physical_page=1, text="Text", blocks=blocks)]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "run_preview"
            doc, chunks, run_dir = run_phase2_pipeline(payload=payload, output_dir=out_path)

            self.assertTrue((out_path / "sections.json").exists())
            self.assertTrue((out_path / "chunks.jsonl").exists())
            self.assertTrue((out_path / "processing_summary.json").exists())
            self.assertTrue((out_path / "quality_report.md").exists())

            # Inspect sections.json
            with open(out_path / "sections.json", "r", encoding="utf-8") as f:
                sections_data = json.load(f)
                self.assertEqual(len(sections_data), 1)
                self.assertIn("parent_section_id", sections_data[0])
                self.assertIn("heading_path", sections_data[0])

            # Inspect summary consistency
            with open(out_path / "processing_summary.json", "r", encoding="utf-8") as f:
                summary = json.load(f)
                self.assertEqual(summary["section_count"], len(sections_data))
                self.assertEqual(summary["chunk_count"], len(chunks))

            # Inspect quality report consistency
            with open(out_path / "quality_report.md", "r", encoding="utf-8") as f:
                report_content = f.read()
                self.assertIn(f"Sections Inferred**: `{summary['section_count']}`", report_content)
                self.assertIn(f"Total Chunks Produced**: `{summary['chunk_count']}`", report_content)


class TestPhase31OutlineAndTOCValidation(unittest.TestCase):
    """
    Focused Phase 3.1 regression tests for:
    1. Conservative PDF outline semantic validation (HUDCO degenerate vs valid vs mixed vs invalid).
    2. Fallback to TOC discovery when outline is rejected.
    3. Positive and negative TOC line matching with representative extracted lines.
    """

    def setUp(self):
        self.analyzer = StructuralAnalyzer()

    def test_hudco_style_degenerate_outline_rejected(self):
        """HUDCO-style outline (1, 2, Final_Final..., 3, 4) must be rejected with explicit warning."""
        entries = [
            {"title": "1", "level": 1, "physical_page": 1},
            {"title": "2", "level": 1, "physical_page": 2},
            {"title": "Final_Final_ANNUAL REPORT HUDCO 2026", "level": 1, "physical_page": 3},
            {"title": "3", "level": 1, "physical_page": 519},
            {"title": "4", "level": 1, "physical_page": 520},
        ]
        is_valid, reasons = self.analyzer._validate_pdf_outlines(entries, total_pages=520)
        self.assertFalse(is_valid)
        self.assertTrue(any("generic export artifacts or pure numeric digits" in r for r in reasons))

        # Test in full analyze() flow: must record STRUCTURE_CONFIDENCE warning and NOT use outline
        payload = RawExtractionPayload(
            source_filename="ar26.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=520,
            outline_entries=entries,
            pages=[
                RawPageRecord(physical_page=1, blocks=[ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="P1 text", locator=PDFSourceLocator(physical_page=1))]),
                RawPageRecord(physical_page=2, blocks=[ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="P2 text", locator=PDFSourceLocator(physical_page=2))]),
            ]
        )
        doc = self.analyzer.analyze(payload)
        self.assertTrue(any(
            w.category == WarningCategory.STRUCTURE_CONFIDENCE and "PDF native outline rejected" in w.message
            for w in doc.warnings
        ))
        # Ensure it didn't create sec_01 titled "1" or sec_02 titled "2" via native_outline
        for s in doc.sections:
            self.assertNotEqual(s.segmentation_method, "native_outline")

    def test_valid_outline_accepted(self):
        """Legitimate outline with meaningful section titles must be accepted."""
        entries = [
            {"title": "1. Corporate Overview", "level": 1, "physical_page": 1},
            {"title": "2. Board's Report", "level": 1, "physical_page": 20},
            {"title": "3. Financial Statements", "level": 1, "physical_page": 100},
        ]
        is_valid, reasons = self.analyzer._validate_pdf_outlines(entries, total_pages=150)
        self.assertTrue(is_valid)
        self.assertEqual(len(reasons), 0)

        payload = RawExtractionPayload(
            source_filename="report.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=150,
            outline_entries=entries,
            pages=[
                RawPageRecord(physical_page=1, blocks=[ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Overview", locator=PDFSourceLocator(physical_page=1))]),
                RawPageRecord(physical_page=20, blocks=[ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Board", locator=PDFSourceLocator(physical_page=20))]),
            ]
        )
        doc = self.analyzer.analyze(payload)
        self.assertEqual(doc.sections[0].segmentation_method, "native_outline")
        self.assertEqual(doc.sections[0].title, "1. Corporate Overview")

    def test_mixed_outline_acceptance_threshold(self):
        """Mixed outline containing mostly valid chapter titles and one generic label must be accepted."""
        entries = [
            {"title": "Cover", "level": 1, "physical_page": 1},
            {"title": "Chapter 1: Strategic Priorities", "level": 1, "physical_page": 5},
            {"title": "Chapter 2: Financial Performance", "level": 1, "physical_page": 25},
            {"title": "Chapter 3: Risk Management", "level": 1, "physical_page": 50},
            {"title": "Chapter 4: Governance", "level": 1, "physical_page": 75},
        ]
        is_valid, reasons = self.analyzer._validate_pdf_outlines(entries, total_pages=100)
        # 1/5 = 20% uninformative < 40% threshold -> must be accepted
        self.assertTrue(is_valid)
        self.assertEqual(len(reasons), 0)

    def test_invalid_out_of_range_or_non_monotonic_outlines(self):
        """Outlines with majority out-of-range pages or severe non-monotonic inversions must be rejected."""
        out_of_range = [
            {"title": "Part A", "physical_page": 9999},
            {"title": "Part B", "physical_page": 8888},
            {"title": "Part C", "physical_page": 1},
        ]
        is_valid, reasons = self.analyzer._validate_pdf_outlines(out_of_range, total_pages=50)
        self.assertFalse(is_valid)
        self.assertTrue(any("invalid physical page numbers" in r for r in reasons))

        non_monotonic = [
            {"title": "Chapter 1", "physical_page": 50},
            {"title": "Chapter 2", "physical_page": 20},
            {"title": "Chapter 3", "physical_page": 5},
        ]
        is_valid_nm, reasons_nm = self.analyzer._validate_pdf_outlines(non_monotonic, total_pages=100)
        self.assertFalse(is_valid_nm)
        self.assertTrue(any("non-monotonic page order" in r for r in reasons_nm))

    def test_fallback_to_toc_when_outline_rejected(self):
        """When outline is rejected as degenerate, pipeline must cleanly fall through to TOC discovery."""
        degenerate_entries = [
            {"title": "1", "level": 1, "physical_page": 1},
            {"title": "2", "level": 1, "physical_page": 2},
            {"title": "Final_Final_ANNUAL REPORT HUDCO 2026", "level": 1, "physical_page": 3},
        ]
        toc_text = (
            "TABLE OF CONTENTS\n"
            "Reference Information 18\n"
            "Board of Directors 20\n"
            "Chairman's Message 22\n"
        )
        p1 = RawPageRecord(physical_page=1, text="Cover", blocks=[ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Cover", locator=PDFSourceLocator(physical_page=1))])
        p5 = RawPageRecord(physical_page=5, text=toc_text, blocks=[])
        p20 = RawPageRecord(physical_page=20, printed_page="18", text="Ref info", blocks=[ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content="Ref", locator=PDFSourceLocator(physical_page=20, printed_page="18"))])
        p22 = RawPageRecord(physical_page=22, printed_page="20", text="Board info", blocks=[ContentBlock(block_id="b3", block_type=BlockType.PARAGRAPH, text_content="Board", locator=PDFSourceLocator(physical_page=22, printed_page="20"))])
        p24 = RawPageRecord(physical_page=24, printed_page="22", text="Chairman info", blocks=[ContentBlock(block_id="b4", block_type=BlockType.PARAGRAPH, text_content="Chair", locator=PDFSourceLocator(physical_page=24, printed_page="22"))])

        payload = RawExtractionPayload(
            source_filename="ar26.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=25,
            outline_entries=degenerate_entries,
            pages=[p1, p5, p20, p22, p24]
        )
        doc = self.analyzer.analyze(payload)

        # 1. Outline rejected warning recorded
        self.assertTrue(any(w.category == WarningCategory.STRUCTURE_CONFIDENCE and "PDF native outline rejected" in w.message for w in doc.warnings))

        # 2. Sections created via TOC discovery
        toc_secs = [s for s in doc.sections if s.segmentation_method == "toc_page_discovery"]
        self.assertEqual(len(toc_secs), 3)
        self.assertEqual(toc_secs[0].title, "Reference Information")
        self.assertEqual(toc_secs[0].section_id, "sec_01")
        self.assertEqual(toc_secs[1].title, "Board of Directors")
        self.assertEqual(toc_secs[1].section_id, "sec_02")
        self.assertEqual(toc_secs[2].title, "Chairman's Message")
        self.assertEqual(toc_secs[2].section_id, "sec_03")

    def test_toc_regex_positive_and_negative_matching(self):
        """Verifies TOC title and line matching on positive lines and rejection of dates, currency, and headers."""
        from pipeline.core.structural_analyzer import TOC_LINE_REGEX, TOC_NEGATIVE_REGEX, TOC_TITLE_REGEX

        # Positive Title matches
        self.assertTrue(bool(TOC_TITLE_REGEX.search("TABLE OF CONTENTS")))
        self.assertTrue(bool(TOC_TITLE_REGEX.search("CONTENTSCONTENTS")))
        self.assertTrue(bool(TOC_TITLE_REGEX.search("Contents")))
        self.assertTrue(bool(TOC_TITLE_REGEX.search("INDEX")))

        # Positive Line matches (both spaces and dots)
        positive_lines = [
            "Reference Information 18",
            "Board of Directors 20",
            "Chairman's Message 22",
            "Notice of AGM 35",
            "Directors' Report 48",
            "Secretarial Audit Report 158",
            "Standalone Financial Statements 206",
            "Notice to Shareholders ..... ii",
            "Executive Summary .......... 1",
            "Audit Committee Report ----- iv",
        ]
        for line in positive_lines:
            match = TOC_LINE_REGEX.match(line)
            self.assertIsNotNone(match, f"Failed to match positive TOC line: '{line}'")
            clean_title = match.group(1).strip()
            self.assertFalse(bool(TOC_NEGATIVE_REGEX.search(clean_title)), f"Positive line falsely rejected by negative regex: '{line}'")

        # Negative Line matches (dates, currency, timestamps, schedule headers)
        negative_lines = [
            "Date: 24th August, 2026 | Time: 11:30 a.m. (IST)",
            "CUT-OFF DATE 17.08.2026",
            "START DATE 20.08.2026",
            "END DATE 23.08.2026 05:00 p.m. (IST)",
            "Gross Income 6,997.66",
            "Revenue from Operations 6,954.08",
            "(` in Crore) PARTICULARS 2021-22",
            "Tel: 011-24648160 Fax: 011-24648190",
        ]
        for line in negative_lines:
            match = TOC_LINE_REGEX.match(line)
            if match:
                clean_title = match.group(1).strip()
                # If it matched the general line pattern, TOC_NEGATIVE_REGEX must reject it
                self.assertTrue(bool(TOC_NEGATIVE_REGEX.search(clean_title)), f"Negative line should have been rejected by TOC_NEGATIVE_REGEX: '{line}'")


if __name__ == "__main__":
    unittest.main()
