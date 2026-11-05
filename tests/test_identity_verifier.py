"""
Comprehensive Unit Tests for DocumentIdentityVerifier Gate.
File: tests/test_identity_verifier.py

Covers all 7 mandatory regression scenarios specified in Prompt 1:
1. Equivalent fiscal-year formats (e.g. 2023-24 and 2023-2024).
2. Same-start-year but different-end-year mismatches (e.g. 2023-24 vs 2023-25).
3. Conflicting report-year evidence (e.g. expected 2023-24, detected 2020-21).
4. Missing or insufficient identity evidence (no year in front matter).
5. Incorrect report-number evidence (expected 54th, detected 51st).
6. A valid identity-verification case (HUDCO 54th Annual Report 2023-24).
7. A PDF that contains unrelated HUDCO references but is not an annual report.
"""

import unittest
from pipeline.adapters.base import RawExtractionPayload, RawPageRecord
from pipeline.core.contracts import DocumentFormat, IdentityVerificationStatus
from pipeline.stage_1_ingestion.identity_verifier import (
    DocumentIdentityVerifier,
    parse_fiscal_year_interval,
    format_canonical_fiscal_year,
)


class TestIdentityVerifier(unittest.TestCase):
    def _create_payload(self, text_pages, filename="ar24.pdf", total_pages=50):
        pages = [
            RawPageRecord(physical_page=i + 1, printed_page=str(i + 1), text=t, blocks=[])
            for i, t in enumerate(text_pages)
        ]
        if len(pages) < total_pages:
            pages += [
                RawPageRecord(physical_page=i + 1, printed_page=str(i + 1), text="Regular narrative content", blocks=[])
                for i in range(len(pages), total_pages)
            ]
        return RawExtractionPayload(
            source_filename=filename,
            document_format=DocumentFormat.PDF,
            total_physical_pages=total_pages,
            pages=pages,
        )

    def test_case_1_equivalent_fiscal_year_formats(self):
        """1. Equivalent fiscal-year formats (2023-24 and 2023-2024) must match as the same interval."""
        self.assertEqual(parse_fiscal_year_interval("2023-24"), (2023, 2024))
        self.assertEqual(parse_fiscal_year_interval("2023-2024"), (2023, 2024))
        self.assertEqual(parse_fiscal_year_interval("2023 - 24"), (2023, 2024))
        self.assertEqual(parse_fiscal_year_interval("2023–2024"), (2023, 2024))

        payload = self._create_payload([
            "Housing and Urban Development Corporation Limited\n54th Annual Report 2023-2024\nBoard of Directors",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.VERIFIED)
        self.assertEqual(res.detected_fiscal_year, "2023-24")
        self.assertEqual(res.confidence, "HIGH")

    def test_case_2_same_start_year_different_end_year_mismatch(self):
        """2. Same-start-year but different-end-year (2023-24 vs 2023-25) must NEVER match."""
        iv_expected = parse_fiscal_year_interval("2023-24")
        iv_detected = parse_fiscal_year_interval("2023-25")
        self.assertNotEqual(iv_expected, iv_detected)
        self.assertEqual(iv_detected, (2023, 2025))

        payload = self._create_payload([
            "HUDCO Annual Report 2023-25\nCorporate Overview",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.MISMATCH)
        self.assertIn("conflict with expected interval", res.discrepancy_reason)

    def test_case_3_conflicting_report_year_evidence(self):
        """3. Conflicting report-year evidence (expected 2023-24, document contains 2020-21)."""
        payload = self._create_payload([
            "HUDCO Housing and Urban Development Corporation\nAnnual Report 2020-21",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.MISMATCH)
        self.assertIn("conflict with expected interval", res.discrepancy_reason)

    def test_case_4_missing_or_insufficient_identity_evidence(self):
        """4. Missing or insufficient identity evidence (HUDCO Annual Report, but no FY anywhere)."""
        payload = self._create_payload([
            "Housing and Urban Development Corporation Limited\nAnnual Report\nTable of Contents",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.AMBIGUOUS)
        self.assertIn("No fiscal year evidence found", res.discrepancy_reason)

    def test_case_5_incorrect_report_number_evidence(self):
        """5. Incorrect report-number evidence (expected 54th, document claims 51st)."""
        payload = self._create_payload([
            "HUDCO 51st Annual Report 2023-24\nDirectors Report",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.MISMATCH)
        self.assertIn("Detected report number '51' conflicts with expected report number '54'", res.discrepancy_reason)

    def test_case_6_valid_identity_verification(self):
        """6. A valid identity-verification case (HUDCO 54th Annual Report 2023-24)."""
        payload = self._create_payload([
            "Housing and Urban Development Corporation Limited\n54th Annual Report 2023-24",
            "Notice of Annual General Meeting",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.VERIFIED)
        self.assertEqual(res.detected_fiscal_year, "2023-24")
        self.assertEqual(res.detected_report_number, 54)
        self.assertEqual(res.confidence, "HIGH")

    def test_case_7_unrelated_hudco_document_not_annual_report(self):
        """7. A PDF containing unrelated HUDCO references but not an annual report."""
        payload = self._create_payload([
            "Reserve Bank of India Master Direction on NBFCs\n"
            "Housing and Urban Development Corporation Limited (HUDCO) is recognized as a public financial institution.\n"
            "Capital adequacy requirements apply to all infrastructure financing companies.",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.MISMATCH)
        self.assertIn("'Annual Report' keyword", res.discrepancy_reason)

    def test_case_8_missing_expected_report_number_evidence(self):
        """8. Report number expected (54th for ar24), but document only has FY without ordinal."""
        payload = self._create_payload([
            "Housing and Urban Development Corporation Limited\nAnnual Report 2023-24\nBoard of Directors",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.AMBIGUOUS)
        self.assertIsNone(res.detected_report_number)
        self.assertIn("Expected report number '54' is not evidenced", res.discrepancy_reason)

    def test_case_9_contradictory_primary_annual_report_title_year(self):
        """9. Contradictory primary annual report title year (Title says 2022-23 while target is 2023-24)."""
        payload = self._create_payload([
            "HUDCO Housing and Urban Development Corporation\nAnnual Report 2022-23\n"
            "On page 12: In 2023-24, projected disbursement is estimated at Rs. 10,000 crore.",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.MISMATCH)
        self.assertIn("conflict with expected interval", res.discrepancy_reason)

    def test_case_10_multiple_conflicting_annual_report_titles(self):
        """10. Front matter contains multiple conflicting annual report declarations."""
        payload = self._create_payload([
            "HUDCO Annual Report 2023-24\n"
            "Annexure: Special Edition Annual Report 2021-22 Combined Document",
        ])
        res = DocumentIdentityVerifier.verify(payload, "ar24.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.AMBIGUOUS)
        self.assertIn("Multiple conflicting annual report title fiscal years", res.discrepancy_reason)

    def test_case_11_observed_evidence_not_inferred_from_filename(self):
        """11. Report number must never be inferred from expected filename and returned as observed evidence."""
        # Custom filename without standard arNN mapping
        payload = self._create_payload([
            "HUDCO Housing and Urban Development Corporation\nAnnual Report 2023-24\nNotice",
        ], filename="custom_report.pdf")
        res = DocumentIdentityVerifier.verify(payload, "custom_report.pdf", expected_fy="2023-24")
        self.assertEqual(res.status, IdentityVerificationStatus.VERIFIED)
        self.assertIsNone(res.detected_report_number)
        self.assertEqual(res.detected_fiscal_year, "2023-24")


if __name__ == "__main__":
    unittest.main()

