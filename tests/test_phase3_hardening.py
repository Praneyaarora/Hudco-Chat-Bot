"""
Phase 3.2 Hardening, Validation, and Regression Test Suite.
File: tests/test_phase3_hardening.py

Covers:
1. Evaluation runner forensic assertions and negative tests (rejecting corrupt artifacts, boundary violations, invalid provenance).
2. ADR-08 Warning Severity and Processing Status degradation (PARTIAL_SUCCESS vs SUCCESS_WITH_WARNINGS).
3. Robust TOC and Outline semantic validation (numeric, generic, draft-export rejection, single-space TOC matching, Roman numerals, false-positive protection).
4. Chunking boundary isolation, oversized paragraph buffer flushing, whole-block overlap, and atomic table preservation.
5. Deterministic, version-aware chunk IDs (ADR-10/ADR-15 reconciliation).
"""

import io
import json
import hashlib
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
    ProcessingStatus,
)
from pipeline.adapters.base import RawExtractionPayload, RawPageRecord
from pipeline.adapters.pdf_adapter import PDFDocumentAdapter
from pipeline.core.structural_analyzer import StructuralAnalyzer, TOC_LINE_REGEX, TOC_NEGATIVE_REGEX
from pipeline.core.chunker import HierarchicalChunker
from pipeline.core.pipeline_runner import run_phase2_pipeline
from pipeline.utils.table_formatter import build_structured_table
from scripts.run_phase3_sample import validate_sample_execution


class TestPhase3HardeningRunnerValidation(unittest.TestCase):
    """Validates that scripts/run_phase3_sample.py forensic validator catches corruptions and boundary violations."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

        p1 = RawPageRecord(physical_page=1, printed_page="1", text="Section one text.", blocks=[
            ContentBlock(block_id="p001_blk00", block_type=BlockType.PARAGRAPH, text_content="Section one text.", locator=PDFSourceLocator(physical_page=1, printed_page="1"))
        ])
        p2 = RawPageRecord(physical_page=2, printed_page="2", text="Section two text.", blocks=[
            ContentBlock(block_id="p002_blk00", block_type=BlockType.PARAGRAPH, text_content="Section two text.", locator=PDFSourceLocator(physical_page=2, printed_page="2"))
        ])
        self.payload = RawExtractionPayload(
            source_filename="test.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=2,
            pages=[p1, p2]
        )

        self.doc, self.chunks, _ = run_phase2_pipeline(
            payload=self.payload,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            chunk_overlap=150
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_pipeline_passes_validation(self):
        """Verifies that flawless run produces zero hard failures."""
        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertEqual(failures, [])

    def test_negative_rejects_missing_artifact(self):
        """Deleting sections.json must cause a hard failure."""
        (self.output_dir / "sections.json").unlink()
        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("Missing output artifact: sections.json" in f for f in failures))

    def test_negative_rejects_corrupted_section_count(self):
        """Mismatched section count in sections.json must cause a hard failure."""
        sec_path = self.output_dir / "sections.json"
        with open(sec_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("sections.json count" in f for f in failures))

    def test_negative_rejects_corrupted_chunk_hash(self):
        """Tampered content in chunks.jsonl without updating SHA-256 must cause a hard failure."""
        chunk_path = self.output_dir / "chunks.jsonl"
        with open(chunk_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        lines[0]["chunk_id"] = "tampered_chunk_id"
        with open(chunk_path, "w", encoding="utf-8") as f:
            for rec in lines:
                f.write(json.dumps(rec) + "\n")
        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("chunk_id' mismatch" in f or "chunk_id mismatch" in f for f in failures))

    def test_negative_rejects_section_boundary_violation(self):
        """A chunk whose physical page is outside its section's bounds must cause a hard failure."""
        corrupt_chunks = list(self.chunks)
        # Point chunk to physical page 99 outside section page bounds [1, 2]
        bad_chunk = corrupt_chunks[0].model_copy(update={"physical_page": 99})
        corrupt_chunks[0] = bad_chunk

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=corrupt_chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("outside section" in f for f in failures))

    def test_negative_rejects_unwarned_oversized_narrative(self):
        """An oversized narrative chunk without a CHUNK_TOO_LONG warning must fail."""
        long_text = "A" * 2500
        bad_chunk = CanonicalChunk(
            chunk_id="test_oversized_c00",
            document_id="test",
            version_id="v1",
            source_id="src",
            source_filename="test.pdf",
            section_id=self.doc.sections[0].section_id,
            section_title="Test Sec",
            physical_page=1,
            chunk_index_in_page=0,
            has_table=False,
            char_count=len(long_text),
            token_estimate=625,
            content=long_text,
            content_sha256=hashlib.sha256(long_text.encode("utf-8")).hexdigest(),
            source_block_ids=["p001_blk00"]
        )
        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=[bad_chunk],
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("missing required CHUNK_TOO_LONG audit warning" in f for f in failures))

    def test_negative_rejects_missing_source_blocks(self):
        """Omitting a source block from sections must be caught by block accounting."""
        corrupt_doc = self.doc.model_copy(deep=True)
        corrupt_doc.sections[0].blocks = []  # empty blocks
        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=corrupt_doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("Block count mismatch" in f or "Unassigned source blocks" in f for f in failures))

    def test_negative_rejects_empty_or_missing_source_block_ids(self):
        """Chunks with missing or empty source_block_ids must fail provenance check."""
        corrupt_chunks = list(self.chunks)
        bad_chunk = corrupt_chunks[0].model_copy(update={"source_block_ids": []})
        corrupt_chunks[0] = bad_chunk

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=corrupt_chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("missing required source_block_ids provenance" in f for f in failures))

    def test_negative_rejects_duplicate_source_block_ids_within_chunk(self):
        """Chunks with duplicate source_block_ids must fail provenance check."""
        corrupt_chunks = list(self.chunks)
        bad_chunk = corrupt_chunks[0].model_copy(update={"source_block_ids": ["p001_blk00", "p001_blk00"]})
        corrupt_chunks[0] = bad_chunk

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=corrupt_chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("contains duplicate source_block_ids" in f for f in failures))

    def test_negative_rejects_fabricated_source_block_id(self):
        """Chunks referencing non-existent or fabricated block IDs must fail."""
        corrupt_chunks = list(self.chunks)
        bad_chunk = corrupt_chunks[0].model_copy(update={"source_block_ids": ["fabricated_block_999"]})
        corrupt_chunks[0] = bad_chunk

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=corrupt_chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("references non-existent or fabricated source block" in f for f in failures))

    def test_negative_rejects_block_outside_section_page_range(self):
        """Sections containing blocks outside their declared physical page bounds must fail."""
        corrupt_doc = self.doc.model_copy(deep=True)
        corrupt_doc.sections[0].physical_page_end = 1
        blk = corrupt_doc.sections[0].blocks[0].model_copy(
            update={"locator": PDFSourceLocator(physical_page=2, printed_page="2")}
        )
        corrupt_doc.sections[0].blocks = [blk]

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=corrupt_doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("outside section bounds" in f for f in failures))

    def test_negative_rejects_duplicate_physical_pages_in_payload(self):
        """Payloads containing duplicate physical page records must fail."""
        corrupt_payload = self.payload.model_copy(deep=True)
        corrupt_payload.pages.append(corrupt_payload.pages[0])  # duplicate page 1

        failures = validate_sample_execution(
            payload=corrupt_payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("Duplicate physical-page records detected" in f for f in failures))

    def test_negative_rejects_section_ordering_violation(self):
        """Sections not in ascending physical_page_start order must fail."""
        corrupt_doc = self.doc.model_copy(deep=True)
        sec2 = corrupt_doc.sections[0].model_copy(update={"section_id": "sec_02", "physical_page_start": 1})
        sec1 = corrupt_doc.sections[0].model_copy(update={"section_id": "sec_01", "physical_page_start": 5})
        corrupt_doc.sections = [sec1, sec2]

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=corrupt_doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("Sections out of physical page order" in f for f in failures))

    def test_negative_rejects_sections_json_field_discrepancy(self):
        """A discrepancy in contract fields of sections.json must cause validation failure."""
        sec_path = self.output_dir / "sections.json"
        with open(sec_path, "r", encoding="utf-8") as f:
            sec_data = json.load(f)
        sec_data[0]["confidence"] = "fabricated_confidence"
        with open(sec_path, "w", encoding="utf-8") as f:
            json.dump(sec_data, f)

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("field 'confidence' mismatch" in f for f in failures))

    def test_negative_rejects_summary_json_metric_mismatch(self):
        """A discrepancy in summary JSON metrics must cause validation failure."""
        sum_path = self.output_dir / "processing_summary.json"
        with open(sum_path, "r", encoding="utf-8") as f:
            sum_data = json.load(f)
        sum_data["status"] = "FABRICATED_STATUS"
        with open(sum_path, "w", encoding="utf-8") as f:
            json.dump(sum_data, f)

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=self.doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("summary status" in f for f in failures))

    def test_negative_rejects_quality_report_warning_omission(self):
        """A warning present in in-memory doc but omitted from quality_report.md must fail."""
        corrupt_doc = self.doc.model_copy(deep=True)
        corrupt_doc.warnings.append(QualityWarning(
            category=WarningCategory.CONTENT_ANOMALY,
            message="Unreported critical anomaly in document.",
            physical_page=1
        ))

        failures = validate_sample_execution(
            payload=self.payload,
            canonical_doc=corrupt_doc,
            chunks=self.chunks,
            output_dir=self.output_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            page_start=1,
            page_end=2
        )
        self.assertTrue(any("quality_report.md missing expected warning entry" in f for f in failures))


class TestPhase3ADR08StatusDegradation(unittest.TestCase):
    """Validates ADR-08 severity rules and processing status degradation."""

    def setUp(self):
        self.analyzer = StructuralAnalyzer()

    def test_physical_page_gaps_degrades_to_partial_success(self):
        """A missing physical page in the extracted stream must trigger CONTENT_ANOMALY and PARTIAL_SUCCESS."""
        p1 = RawPageRecord(physical_page=1, text="Page 1", blocks=[
            ContentBlock(block_id="p001_blk00", block_type=BlockType.PARAGRAPH, text_content="Page 1", locator=PDFSourceLocator(physical_page=1))
        ])
        # Page 2 missing, jumps to Page 3
        p3 = RawPageRecord(physical_page=3, text="Page 3", blocks=[
            ContentBlock(block_id="p003_blk00", block_type=BlockType.PARAGRAPH, text_content="Page 3", locator=PDFSourceLocator(physical_page=3))
        ])
        payload = RawExtractionPayload(
            source_filename="gap.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=3,
            pages=[p1, p3]
        )
        doc = self.analyzer.analyze(payload)
        self.assertEqual(doc.processing_status, ProcessingStatus.PARTIAL_SUCCESS)
        self.assertTrue(any(w.category == WarningCategory.CONTENT_ANOMALY and "Missing physical page gap" in w.message for w in doc.warnings))

    def test_duplicate_payload_block_ids_degrades_to_partial_success(self):
        """Ambiguous duplicate block IDs in source payload must set PARTIAL_SUCCESS."""
        b1 = ContentBlock(block_id="dup_id", block_type=BlockType.PARAGRAPH, text_content="Text 1", locator=PDFSourceLocator(physical_page=1))
        b2 = ContentBlock(block_id="dup_id", block_type=BlockType.PARAGRAPH, text_content="Text 2", locator=PDFSourceLocator(physical_page=1))
        p1 = RawPageRecord(physical_page=1, text="Text 1 Text 2", blocks=[b1, b2])
        payload = RawExtractionPayload(
            source_filename="dup.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            pages=[p1]
        )
        doc = self.analyzer.analyze(payload)
        self.assertEqual(doc.processing_status, ProcessingStatus.PARTIAL_SUCCESS)

    def test_low_confidence_fallback_degrades_to_partial_success(self):
        """When analyzer must use low-confidence conservative fallback windowing, status must be PARTIAL_SUCCESS."""
        p1 = RawPageRecord(physical_page=1, text="No headings or TOC", blocks=[
            ContentBlock(block_id="p001_blk00", block_type=BlockType.PARAGRAPH, text_content="Prose", locator=PDFSourceLocator(physical_page=1))
        ])
        payload = RawExtractionPayload(
            source_filename="plain.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            pages=[p1]
        )
        doc = self.analyzer.analyze(payload)
        self.assertEqual(doc.sections[0].confidence, "low")
        self.assertEqual(doc.processing_status, ProcessingStatus.PARTIAL_SUCCESS)

    def test_minor_anomalies_produce_success_with_warnings(self):
        """Blank pages and scanned image pages must produce SUCCESS_WITH_WARNINGS, not PARTIAL_SUCCESS."""
        p1 = RawPageRecord(physical_page=1, text="", blocks=[])
        payload = RawExtractionPayload(
            source_filename="blank.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=1,
            pages=[p1],
            warnings=[QualityWarning(category=WarningCategory.BLANK_PAGE, message="Blank", physical_page=1)]
        )
        # Add 1 block so document is not empty
        p2 = RawPageRecord(physical_page=2, text="Real content", blocks=[
            ContentBlock(block_id="p002_blk00", block_type=BlockType.PARAGRAPH, text_content="Real content", locator=PDFSourceLocator(physical_page=2))
        ])
        payload.pages.append(p2)
        payload.total_physical_pages = 2

        # Give valid outline so confidence is high
        payload.outline_entries = [{"title": "Main Chapter", "level": 1, "physical_page": 2}]

        doc = self.analyzer.analyze(payload)
        self.assertEqual(doc.processing_status, ProcessingStatus.SUCCESS_WITH_WARNINGS)


class TestPhase3TOCOutlineValidation(unittest.TestCase):
    """Regression tests for ADR-17 outline semantic validation and robust TOC pattern matching."""

    def setUp(self):
        self.analyzer = StructuralAnalyzer()

    def test_draft_export_and_numeric_outlines_rejected(self):
        """Numeric ('1', '2') and draft export ('Final_Final...') bookmarks must be rejected."""
        outline = [
            {"title": "1", "level": 1, "physical_page": 1},
            {"title": "2", "level": 1, "physical_page": 2},
            {"title": "Final_Final_ANNUAL REPORT HUDCO 2026", "level": 1, "physical_page": 3}
        ]
        valid, warn = self.analyzer._validate_pdf_outlines(outline, total_pages=10)
        self.assertFalse(valid)
        self.assertTrue(any("generic export artifacts or pure numeric digits" in r for r in warn))

    def test_valid_descriptive_outlines_accepted(self):
        """Rich descriptive chapter titles with valid page ranges must be accepted."""
        outline = [
            {"title": "Corporate Overview", "level": 1, "physical_page": 1},
            {"title": "Management Discussion & Analysis", "level": 1, "physical_page": 10},
            {"title": "Financial Statements", "level": 1, "physical_page": 25}
        ]
        valid, warn = self.analyzer._validate_pdf_outlines(outline, total_pages=50)
        self.assertTrue(valid)
        self.assertEqual(warn, [])

    def test_out_of_range_or_non_monotonic_outlines_rejected(self):
        """Outlines with page references beyond document length or non-monotonic ordering must be rejected."""
        outline = [
            {"title": "Chapter One", "level": 1, "physical_page": 20},
            {"title": "Chapter Two", "level": 1, "physical_page": 5}  # non-monotonic
        ]
        valid, warn = self.analyzer._validate_pdf_outlines(outline, total_pages=30)
        self.assertFalse(valid)
        self.assertTrue(any("non-monotonic" in r for r in warn))

    def test_toc_line_regex_dot_leaders_and_spaces(self):
        """TOC matching supports dot leaders, tabs, hyphens, and single spaces."""
        valid_lines = [
            "Corporate Governance Report .......... 52",
            "Board of Directors | 20",
            "Notice of AGM    35",
            "Reference Information 18",
            "Auditor's Report ............. iv",
        ]
        for line in valid_lines:
            m = TOC_LINE_REGEX.search(line)
            self.assertIsNotNone(m, f"Failed to match valid TOC line: '{line}'")

    def test_toc_negative_exclusion_prevents_false_positives(self):
        """Prose with currency figures, dates, times, or schedules must NOT trigger TOC matches."""
        false_positive_prose = [
            "Total loan sanctions stood at Rs. 25000 Crore",
            "Date : 25th September 2026",
            "Meeting Time: 11:30 am",
            "CUT-OFF DATE : Friday, September 18",
            "Visit our Website: www.hudco.org.in"
        ]
        for text in false_positive_prose:
            self.assertIsNotNone(
                TOC_NEGATIVE_REGEX.search(text),
                f"Negative regex failed to exclude non-TOC line: '{text}'"
            )

    def test_toc_front_matter_preamble_preservation(self):
        """When TOC chapters start after the current extraction window, the window is preserved as Document Front Matter."""
        p1 = RawPageRecord(physical_page=1, printed_page=None, text="Cover", blocks=[
            ContentBlock(block_id="p001_blk00", block_type=BlockType.PARAGRAPH, text_content="Cover", locator=PDFSourceLocator(physical_page=1))
        ])
        p5 = RawPageRecord(
            physical_page=5,
            printed_page=None,
            text="TABLE OF CONTENTS\nNotice of AGM ..... 25\nDirectors Report ..... 35",
            blocks=[
                ContentBlock(block_id="p005_blk00", block_type=BlockType.PARAGRAPH, text_content="TABLE OF CONTENTS\nNotice of AGM ..... 25\nDirectors Report ..... 35", locator=PDFSourceLocator(physical_page=5))
            ]
        )
        payload = RawExtractionPayload(
            source_filename="ar26.pdf",
            document_format=DocumentFormat.PDF,
            total_physical_pages=10,
            pages=[p1, p5]
        )
        doc = self.analyzer.analyze(payload)
        self.assertEqual(len(doc.sections), 1)
        self.assertEqual(doc.sections[0].title, "Document Front Matter")
        self.assertEqual(doc.sections[0].segmentation_method, "toc_preamble")
        self.assertEqual(doc.sections[0].section_id, "sec_01")


class TestPhase3ChunkingAndTableIntegrity(unittest.TestCase):
    """Strengthened chunking, buffer isolation, table preservation, and overlap tests."""

    def test_oversized_paragraph_with_non_empty_buffer(self):
        """A small paragraph in buffer followed by an oversized paragraph flushes buffer first, then emits oversized chunk."""
        chunker = HierarchicalChunker(target_chunk_size=1000, max_chunk_size=2000, chunk_overlap=150)

        small_b = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Small paragraph text.", locator=PDFSourceLocator(physical_page=1))
        huge_text = "H" * 2500
        huge_b = ContentBlock(block_id="b2", block_type=BlockType.PARAGRAPH, text_content=huge_text, locator=PDFSourceLocator(physical_page=1))

        sec = CanonicalSection(
            section_id="sec_01",
            title="Sec",
            physical_page_start=1,
            physical_page_end=1,
            segmentation_method="test",
            confidence="high",
            blocks=[small_b, huge_b]
        )
        meta = DocumentMetadata(
            document_id="doc1",
            source_id="src1",
            version_id="v1",
            source_filename="doc.pdf",
            document_format=DocumentFormat.PDF,
            content_sha256="a" * 64,
            file_size_bytes=100
        )
        doc = CanonicalDocument(metadata=meta, sections=[sec])

        chunks, warnings = chunker.chunk_document(doc)
        # Expect 2 chunks: chunk 1 with small_b, chunk 2 with huge_b
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].content, "Small paragraph text.")
        self.assertEqual(chunks[1].content, huge_text)
        self.assertTrue(chunks[1].char_count > 2000)
        self.assertTrue(any(w.category == WarningCategory.CHUNK_TOO_LONG for w in warnings))

    def test_table_atomic_preservation_and_gfm_rendering(self):
        """Tables are indivisible chunks with headers, units, and markdown representations."""
        raw_matrix = [
            ["Metric", "FY 2025", "FY 2026"],
            ["Loan Sanctions", "10000", "15000"],
            ["Net Profit", "500", "750"]
        ]
        table = build_structured_table(
            raw_matrix=raw_matrix,
            table_id="p021_tbl01",
            unit_of_measure="₹ in Crore"
        )
        tbl_block = ContentBlock(
            block_id="p021_blk01",
            block_type=BlockType.TABLE,
            text_content=table.markdown_representation,
            locator=PDFSourceLocator(physical_page=21, printed_page="19"),
            table_data=table
        )
        sec = CanonicalSection(
            section_id="sec_01",
            title="Financials",
            physical_page_start=21,
            physical_page_end=21,
            segmentation_method="test",
            confidence="high",
            blocks=[tbl_block]
        )
        meta = DocumentMetadata(
            document_id="ar26",
            source_id="hudco",
            version_id="v1",
            source_filename="ar26.pdf",
            document_format=DocumentFormat.PDF,
            content_sha256="b" * 64,
            file_size_bytes=500
        )
        doc = CanonicalDocument(metadata=meta, sections=[sec])

        chunker = HierarchicalChunker(target_chunk_size=1200, max_chunk_size=2000)
        chunks, _ = chunker.chunk_document(doc)

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].has_table)
        self.assertEqual(len(chunks[0].structured_tables), 1)
        self.assertEqual(chunks[0].structured_tables[0].unit_of_measure, "₹ in Crore")
        self.assertIn("| Metric | FY 2025 | FY 2026 |", chunks[0].content)

    def test_deterministic_chunk_ids_across_repeated_runs(self):
        """Repeated chunking of the exact same document produces 100% byte-identical chunk IDs (ADR-10)."""
        b1 = ContentBlock(block_id="b1", block_type=BlockType.PARAGRAPH, text_content="Deterministic content.", locator=PDFSourceLocator(physical_page=1))
        sec = CanonicalSection(
            section_id="sec_01",
            title="Sec",
            physical_page_start=1,
            physical_page_end=1,
            segmentation_method="test",
            confidence="high",
            blocks=[b1]
        )
        meta = DocumentMetadata(
            document_id="ar26",
            source_id="hudco",
            version_id="v1",
            version_number=1,
            source_filename="ar26.pdf",
            document_format=DocumentFormat.PDF,
            content_sha256="c" * 64,
            file_size_bytes=100
        )
        doc = CanonicalDocument(metadata=meta, sections=[sec])

        chunker = HierarchicalChunker(target_chunk_size=1200, max_chunk_size=2000, processing_revision=1)
        chunks_run1, _ = chunker.chunk_document(doc)
        chunks_run2, _ = chunker.chunk_document(doc)

        self.assertEqual(len(chunks_run1), len(chunks_run2))
        self.assertEqual(chunks_run1[0].chunk_id, chunks_run2[0].chunk_id)
        # Check canonical format
        self.assertTrue(chunks_run1[0].chunk_id.startswith("ar26_v1_"))
        self.assertIn("_sec_01_p001_c00", chunks_run1[0].chunk_id)

    def test_heuristic_table_preserves_narrative_and_footnotes(self):
        """Heuristic table fallback must preserve surrounding narrative, headings, and footnotes above and below."""
        adapter = PDFDocumentAdapter()
        raw_page_text = (
            "FINANCIAL HIGHLIGHTS\n"
            "(₹ in Crore)\n\n"
            "PARTICULARS    FY 2024-25    FY 2025-26\n"
            "Total Income   10,348.50     13,327.20\n"
            "Net Profit     2,709.10      2,423.80\n"
            "Net Worth      17,543.00     19,812.50\n\n"
            "*Dividend declared at Rs. 1.50 per share.\n"
            "**Includes exceptional provisions."
        )
        tables, blocks = adapter._extract_page_tables_heuristic(
            page_text=raw_page_text,
            physical_page=21,
            printed_page="19"
        )
        self.assertEqual(len(tables), 1)
        self.assertGreaterEqual(len(blocks), 3)

        # First block must be narrative/heading above table
        self.assertEqual(blocks[0].block_type, BlockType.HEADING)
        self.assertIn("FINANCIAL HIGHLIGHTS", blocks[0].text_content)

        # Middle block must be table
        table_block = [b for b in blocks if b.block_type == BlockType.TABLE][0]
        self.assertIsNotNone(table_block.table_data)
        self.assertEqual(table_block.table_data.unit_of_measure, "₹ in Crore")
        self.assertIn("Total Income", table_block.text_content)

        # Trailing block must be footnotes below table
        last_block = blocks[-1]
        self.assertIn("Dividend declared", last_block.text_content)

    def test_rupeeforadian_font_artifact_normalized_to_rupee(self):
        """Pre-Unicode RupeeForadian font backtick must be converted to ₹ in Crore."""
        from pipeline.utils.text_normalizer import normalize_text
        from pipeline.utils.table_formatter import detect_unit_of_measure

        raw_header = "FINANCIAL HIGHLIGHTS (` in Crore)"
        normalized = normalize_text(raw_header)
        self.assertIn("(₹ in Crore)", normalized)
        self.assertNotIn("(` in Crore)", normalized)

        detected_unit = detect_unit_of_measure(normalized)
        self.assertEqual(detected_unit, "₹ in Crore")

    def test_structural_analyzer_pdf_toc_waterfall_not_bypassed(self):
        """PDF documents with TOC must use TOC discovery (Priority 3), not HTML heading tree (Priority 2)."""
        adapter = PDFDocumentAdapter()
        analyzer = StructuralAnalyzer()

        # Physical pages 20-50 contain published TOC metadata mapping to 5 chapters
        payload_20_50 = adapter.extract_file(
            "data/raw/annual_reports/ar26.pdf",
            config={"page_start": 20, "page_end": 50}
        )
        doc = analyzer.analyze(payload_20_50)

        # Must yield exactly 5 chapters via toc_page_discovery, NOT html_heading_tree
        self.assertEqual(len(doc.sections), 5)
        for s in doc.sections:
            self.assertEqual(s.segmentation_method, "toc_page_discovery")
        self.assertEqual(doc.sections[0].title, "Reference Information")
        self.assertEqual(doc.sections[1].title, "Board of Directors")
        self.assertEqual(doc.sections[4].title, "Directors’ Report")


if __name__ == "__main__":
    unittest.main()
