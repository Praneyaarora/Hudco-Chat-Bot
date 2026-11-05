"""
Focused Unit Tests for Phase 1: Core Foundation & PDF/HTML Extraction Adapters.
File: tests/test_phase1.py

Covers:
- Canonical contracts validation, section ordering, and locator invariants.
- Multi-dimensional deterministic chunk ID generation with source versions,
  processing revisions, and content hashes.
- Conservative text normalization: strict preservation of Unicode punctuation (em-dashes,
  en-dashes, typographic quotes, Indian Rupee sign), legal citations, and numeric expressions.
- Structured table formatting: padding jagged rows without fabricated values,
  distinguishing headless tables, and treating Markdown strictly as a display layer.
- PDF printed-page detection: conservative hierarchy rejecting standalone financial numbers,
  table rows, and dates while recognizing explicit headers/footers and valid Roman numerals.
- In-memory PDF extraction: physical page counting, non-empty text stream extraction,
  empty page detection, and hierarchical outline/bookmark extraction.
- HTML extraction: heading hierarchies, structured tables, nested container traversal,
  provenance locators with approximate flags, inline & metadata link preservation,
  conservative preservation of header/footer/aside content, and parser resilience.

NOTE: As per project guidelines, these tests are written for Phase 1 verification
and are reported as strictly UNEXECUTED until explicit authorization.
"""

import io
import unittest
import pypdf

from pipeline.core.contracts import (
    DocumentFormat,
    SourceType,
    DiscoveryMethod,
    ProcessingStatus,
    BlockType,
    WarningCategory,
    SourceConfiguration,
    PDFSourceLocator,
    HTMLSourceLocator,
    StructuredTable,
    ContentBlock,
    CanonicalSection,
    DocumentMetadata,
    CanonicalChunk,
    DocumentVersion,
)
from pipeline.adapters.pdf_adapter import PDFDocumentAdapter, detect_printed_page_label
from pipeline.adapters.html_adapter import HTMLDocumentAdapter, StandardLibraryHTMLParser
from pipeline.utils.text_normalizer import normalize_text, normalize_whitespace, clean_cell_text
from pipeline.utils.table_formatter import build_structured_table, format_matrix_to_gfm, detect_unit_of_measure


class TestPhase1Contracts(unittest.TestCase):
    """Validates canonical Pydantic v2 data models, provenance, and chunk identity invariants."""

    def test_canonical_section_page_ordering_validation(self):
        """Verifies that physical_page_end cannot be less than physical_page_start."""
        # Valid section
        sec = CanonicalSection(
            section_id="sec_01",
            title="Board of Directors",
            level=1,
            physical_page_start=10,
            physical_page_end=20,
            printed_page_start="8",
            printed_page_end="18",
            segmentation_method="native_outline",
            confidence="high"
        )
        self.assertEqual(sec.physical_page_start, 10)
        self.assertEqual(sec.physical_page_end, 20)

        # Invalid section where end < start must raise ValueError
        with self.assertRaises(ValueError):
            CanonicalSection(
                section_id="sec_01",
                title="Invalid Section",
                level=1,
                physical_page_start=20,
                physical_page_end=10,
                segmentation_method="fallback",
                confidence="low"
            )

    def test_version_aware_deterministic_chunk_id_with_revisions(self):
        """
        Verifies that chunk IDs cleanly separate source versions, processing revisions,
        and content hashes without collision across pipeline reruns.
        """
        content_hash = "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41"

        # Baseline chunk ID
        id_v1_r1 = CanonicalChunk.generate_chunk_id(
            document_id="annual_report_ar26",
            version_number=1,
            content_sha256=content_hash,
            section_id="sec_05",
            physical_page=52,
            chunk_index=0,
            processing_revision=1
        )
        self.assertEqual(id_v1_r1, "annual_report_ar26_v1_c412ce14_sec_05_p052_c00")

        # Reprocessing with revised parser/chunker (revision 2) produces distinct ID
        id_v1_r2 = CanonicalChunk.generate_chunk_id(
            document_id="annual_report_ar26",
            version_number=1,
            content_sha256=content_hash,
            section_id="sec_05",
            physical_page=52,
            chunk_index=0,
            processing_revision=2
        )
        self.assertEqual(id_v1_r2, "annual_report_ar26_v1_r2_c412ce14_sec_05_p052_c00")
        self.assertNotEqual(id_v1_r1, id_v1_r2)

        # Reprocessing with new document source version (version 2) produces distinct ID
        id_v2_r1 = CanonicalChunk.generate_chunk_id(
            document_id="annual_report_ar26",
            version_number=2,
            content_sha256="f890ba12393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41",
            section_id="sec_05",
            physical_page=52,
            chunk_index=0,
            processing_revision=1
        )
        self.assertEqual(id_v2_r1, "annual_report_ar26_v2_f890ba12_sec_05_p052_c00")
        self.assertNotEqual(id_v1_r1, id_v2_r1)

    def test_source_locator_approximate_and_exact_provenance(self):
        """Verifies that HTMLSourceLocator explicitly distinguishes exact from approximate locators."""
        approx_locator = HTMLSourceLocator(
            source_url="https://hudco.org/schemes",
            css_selector="html > body > main > p",
            heading_hierarchy=["Schemes", "Housing"],
            is_approximate=True
        )
        self.assertTrue(approx_locator.is_approximate)
        self.assertEqual(approx_locator.css_selector, "html > body > main > p")

        exact_locator = HTMLSourceLocator(
            source_url="https://hudco.org/schemes",
            css_selector="#section-interest-rates",
            heading_hierarchy=["Schemes", "Interest Rates"],
            is_approximate=False
        )
        self.assertFalse(exact_locator.is_approximate)


class TestTextNormalizerAndTableFormatter(unittest.TestCase):
    """Validates conservative text normalization and structured table formatting."""

    def test_conservative_text_normalization_preserves_unicode_and_punctuation(self):
        """
        Verifies that whitespace is cleaned without mutating substantive punctuation:
        em-dashes, en-dashes, typographic quotes, currency symbols, and legal citations must survive intact.
        """
        sample_legal = (
            "Under Section\u00a0135(1) of the Companies Act, 2013 \u2014 every eligible company "
            "shall allocate at least \u201c2% of average net profits\u201d for CSR.\r\n"
            "HUDCO sanctioned \u20b9 15,200.50 Crore during FY\u00a02025\u201326.\r\n\r\n\r\n"
            "Notice dated 25th March, 2026."
        )
        normalized = normalize_whitespace(sample_legal)

        # Em dash and en dash preserved
        self.assertIn("—", normalized)
        self.assertIn("–", normalized)
        # Indian Rupee symbol preserved
        self.assertIn("₹ 15,200.50 Crore", normalized)
        # Typographic quotes preserved
        self.assertIn("“2% of average net profits”", normalized)
        # Legal citation preserved
        self.assertIn("Section 135(1) of the Companies Act, 2013", normalized)
        # Non-breaking space normalized to single regular space
        self.assertNotIn("\u00a0", normalized)
        # Excessive newlines collapsed
        self.assertNotIn("\r", normalized)
        self.assertNotIn("\n\n\n", normalized)

    def test_table_formatter_padding_and_no_fabrication(self):
        """Verifies that jagged tables are padded with empty strings and flagged malformed without inventing values."""
        raw_matrix = [
            ["Particulars", "FY 2024-25", "FY 2023-24"],
            ["Total Income", "10,500.20", "8,900.10"],
            ["Net Profit", "2,100.50"],  # Missing 3rd column
        ]
        st = build_structured_table(raw_matrix, table_id="test_tbl_01", unit_of_measure="₹ in Crore")
        self.assertIsNotNone(st)
        self.assertTrue(st.is_malformed)
        self.assertEqual(st.col_count, 3)
        self.assertEqual(st.row_count, 2)
        # 2nd body row padded with empty string
        self.assertEqual(st.rows[1], ["Net Profit", "2,100.50", ""])
        # Unit of measure captured as advisory
        self.assertEqual(st.unit_of_measure, "₹ in Crore")
        # Header recognized
        self.assertTrue(st.has_explicit_headers)

    def test_headless_table_handling(self):
        """Verifies that headless data tables (where row 0 contains numeric data) are not falsely given headers."""
        raw_numeric_matrix = [
            ["101", "2024-03-31", "15420.50"],
            ["102", "2024-06-30", "16890.00"],
            ["103", "2024-09-30", "17200.10"],
        ]
        st = build_structured_table(raw_numeric_matrix, table_id="tbl_numeric")
        self.assertIsNotNone(st)
        self.assertFalse(st.has_explicit_headers)
        # All 3 rows preserved in data rows
        self.assertEqual(len(st.rows), 3)
        self.assertEqual(st.rows[0], ["101", "2024-03-31", "15420.50"])

    def test_table_markdown_is_display_only(self):
        """Verifies that Markdown representation is a formatted projection, not the canonical structured data."""
        raw_matrix = [
            ["Metric", "Value"],
            ["CRAR (%)", "24.50"],
            ["GNPA (%)", "0.35"]
        ]
        st = build_structured_table(raw_matrix, table_id="tbl_ratios")
        self.assertIsNotNone(st)
        # Authoritative structured representation
        self.assertEqual(st.headers, ["Metric", "Value"])
        self.assertEqual(st.rows, [["CRAR (%)", "24.50"], ["GNPA (%)", "0.35"]])
        # Markdown representation is display layer
        self.assertIn("| Metric | Value |", st.markdown_representation)
        self.assertIn("| CRAR (%) | 24.50 |", st.markdown_representation)


class TestPDFExtractionAdapter(unittest.TestCase):
    """Validates PDF extraction with physical/printed page separation, confidence, and text extraction."""

    def test_roman_numeral_and_arabic_printed_page_detection(self):
        """Verifies that running header/footer regex detects both Arabic and valid Roman numeral printed page labels."""
        # Arabic numeral header
        text_arabic = "52 | ANNUAL REPORT 2025-26\nDirectors' Report continues with operations."
        self.assertEqual(detect_printed_page_label(text_arabic), "52")

        # Running footer with page label
        text_footer = "Annual Report 2025-26 | Page 104\nHousing and Urban Development Corporation"
        self.assertEqual(detect_printed_page_label(text_footer), "104")

        # Valid Roman numeral header
        text_roman = "iv | ANNUAL REPORT 2025-26\nTable of Contents and General Information."
        self.assertEqual(detect_printed_page_label(text_roman), "iv")

        # Valid upper-case Roman numeral footer
        text_roman_upper = "XII | HUDCO Financial Statements Overview"
        self.assertEqual(detect_printed_page_label(text_roman_upper), "XII")

    def test_ambiguous_numeric_lines_not_treated_as_printed_page(self):
        """
        Conservative evidence hierarchy: standalone numbers from financial tables, note references,
        and dates must NOT be falsely identified as printed page labels.
        """
        # Standalone financial figure
        text_financial = "Balance Sheet as at 31st March 2026\nTotal Assets\n15200\nEnd of Statement"
        self.assertIsNone(detect_printed_page_label(text_financial))

        # Standalone year
        text_year = "HUDCO Annual General Meeting\n2026"
        self.assertIsNone(detect_printed_page_label(text_year))

        # Note number ending
        text_note = "See accompanying accounting policies and principles\nNote 24"
        self.assertIsNone(detect_printed_page_label(text_note))

        # Text with no page numbering
        text_clean = "Cover Page of Annual Report Housing and Urban Development Corporation"
        self.assertIsNone(detect_printed_page_label(text_clean))

    def test_pdf_adapter_page_by_page_and_empty_page_handling(self):
        """Creates a mock in-memory 2-page PDF (Page 1 has text stream, Page 2 is blank) and verifies extraction."""
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=612, height=792)
        writer.add_metadata({"/Title": "HUDCO Test Document", "/Author": "HUDCO Secretarial"})

        pdf_stream = io.BytesIO()
        writer.write(pdf_stream)
        pdf_bytes = pdf_stream.getvalue()

        adapter = PDFDocumentAdapter()
        payload = adapter.extract_bytes(pdf_bytes, filename="mock_test.pdf")

        self.assertEqual(payload.total_physical_pages, 2)
        self.assertEqual(len(payload.pages), 2)
        self.assertEqual(payload.pages[0].physical_page, 1)
        self.assertEqual(payload.pages[1].physical_page, 2)
        self.assertTrue(payload.pages[1].is_empty)
        self.assertEqual(payload.metadata.get("Title"), "HUDCO Test Document")

    def test_pdf_text_extraction_with_real_content_stream(self):
        """
        Verifies actual text extraction from an in-memory PDF fixture with genuine content streams.
        Distinguishes non-empty extraction from empty page extraction.
        """
        # Minimal valid 1-page PDF 1.4 byte sequence containing authentic text stream
        text_content = "HUDCO Annual Report 2025-26 Page 1 Board Approval"
        stream_bytes = f"BT /F1 12 Tf 50 750 Td ({text_content}) Tj ET\n".encode("latin-1")
        stream_len = len(stream_bytes)
        pdf_raw = (
            b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            b"4 0 obj << /Length " + str(stream_len).encode("ascii") + b" >>\nstream\n"
            + stream_bytes +
            b"endstream\nendobj\n"
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
            b"xref\n0 6\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"0000000228 00000 n \n"
            b"0000000300 00000 n \n"
            b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n380\n%%EOF\n"
        )

        adapter = PDFDocumentAdapter()
        payload = adapter.extract_bytes(pdf_raw, filename="real_content.pdf")

        self.assertEqual(payload.total_physical_pages, 1)
        self.assertFalse(payload.pages[0].is_empty)
        self.assertIn("HUDCO Annual Report", payload.pages[0].text)
        self.assertGreater(payload.pages[0].char_count, 10)

    def test_pdf_outline_bookmark_extraction(self):
        """Verifies native PDF outline/bookmark extraction when outlines are present."""
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=612, height=792)
        # Add outline bookmarks
        writer.add_outline_item(title="1. Directors' Report", page_number=0)
        writer.add_outline_item(title="2. Financial Statements", page_number=1)

        pdf_stream = io.BytesIO()
        writer.write(pdf_stream)
        pdf_bytes = pdf_stream.getvalue()

        adapter = PDFDocumentAdapter()
        payload = adapter.extract_bytes(pdf_bytes, filename="bookmarked.pdf")

        self.assertEqual(len(payload.outline_entries), 2)
        self.assertEqual(payload.outline_entries[0]["title"], "1. Directors' Report")
        self.assertEqual(payload.outline_entries[0]["physical_page"], 1)
        self.assertEqual(payload.outline_entries[1]["title"], "2. Financial Statements")
        self.assertEqual(payload.outline_entries[1]["physical_page"], 2)


class TestHTMLExtractionAdapter(unittest.TestCase):
    """Validates HTML extraction, provenance, link preservation, and parser resilience."""

    def test_html_adapter_heading_and_table_extraction(self):
        """Verifies HTML document title, heading hierarchy, paragraphs, and tables."""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HUDCO - Housing Finance Schemes</title>
            <style>body { font-family: sans-serif; }</style>
            <script>console.log("analytics");</script>
        </head>
        <body>
            <main>
                <h1>Housing Finance Schemes</h1>
                <p>HUDCO provides comprehensive retail and bulk housing loans across India.</p>
                <h2>Interest Rates FY 2025-26</h2>
                <ul>
                    <li>Individual Housing: 8.50%</li>
                    <li>Social Housing: 7.75%</li>
                </ul>
                <table>
                    <thead>
                        <tr><th>Scheme Name</th><th>Max Loan (₹ Crore)</th><th>Interest Rate</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>PMAY-U 2.0</td><td>0.50</td><td>6.50%</td></tr>
                        <tr><td>General Housing</td><td>5.00</td><td>8.75%</td></tr>
                    </tbody>
                </table>
            </main>
        </body>
        </html>
        """
        adapter = HTMLDocumentAdapter()
        payload = adapter.extract_bytes(html_content.encode("utf-8"), filename="schemes.html")

        self.assertEqual(payload.total_physical_pages, 1)
        self.assertEqual(payload.metadata.get("title"), "HUDCO - Housing Finance Schemes")

        page = payload.pages[0]
        self.assertFalse(page.is_empty)

        # Verify scripts were excluded
        self.assertNotIn("analytics", page.text)

        # Verify headings, paragraphs, and lists are present
        self.assertIn("Housing Finance Schemes", page.text)
        self.assertIn("Interest Rates FY 2025-26", page.text)
        self.assertIn("Individual Housing: 8.50%", page.text)

        # Verify table extraction
        self.assertEqual(len(page.tables), 1)
        tbl = page.tables[0]
        self.assertEqual(tbl.col_count, 3)
        self.assertEqual(tbl.row_count, 2)
        self.assertIn("| Scheme Name | Max Loan (₹ Crore) | Interest Rate |", tbl.markdown_representation)
        self.assertIn("| PMAY-U 2.0 | 0.50 | 6.50% |", tbl.markdown_representation)

    def test_html_adapter_preserves_hyperlinks(self):
        """
        Verifies that hyperlinks preserve anchor text, original href, resolved URL against source_url,
        and accurately classify PDF, HTML, and non-document links with official HUDCO host checking.
        """
        html_content = """
        <html><body>
            <p>Visit the official portal at <a href="/schemes">HUDCO Schemes</a> for guidelines.</p>
            <p>Download the official <a href="/writereaddata/annual-report-2025-26.pdf">Annual Report 2025-26</a>.</p>
            <p>Read external analysis at <a href="https://external-news.org/hudco">News Portal</a>.</p>
            <p>Skip to <a href="#content">Content</a> or <a href="javascript:print()">Print</a>.</p>
        </body></html>
        """
        adapter = HTMLDocumentAdapter()
        payload = adapter.extract_bytes(
            html_content.encode("utf-8"),
            filename="links.html",
            config={"source_url": "https://www.hudco.org.in/annual-reports"}
        )

        p1 = payload.pages[0].blocks[0]
        self.assertIn("[HUDCO Schemes](https://www.hudco.org.in/schemes)", p1.text_content)
        self.assertEqual(p1.metadata["links"][0]["original_href"], "/schemes")
        self.assertEqual(p1.metadata["links"][0]["resolved_url"], "https://www.hudco.org.in/schemes")
        self.assertEqual(p1.metadata["links"][0]["link_type"], "html_page")
        self.assertTrue(p1.metadata["links"][0]["is_official_host"])
        self.assertFalse(p1.metadata["links"][0]["is_downloadable_document"])

        p2 = payload.pages[0].blocks[1]
        self.assertIn("[Annual Report 2025-26](https://www.hudco.org.in/writereaddata/annual-report-2025-26.pdf)", p2.text_content)
        self.assertEqual(p2.metadata["links"][0]["original_href"], "/writereaddata/annual-report-2025-26.pdf")
        self.assertEqual(p2.metadata["links"][0]["link_type"], "pdf")
        self.assertTrue(p2.metadata["links"][0]["is_downloadable_document"])
        self.assertTrue(p2.metadata["links"][0]["is_official_host"])

        p3 = payload.pages[0].blocks[2]
        self.assertFalse(p3.metadata["links"][0]["is_official_host"])

        p4 = payload.pages[0].blocks[3]
        # Non-document fragment and javascript links are not added to block links
        self.assertEqual(len(p4.metadata.get("links", [])), 0)

    def test_html_adapter_nested_containers_and_locators(self):
        """Verifies that nested elements (main > article > p) produce approximate locators without duplicating text."""
        html_content = """
        <html><body>
            <main>
                <article>
                    <p>Substantive article paragraph inside nested semantic containers.</p>
                </article>
            </main>
        </body></html>
        """
        adapter = HTMLDocumentAdapter()
        payload = adapter.extract_bytes(html_content.encode("utf-8"), filename="nested.html")

        blocks = [b for b in payload.pages[0].blocks if b.block_type == BlockType.PARAGRAPH]
        # Must not duplicate the paragraph
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text_content, "Substantive article paragraph inside nested semantic containers.")
        # Must flag selector as approximate
        self.assertTrue(blocks[0].locator.is_approximate)

    def test_html_adapter_preserves_header_footer_aside_content(self):
        """
        Verifies conservative chrome filtering: substantive content placed inside
        header, footer, or aside tags is preserved rather than aggressively pruned.
        """
        html_content = """
        <html><body>
            <header>
                <p>HUDCO Official Annual Report Release Bulletin</p>
            </header>
            <aside>
                <p>Note: Interest subvention applies under PMAY guidelines.</p>
            </aside>
            <footer>
                <p>© 2026 Housing and Urban Development Corporation Ltd. All rights reserved.</p>
            </footer>
        </body></html>
        """
        adapter = HTMLDocumentAdapter()
        payload = adapter.extract_bytes(html_content.encode("utf-8"), filename="chrome.html")

        text = payload.pages[0].text
        self.assertIn("HUDCO Official Annual Report Release Bulletin", text)
        self.assertIn("Note: Interest subvention applies under PMAY guidelines.", text)
        self.assertIn("All rights reserved.", text)


if __name__ == "__main__":
    unittest.main()
