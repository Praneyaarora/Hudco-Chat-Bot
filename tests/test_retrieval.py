"""
Unit and Integration Tests for Layer 4 Retrieval Engine.
File: tests/test_retrieval.py

Covers:
- Canonical schema validation, malformed JSON, and duplicate chunk ID rejection.
- Table linearization (row particulars, column headers, units, captions).
- Financial tokenization (fiscal years, comma-separated numbers, currency normalization, stopwords).
- BM25 ranking, score diagnostics, and provenance preservation.
- Metadata filters (document, section, physical page range, table flag, stale chunks).
- Malformed filter validation.
- Deterministic index rebuilds.
- Calibrated confidence thresholding and abstention handling.
"""

import os
import json
import hashlib
import tempfile
import unittest

from pipeline.core.contracts import CanonicalChunk, StructuredTable
from pipeline.retrieval.contracts import (
    RetrievalFilter,
    TableMetadata,
    RetrievalResultItem,
    RetrievalResponse,
)
from pipeline.retrieval.table_linearizer import (
    linearize_table,
    build_searchable_chunk_text,
)
from pipeline.retrieval.tokenizer import tokenize
from pipeline.retrieval.loader import load_canonical_chunks, ChunkLoaderError
from pipeline.retrieval.bm25 import Layer4BM25Index


def create_sample_chunk(
    chunk_id: str,
    content: str,
    physical_page: int = 1,
    section_id: str = "sec_01",
    section_title: str = "Overview",
    has_table: bool = False,
    structured_tables = None,
    is_stale: bool = False,
    document_id: str = "doc_ar26",
    version_id: str = "v1",
) -> CanonicalChunk:
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return CanonicalChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        version_id=version_id,
        source_id="ar26_pdf",
        source_filename="ar26.pdf",
        section_id=section_id,
        section_title=section_title,
        ancestor_headings=["Annual Report 2025-26", section_title],
        chunk_index_in_section=0,
        chunk_index_in_page=0,
        physical_page=physical_page,
        printed_page=str(physical_page),
        char_count=len(content),
        token_estimate=len(content) // 4,
        has_table=has_table,
        structured_tables=structured_tables or [],
        content=content,
        content_sha256=sha,
        is_stale=is_stale,
    )


class TestTableLinearizer(unittest.TestCase):
    def test_linearize_table_with_units_and_headers(self):
        table = StructuredTable(
            table_id="tbl_fin_01",
            caption="Financial Highlights Summary",
            headers=["Particulars", "FY 2024-25", "FY 2023-24"],
            rows=[
                ["Revenue from Operations", "13,150.40", "11,200.10"],
                ["Net Profit (PAT)", "2,450.80", "1,890.30"],
            ],
            unit_of_measure="₹ in Crore",
            markdown_representation="| Particulars | FY 2024-25 | FY 2023-24 |\n|---|---|---|\n| Revenue | 13,150.40 | 11,200.10 |",
            physical_page=19,
            row_count=2,
            col_count=3,
        )

        linearized = linearize_table(table)
        self.assertIn("Table: Financial Highlights Summary", linearized)
        self.assertIn("Unit: ₹ in Crore", linearized)
        self.assertIn("Revenue from Operations | FY 2024-25: 13,150.40", linearized)
        self.assertIn("(₹ in Crore)", linearized)
        self.assertIn("Net Profit (PAT) | FY 2024-25: 2,450.80 | FY 2023-24: 1,890.30 (₹ in Crore)", linearized)

    def test_build_searchable_chunk_text(self):
        table = StructuredTable(
            table_id="tbl_fin_02",
            caption="Loan Sanctions",
            headers=["Sector", "Amount"],
            rows=[["Housing", "25000"]],
            unit_of_measure="Rs. Cr",
            markdown_representation="| Sector | Amount |\n|---|---|\n| Housing | 25000 |",
            physical_page=25,
            row_count=1,
            col_count=2,
        )
        text = build_searchable_chunk_text(
            content="Summary of annual sanctions.",
            structured_tables=[table],
            section_title="Operational Performance",
            ancestor_headings=["Business Highlights"],
        )
        self.assertIn("Operational Performance", text)
        self.assertIn("Business Highlights", text)
        self.assertIn("Summary of annual sanctions.", text)
        self.assertIn("Housing | Amount: 25000 (Rs. Cr)", text)


class TestTokenizer(unittest.TestCase):
    def test_fiscal_year_handling(self):
        tokens = tokenize("HUDCO performance for FY 2025-26 and 2024-25.")
        self.assertIn("2025-26", tokens)
        self.assertIn("2025", tokens)
        self.assertIn("2026", tokens)
        self.assertIn("2024-25", tokens)

    def test_comma_number_normalization(self):
        tokens = tokenize("Total revenue was Rs. 13,150.40 crore.")
        self.assertIn("13150.40", tokens)
        self.assertIn("crore", tokens)

    def test_stopword_removal_includes_pronouns(self):
        tokens = tokenize("He was appointed as Director in his official capacity.")
        self.assertNotIn("he", tokens)
        self.assertNotIn("his", tokens)
        self.assertNotIn("was", tokens)
        self.assertIn("appoint", tokens)
        self.assertIn("director", tokens)



class TestLoader(unittest.TestCase):
    def test_valid_load(self):
        c1 = create_sample_chunk("chunk_1", "First chunk content", 1)
        c2 = create_sample_chunk("chunk_2", "Second chunk content", 2)

        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(c1.model_dump_json() + "\n")
            f.write(c2.model_dump_json() + "\n")
            temp_path = f.name

        try:
            chunks = load_canonical_chunks(temp_path)
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].chunk_id, "chunk_1")
            self.assertEqual(chunks[1].chunk_id, "chunk_2")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_duplicate_chunk_rejection(self):
        c1 = create_sample_chunk("chunk_dup", "Duplicate content", 1)

        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(c1.model_dump_json() + "\n")
            f.write(c1.model_dump_json() + "\n")
            temp_path = f.name

        try:
            with self.assertRaises(ChunkLoaderError) as ctx:
                load_canonical_chunks(temp_path)
            self.assertIn("Duplicate chunk_id 'chunk_dup'", str(ctx.exception))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_malformed_json_handling(self):
        c1 = create_sample_chunk("chunk_1", "Valid chunk", 1)

        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(c1.model_dump_json() + "\n")
            f.write("{invalid_json: true\n")
            temp_path = f.name

        try:
            with self.assertRaises(ChunkLoaderError) as ctx:
                load_canonical_chunks(temp_path, strict=True)
            self.assertIn("invalid json", str(ctx.exception).lower())
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestBM25IndexAndRetrieval(unittest.TestCase):
    def setUp(self):
        self.c1 = create_sample_chunk(
            "c_exec_01",
            "Shri Sanjay Kulshrestha is the Chairman & Managing Director of HUDCO.",
            physical_page=5,
            section_id="sec_01",
            section_title="Board of Directors",
        )
        self.c2 = create_sample_chunk(
            "c_fin_01",
            "Net profit after tax for the year stood at Rs. 2,116.70 crore compared to Rs. 1,650.20 crore.",
            physical_page=19,
            section_id="sec_02",
            section_title="Financial Highlights",
            has_table=True,
            structured_tables=[
                StructuredTable(
                    table_id="tbl_fin_pat",
                    caption="PAT Trend",
                    headers=["Metric", "FY 2024-25"],
                    rows=[["Net Profit", "2,116.70"]],
                    unit_of_measure="₹ in Crore",
                    markdown_representation="| Metric | FY 2024-25 |\n|---|---|\n| Net Profit | 2,116.70 |",
                    physical_page=19,
                    row_count=1,
                    col_count=2,
                )
            ]
        )
        self.c3 = create_sample_chunk(
            "c_csr_01",
            "HUDCO undertakes diverse Corporate Social Responsibility initiatives across India.",
            physical_page=45,
            section_id="sec_03",
            section_title="CSR Activities",
        )
        self.c4_stale = create_sample_chunk(
            "c_old_01",
            "Superseded draft of chairman statement.",
            physical_page=50,
            is_stale=True,
        )
        self.index = Layer4BM25Index(
            chunks=[self.c1, self.c2, self.c3, self.c4_stale],
            abstention_threshold=1.0,
            min_term_coverage=0.40,
        )

    def test_ranking_and_diagnostics(self):
        resp = self.index.retrieve("Who is Chairman and Managing Director?", top_k=3)
        self.assertFalse(resp.is_abstention)
        self.assertGreater(resp.total_results, 0)
        top = resp.results[0]
        self.assertEqual(top.chunk_id, "c_exec_01")
        self.assertEqual(top.physical_page, 5)
        self.assertIn("chairman", top.matched_terms)
        self.assertIn("managing", top.matched_terms)
        self.assertIn("director", top.matched_terms)
        self.assertGreaterEqual(top.term_coverage, 0.50)
        self.assertTrue(len(top.explanation) > 0)

    def test_table_awareness_search(self):
        resp = self.index.retrieve("Net Profit 2,116.70 PAT Trend", top_k=3)
        self.assertFalse(resp.is_abstention)
        self.assertEqual(resp.results[0].chunk_id, "c_fin_01")
        self.assertTrue(resp.results[0].has_table)
        self.assertIsNotNone(resp.results[0].table_metadata)
        self.assertEqual(resp.results[0].table_metadata[0].table_id, "tbl_fin_pat")

    def test_metadata_filter_section_and_page(self):
        # Target financial section only
        filter_fin = RetrievalFilter(section_id="sec_02", min_physical_page=10, max_physical_page=25)
        resp = self.index.retrieve("profit", filters=filter_fin)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].chunk_id, "c_fin_01")

        # Exclude by page window
        filter_out_of_range = RetrievalFilter(min_physical_page=30, max_physical_page=40)
        resp2 = self.index.retrieve("profit", filters=filter_out_of_range)
        self.assertEqual(len(resp2.results), 0)
        self.assertTrue(resp2.is_abstention)

    def test_metadata_filter_has_table(self):
        filter_table = RetrievalFilter(has_table=True)
        resp = self.index.retrieve("profit", filters=filter_table)
        self.assertEqual(len(resp.results), 1)
        self.assertTrue(resp.results[0].has_table)

        filter_narrative = RetrievalFilter(has_table=False)
        resp_narrative = self.index.retrieve("profit", filters=filter_narrative)
        self.assertEqual(len(resp_narrative.results), 0)

    def test_stale_filter(self):
        resp_default = self.index.retrieve("superseded draft")
        # Default include_stale=False: should abstain / not find c4_stale
        self.assertTrue(resp_default.is_abstention)
        self.assertEqual(len(resp_default.results), 0)

        filter_stale = RetrievalFilter(include_stale=True)
        resp_stale = self.index.retrieve("superseded draft", filters=filter_stale)
        self.assertFalse(resp_stale.is_abstention)
        self.assertEqual(resp_stale.results[0].chunk_id, "c_old_01")

    def test_malformed_filter_raises_error(self):
        invalid_filter = RetrievalFilter(min_physical_page=100, max_physical_page=50)
        with self.assertRaises(ValueError) as ctx:
            self.index.retrieve("test query", filters=invalid_filter)
        self.assertIn("Invalid page range", str(ctx.exception))

    def test_empty_query_abstention(self):
        resp = self.index.retrieve("   ")
        self.assertTrue(resp.is_abstention)
        self.assertEqual(len(resp.results), 0)
        self.assertIn("Empty query", resp.abstention_reason)

    def test_unanswerable_query_abstention(self):
        # Query containing concepts nowhere in the documents
        resp = self.index.retrieve("Bitcoin cryptocurrency Ethereum reserves", score_threshold=10.0)
        self.assertTrue(resp.is_abstention)
        self.assertIsNotNone(resp.abstention_reason)

    def test_deterministic_rebuild(self):
        chunks = [self.c1, self.c2, self.c3]
        index1 = Layer4BM25Index(chunks)
        index2 = Layer4BM25Index(chunks)

        self.assertEqual(index1.doc_freq, index2.doc_freq)
        self.assertEqual(index1.avg_doc_len, index2.avg_doc_len)
        self.assertEqual(index1.idf, index2.idf)

        resp1 = index1.retrieve("Managing Director", top_k=2)
        resp2 = index2.retrieve("Managing Director", top_k=2)

        self.assertEqual(len(resp1.results), len(resp2.results))
        for r1, r2 in zip(resp1.results, resp2.results):
            self.assertEqual(r1.chunk_id, r2.chunk_id)
            self.assertEqual(r1.score, r2.score)
            self.assertEqual(r1.rank, r2.rank)


class TestPipelineRunner(unittest.TestCase):
    def test_pipeline_lock_acquire_and_release(self):
        from pathlib import Path
        from pipeline.runner import PipelineLock, PipelineLockError

        with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as f:
            lock_file = Path(f.name)

        try:
            # 1. Acquire and verify release
            lock1 = PipelineLock(lock_file)
            with lock1:
                self.assertTrue(lock_file.exists())
                # Nested acquire should raise lock conflict
                lock2 = PipelineLock(lock_file)
                with self.assertRaises(PipelineLockError):
                    lock2.acquire()

            self.assertFalse(lock_file.exists())
        finally:
            if lock_file.exists():
                lock_file.unlink()

    def test_runner_preflight_missing_file_raises_error(self):
        from pathlib import Path
        from pipeline.runner import EndToEndPipelineRunner

        with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as f:
            temp_lock = Path(f.name)
        if temp_lock.exists():
            temp_lock.unlink()

        try:
            runner = EndToEndPipelineRunner(
                source_pdf=Path("nonexistent_hudco_doc.pdf"),
                validation_only=True,
                lock_path=temp_lock,
            )
            # Should return exit code 3 (Preflight error)
            exit_code = runner.run()
            self.assertEqual(exit_code, 3)
        finally:
            if temp_lock.exists():
                temp_lock.unlink()

    def test_runner_preflight_unsupported_format(self):
        from pathlib import Path
        from pipeline.runner import EndToEndPipelineRunner

        with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as f:
            temp_lock = Path(f.name)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            dummy_docx = Path(f.name)
        if temp_lock.exists():
            temp_lock.unlink()

        try:
            runner = EndToEndPipelineRunner(
                source_pdf=dummy_docx,
                validation_only=True,
                lock_path=temp_lock,
            )
            exit_code = runner.run()
            self.assertEqual(exit_code, 3)
        finally:
            if temp_lock.exists():
                temp_lock.unlink()
            if dummy_docx.exists():
                dummy_docx.unlink()

    def test_pipeline_gate_failure_does_not_publish_approval_pointer(self):
        """
        Integration test verifying that when an acceptance gate fails,
        the runner DOES NOT publish/overwrite latest_approved_run.json.
        When gates pass, it publishes atomically.
        """
        import time
        from pathlib import Path
        from pipeline.runner import EndToEndPipelineRunner

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_out = tmp_path / "output_chunks"
            temp_out.mkdir()
            run_dir = temp_out / "run_test"
            run_dir.mkdir()
            latest_ptr = temp_out / "latest_approved_run.json"

            runner = EndToEndPipelineRunner(
                output_base_dir=temp_out,
                validation_only=True,
            )
            runner.effective_run_dir = run_dir
            runner.source_sha256 = "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41"
            runner.chunks = [create_sample_chunk("c01", "Sample content", physical_page=1)]
            runner.eval_metrics = {"metrics": {"page_recall_at_5": 0.5}}
            runner.gates = {"Gate 1": False}

            # 1. Finalize with gate failure
            runner._finalize_and_publish(all_passed=False, overall_start=time.time())

            # Manifest and report must exist in run_dir with FAILED status
            self.assertTrue((run_dir / "pipeline_manifest.json").exists())
            self.assertTrue((run_dir / "pipeline_quality_report.md").exists())
            with open(run_dir / "pipeline_manifest.json", "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.assertEqual(manifest_data["status"], "failed")

            # The approved pointer must NOT be written when gates fail
            self.assertFalse(latest_ptr.exists())

            # 2. When gates pass, pointer IS written atomically
            runner._finalize_and_publish(all_passed=True, overall_start=time.time())
            self.assertTrue(latest_ptr.exists())
            with open(latest_ptr, "r", encoding="utf-8") as f:
                ptr_data = json.load(f)
            self.assertEqual(ptr_data["source_sha256"], runner.source_sha256)

    def test_html_document_end_to_end_ingestion_and_retrieval(self):
        """
        Isolated integration test verifying Section 8:
        HTML extraction -> canonical representation -> chunking -> Layer 4 indexing and retrieval.
        """
        from pathlib import Path
        from pipeline.adapters.html_adapter import HTMLDocumentAdapter
        from pipeline.core.contracts import DocumentFormat
        from pipeline.core.pipeline_runner import run_phase2_pipeline

        html_content = """<!DOCTYPE html>
<html>
<head><title>HUDCO Institutional Report</title></head>
<body>
<h1>HUDCO Institutional Report 2026</h1>
<h2>Leadership and Management</h2>
<p>Shri Sanjay Kulshrestha is the Chairman and Managing Director of Housing and Urban Development Corporation.</p>
<h2>Financial Performance Summary</h2>
<p>During the fiscal year, sanctions reached record levels.</p>
<table>
<tr><th>Particulars</th><th>Amount (₹ Crore)</th></tr>
<tr><td>Loan Sanctions</td><td>12500</td></tr>
<tr><td>Loan Disbursements</td><td>9800</td></tr>
</table>
</body>
</html>"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            html_file = tmp_path / "report.html"
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)

            # 1. Extraction
            adapter = HTMLDocumentAdapter()
            payload = adapter.extract_file(html_file)
            self.assertEqual(payload.document_format, DocumentFormat.HTML)
            self.assertGreater(len(payload.pages), 0)

            # 2. Canonical representation & chunking
            out_dir = tmp_path / "artifacts"
            doc, chunks, _ = run_phase2_pipeline(
                payload=payload,
                output_dir=out_dir,
                target_chunk_size=500,
                max_chunk_size=1000,
            )
            self.assertGreater(len(chunks), 0)
            self.assertTrue(any(c.has_table for c in chunks))

            # 3. Layer 4 BM25 Indexing & Retrieval
            index = Layer4BM25Index(chunks, k1=1.2, b=0.45, abstention_threshold=1.0)
            resp = index.retrieve("Who is the Chairman and Managing Director?", top_k=2)

            self.assertFalse(resp.is_abstention)
            self.assertGreater(len(resp.results), 0)
            self.assertIn("kulshrestha", resp.results[0].content.lower())


class TestRegionalOfficeAndContactRanking(unittest.TestCase):
    """
    Regression tests for Priority P1: Regional Office directory vs Corporate Contact ranking.
    Verifies that regional office queries rank regional directories #1,
    while generic corporate contact queries still rank corporate offices #1.
    """

    def setUp(self):
        # 1. Regional office chunk (p. 518)
        content_reg = "THIRUVANANTHAPURAM: Housing & Urban Development Corporation Ltd. Regional Office, Saphalya Bhavan, Palayam, Thiruvananthapuram - 695034. Email: ro.thiruvananthapuram@hudco.org, Tel: 0471-2339742."
        self.chunk_regional = CanonicalChunk(
            chunk_id="chunk_reg_tvm_p518",
            document_id="doc_ar26",
            version_id="v1",
            source_id="ar26_pdf",
            source_filename="ar26.pdf",
            section_id="sec_18",
            section_title="HUDCO Offices",
            ancestor_headings=["Annual Report 2025-26", "HUDCO Offices", "REGIONAL OFFICES", "Thiruvananthapuram"],
            chunk_index_in_section=9,
            chunk_index_in_page=0,
            physical_page=518,
            printed_page="516",
            char_count=len(content_reg),
            token_estimate=len(content_reg) // 4,
            has_table=False,
            structured_tables=[],
            content=content_reg,
            content_sha256=hashlib.sha256(content_reg.encode("utf-8")).hexdigest(),
            is_stale=False,
        )

        # 2. Corporate registered office chunk (p. 215)
        content_corp = "REGISTERED OFFICE: HUDCO Bhawan, Core-7A, India Habitat Centre, Lodhi Road, New Delhi - 110003. Email: cshudco@hudco.org, Tel: 011-24649610. Website: www.hudco.org.in."
        self.chunk_corporate_reg = CanonicalChunk(
            chunk_id="chunk_corp_reg_p215",
            document_id="doc_ar26",
            version_id="v1",
            source_id="ar26_pdf",
            source_filename="ar26.pdf",
            section_id="sec_14",
            section_title="Corporate Governance",
            ancestor_headings=["Annual Report 2025-26", "Corporate Governance", "Registered Office"],
            chunk_index_in_section=1,
            chunk_index_in_page=0,
            physical_page=215,
            printed_page="213",
            char_count=len(content_corp),
            token_estimate=len(content_corp) // 4,
            has_table=False,
            structured_tables=[],
            content=content_corp,
            content_sha256=hashlib.sha256(content_corp.encode("utf-8")).hexdigest(),
            is_stale=False,
        )

        # 3. Generic corporate contact table in BRSR (p. 104)
        content_brsr = "General Information: Name of Company: Housing and Urban Development Corporation Limited. Corporate Identity Number (CIN): L74899DL1970GOI005276. Registered Office Address: HUDCO Bhawan, India Habitat Centre, Lodhi Road, New Delhi. Telephone: 011-24648426. E-mail: complianceofficer@hudco.org."
        self.chunk_brsr_generic = CanonicalChunk(
            chunk_id="chunk_brsr_gen_p104",
            document_id="doc_ar26",
            version_id="v1",
            source_id="ar26_pdf",
            source_filename="ar26.pdf",
            section_id="sec_07",
            section_title="General Disclosures",
            ancestor_headings=["Annual Report 2025-26", "Business Responsibility and Sustainability Report", "General Disclosures"],
            chunk_index_in_section=4,
            chunk_index_in_page=0,
            physical_page=104,
            printed_page="102",
            char_count=len(content_brsr),
            token_estimate=len(content_brsr) // 4,
            has_table=True,
            structured_tables=[],
            content=content_brsr,
            content_sha256=hashlib.sha256(content_brsr.encode("utf-8")).hexdigest(),
            is_stale=False,
        )

        # 4. Stale regional office chunk
        content_stale = "Old Thiruvananthapuram Office records."
        self.chunk_stale = CanonicalChunk(
            chunk_id="chunk_reg_stale",
            document_id="doc_ar26",
            version_id="v0",
            source_id="ar26_pdf",
            source_filename="ar26.pdf",
            section_id="sec_18",
            section_title="HUDCO Offices",
            ancestor_headings=["HUDCO Offices", "Regional Office"],
            chunk_index_in_section=0,
            chunk_index_in_page=0,
            physical_page=518,
            printed_page="516",
            char_count=len(content_stale),
            token_estimate=len(content_stale) // 4,
            has_table=False,
            structured_tables=[],
            content=content_stale,
            content_sha256=hashlib.sha256(content_stale.encode("utf-8")).hexdigest(),
            is_stale=True,
        )

        self.index = Layer4BM25Index([
            self.chunk_regional,
            self.chunk_corporate_reg,
            self.chunk_brsr_generic,
            self.chunk_stale,
        ], abstention_threshold=1.0)

    def test_regional_office_query_ranks_regional_chunk_rank_1(self):
        query = "What is the contact address, telephone, and email for HUDCO's Regional Office in Thiruvananthapuram?"
        resp = self.index.retrieve(query, top_k=3)

        self.assertFalse(resp.is_abstention)
        self.assertGreaterEqual(len(resp.results), 2)
        # Regional office must rank #1 above BRSR corporate contact
        self.assertEqual(resp.results[0].chunk_id, "chunk_reg_tvm_p518")
        self.assertEqual(resp.results[0].physical_page, 518)
        self.assertGreater(resp.results[0].score, resp.results[1].score)
        self.assertIn("thiruvananthapuram", resp.results[0].matched_terms)

    def test_corporate_contact_query_ranks_corporate_office_rank_1(self):
        query = "What is the registered corporate office address, telephone, and email for HUDCO in New Delhi?"
        resp = self.index.retrieve(query, top_k=3)

        self.assertFalse(resp.is_abstention)
        # Corporate registered office or BRSR should be rank 1 (both New Delhi), NOT Thiruvananthapuram
        self.assertIn(resp.results[0].chunk_id, {"chunk_corp_reg_p215", "chunk_brsr_gen_p104"})
        self.assertIn(resp.results[0].physical_page, {215, 104})
        # Thiruvananthapuram should NOT be rank 1
        self.assertNotEqual(resp.results[0].chunk_id, "chunk_reg_tvm_p518")

    def test_filters_and_stale_exclusion(self):
        query = "HUDCO office contact details"

        # Stale chunk excluded by default
        resp_default = self.index.retrieve(query, top_k=10)
        retrieved_ids = [r.chunk_id for r in resp_default.results]
        self.assertNotIn("chunk_reg_stale", retrieved_ids)

        # Page range filter isolating regional office page
        filt_reg = RetrievalFilter(min_physical_page=500, max_physical_page=520)
        resp_reg = self.index.retrieve(query, filters=filt_reg, top_k=10)
        self.assertTrue(all(500 <= r.physical_page <= 520 for r in resp_reg.results))
        self.assertEqual(len(resp_reg.results), 1)
        self.assertEqual(resp_reg.results[0].chunk_id, "chunk_reg_tvm_p518")

    def test_scores_and_metadata_consistency(self):
        query = "Thiruvananthapuram regional office telephone"
        resp = self.index.retrieve(query, top_k=2)

        self.assertFalse(resp.is_abstention)
        r0 = resp.results[0]
        self.assertEqual(r0.chunk_id, "chunk_reg_tvm_p518")
        self.assertGreater(r0.score, 0.0)
        self.assertGreater(r0.term_coverage, 0.5)
        self.assertEqual(r0.rank, 1)
        self.assertEqual(r0.document_id, "doc_ar26")
        self.assertEqual(r0.section_id, "sec_18")
        self.assertEqual(r0.physical_page, 518)


if __name__ == "__main__":
    unittest.main()

