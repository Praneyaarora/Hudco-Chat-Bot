"""
Mandatory Artifact-Dependent Acceptance Gate Tests.
File: tests/test_acceptance_gates.py

CRITICAL CONTRACT:
These tests verify real artifacts on disk. If a required artifact is missing,
the test must explicitly FAIL (no silent skipping or false-green passes).
"""

import json
import hashlib
import unittest
from pathlib import Path

from pipeline.core.contracts import CanonicalChunk
from pipeline.retrieval.contracts import RetrievalFilter
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.loader import load_canonical_chunks
from pipeline.stage_1_ingestion.downloader import DocumentDownloader


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestMandatoryArtifactAcceptance(unittest.TestCase):
    """
    Mandatory acceptance gates covering real on-disk artifacts.
    Any missing artifact or hash deviation causes an explicit test failure.
    """

    def setUp(self):
        self.approved_pointer_path = PROJECT_ROOT / "data" / "output_chunks" / "latest_approved_run.json"
        self.ar26_pdf_path = PROJECT_ROOT / "data" / "raw" / "annual_reports" / "ar26.pdf"
        self.ar26_chunks_path = PROJECT_ROOT / "data" / "output_chunks" / "run_full_ar26_p1_520_v1" / "chunks.jsonl"
        self.ar24_pdf_path = PROJECT_ROOT / "data" / "raw" / "annual_reports" / "ar24.pdf"
        self.ar24_chunks_path = PROJECT_ROOT / "data" / "output_chunks" / "run_pilot_ar24_p1_426_v1" / "chunks.jsonl"
        self.ar24_sections_path = PROJECT_ROOT / "data" / "output_chunks" / "run_pilot_ar24_p1_426_v1" / "sections.json"
        self.source_registry_path = PROJECT_ROOT / "data" / "source_registry.json"

    def test_mandatory_artifacts_exist(self):
        """MANDATORY GATE: All required baseline and pilot artifacts must physically exist on disk."""
        self.assertTrue(self.approved_pointer_path.exists(), f"Missing mandatory artifact: {self.approved_pointer_path}")
        self.assertTrue(self.ar26_pdf_path.exists(), f"Missing mandatory artifact: {self.ar26_pdf_path}")
        self.assertTrue(self.ar26_chunks_path.exists(), f"Missing mandatory artifact: {self.ar26_chunks_path}")
        self.assertTrue(self.ar24_pdf_path.exists(), f"Missing mandatory artifact: {self.ar24_pdf_path}")
        self.assertTrue(self.ar24_chunks_path.exists(), f"Missing mandatory artifact: {self.ar24_chunks_path}")
        self.assertTrue(self.ar24_sections_path.exists(), f"Missing mandatory artifact: {self.ar24_sections_path}")
        self.assertTrue(self.source_registry_path.exists(), f"Missing mandatory artifact: {self.source_registry_path}")

    def test_approved_ar26_baseline_integrity(self):
        """MANDATORY GATE: Approved ar26 run pointer, hashes, and chunk counts must be 100% intact."""
        with open(self.approved_pointer_path, "r", encoding="utf-8") as f:
            pointer = json.load(f)

        # 1. Approved run directory
        self.assertIn("run_full_ar26_p1_520_v1", pointer["approved_run_dir"])
        self.assertEqual(pointer["source_filename"], "ar26.pdf")

        # 2. Source PDF SHA-256
        expected_src_sha = "c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41"
        self.assertEqual(pointer["source_sha256"], expected_src_sha)
        actual_src_sha = DocumentDownloader.compute_sha256_of_file(self.ar26_pdf_path)
        self.assertEqual(actual_src_sha, expected_src_sha, "Physical ar26.pdf hash does not match approved pointer!")

        # 3. Approved chunk count
        self.assertEqual(pointer["total_chunks"], 2682)

        # 4. Physical chunks file SHA-256 and line count
        expected_chunks_sha = "e631a0e75f6bf838865a470cd506ef1dd7624ea8836d6fc42e40e05ae849a1c9"
        actual_chunks_sha = DocumentDownloader.compute_sha256_of_file(self.ar26_chunks_path)
        self.assertEqual(actual_chunks_sha, expected_chunks_sha, "Approved ar26 chunks.jsonl has been altered!")

        ar26_chunks = load_canonical_chunks(str(self.ar26_chunks_path))
        self.assertEqual(len(ar26_chunks), 2682, "Approved ar26 chunk count mismatch!")

        # 5. ID uniqueness in ar26
        ids = [c.chunk_id for c in ar26_chunks]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate chunk IDs found in approved ar26 run!")

    def test_real_ar24_page_provenance_and_citation_regression(self):
        """
        MANDATORY GATE: Real ar24 PDF page-8 narrative attribution defect.
        Verifies that text originating on physical page 8 within a multi-page chunk
        has physical_pages containing 8, and is retrievable when filtering on page 8.
        """
        ar24_chunks = load_canonical_chunks(str(self.ar24_chunks_path))
        self.assertEqual(len(ar24_chunks), 2360, "ar24 chunk count must be 2360 (authoritative calibrated run).")

        # Locate the specific multi-page chunk spanning physical pages 5 through 16
        multi_page_chunk = None
        for c in ar24_chunks:
            if c.physical_page == 5 and c.physical_pages and 8 in c.physical_pages:
                multi_page_chunk = c
                break

        self.assertIsNotNone(multi_page_chunk, "Could not find multi-page chunk spanning page 8 in real ar24 chunks!")
        self.assertEqual(multi_page_chunk.physical_page, 5, "Start page must be preserved for chunk ID stability.")
        self.assertIn(8, multi_page_chunk.physical_pages, "Physical page 8 must be present in physical_pages list!")
        self.assertIsNotNone(multi_page_chunk.physical_page_end, "physical_page_end must be set on multi-page chunk.")
        self.assertGreaterEqual(multi_page_chunk.physical_page_end, 8)

        # Build retrieval index and test page-8 filtered query
        index = Layer4BM25Index()
        index.build_index(ar24_chunks)

        # Query with physical page filter strictly targeting page 8
        res = index.retrieve(
            query="Human Settlement Management Institute HSMI Regional Offices",
            filters=RetrievalFilter(min_physical_page=8, max_physical_page=8),
            score_threshold=0.0,
        )

        self.assertFalse(res.is_abstention, "Retrieval on physical page 8 must not abstain when evidence is present.")
        retrieved_ids = [r.chunk_id for r in res.results]
        self.assertIn(multi_page_chunk.chunk_id, retrieved_ids, "Multi-page chunk was not retrieved with page 8 filter!")

        # Verify retrieved result exposes exact citation page and human-readable label
        item = next(r for r in res.results if r.chunk_id == multi_page_chunk.chunk_id)
        self.assertIn(8, item.physical_pages)
        self.assertEqual(item.citation_page, 8, "Citation page must identify targeted page 8, not chunk start page 5!")
        self.assertEqual(item.citation_label, "Page 8", "Citation label must accurately cite Page 8!")
        self.assertEqual(item.citation_pages, [8])

    def test_real_ar24_structural_section_count_reconciliation(self):
        """
        MANDATORY GATE: Structural analysis must reflect calibrated 19 sections (not 2).
        """
        with open(self.ar24_sections_path, "r", encoding="utf-8") as f:
            sections = json.load(f)

        self.assertEqual(len(sections), 19, f"Authoritative ar24 section count must be 19, found {len(sections)}")

    def test_source_registry_reconciliation_and_standards(self):
        """
        MANDATORY GATE: Source registry must enforce canonical source_id and document_id standards
        and match authoritative chunk counts.
        """
        with open(self.source_registry_path, "r", encoding="utf-8") as f:
            registry_data = json.load(f)

        sources = registry_data.get("sources", {})
        self.assertIn("hudco_annual_report_ar24", sources)
        self.assertIn("hudco_annual_report_ar26", sources)

        # Verify canonical ID conventions
        for sid, rec in sources.items():
            self.assertTrue(sid.startswith("hudco_annual_report_ar"), f"Non-canonical source_id: {sid}")
            expected_doc_id = sid.replace("hudco_annual_report_", "doc_")
            self.assertEqual(rec.get("document_id"), expected_doc_id, f"Document ID mismatch for {sid}")

        # Authoritative chunk counts
        self.assertEqual(sources["hudco_annual_report_ar26"]["chunk_count"], 2682)
        self.assertEqual(sources["hudco_annual_report_ar24"]["chunk_count"], 2360)

    def test_comparative_table_fiscal_years_do_not_confuse_report_fiscal_year(self):
        """
        MANDATORY GATE: Ensure historical years appearing in comparative tables
        (e.g. 2019-20, 2020-21, 2021-22, 2022-23 columns in 2023-24 report) do not confuse or overwrite
        the canonical report fiscal year.
        """
        import re
        ar24_chunks = load_canonical_chunks(str(self.ar24_chunks_path))
        # Find chunks containing tables with comparative multi-year columns
        comparative_chunks = []
        for c in ar24_chunks:
            if c.has_table:
                for t in c.structured_tables:
                    header_text = " ".join(t.headers)
                    matches = set(re.findall(r"20\d{2}-\d{2}", header_text))
                    if len(matches) > 1 and "2023-24" in matches:
                        comparative_chunks.append((c, matches))
                        break

        self.assertGreater(len(comparative_chunks), 0, "Expected comparative multi-year tables in ar24!")
        for c, prior_years in comparative_chunks:
            # Canonical chunk fiscal year MUST remain the report's own fiscal year (2023-24)
            self.assertEqual(
                c.fiscal_year,
                "2023-24",
                f"Chunk {c.chunk_id} fiscal_year confused with comparative table years: {c.fiscal_year}",
            )
            # Prior years from columns (e.g. 2022-23, 2021-22) must not overwrite chunk.fiscal_year
            other_years = prior_years - {"2023-24"}
            self.assertGreater(len(other_years), 0)

    def test_per_report_manifest_consistency(self):
        """
        MANDATORY GATE: Verify every completed run directory has a valid, consistent manifest
        with zero duplicate chunk IDs, matching chunk counts, and valid hashes.
        """
        output_chunks_dir = PROJECT_ROOT / "data" / "output_chunks"
        manifest_files = list(output_chunks_dir.glob("run_*/manifest.json"))
        self.assertGreaterEqual(len(manifest_files), 1, "At least one completed run manifest must exist.")

        for mf_path in manifest_files:
            with open(mf_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Mandatory schema fields
            required_fields = [
                "document_id", "source_id", "source_filename", "fiscal_year",
                "file_sha256", "total_physical_pages", "chunk_count",
                "unique_chunk_id_count", "section_count", "chunks_sha256", "status",
            ]
            for field in required_fields:
                self.assertIn(field, manifest, f"Manifest {mf_path.parent.name} missing field {field}")

            # Chunk count integrity
            self.assertEqual(
                manifest["chunk_count"],
                manifest["unique_chunk_id_count"],
                f"Duplicate chunk IDs indicated in manifest {mf_path.parent.name}!",
            )
            self.assertGreater(manifest["chunk_count"], 0)
            self.assertGreater(manifest["total_physical_pages"], 0)
            self.assertEqual(len(manifest["file_sha256"]), 64)
            self.assertEqual(len(manifest["chunks_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()

