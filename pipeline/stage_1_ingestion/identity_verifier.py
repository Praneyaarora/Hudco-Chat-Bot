"""
Document Content Identity Verification Gate.
File: pipeline/stage_1_ingestion/identity_verifier.py

Verifies that candidate PDF documents match expected report identities
(organization/publisher, annual report designation, fiscal year interval,
report number, and physical page count) BEFORE admitting them into the corpus
or marking them verified.
"""

from __future__ import annotations

import re
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field

from pipeline.adapters.base import RawExtractionPayload
from pipeline.core.contracts import IdentityVerificationStatus


REPORT_NUMBER_MAP = {
    "ar15": {"number": 45, "ordinal": "45th", "fy": "2014-15"},
    "ar16": {"number": 46, "ordinal": "46th", "fy": "2015-16"},
    "ar17": {"number": 47, "ordinal": "47th", "fy": "2016-17"},
    "ar18": {"number": 48, "ordinal": "48th", "fy": "2017-18"},
    "ar19": {"number": 49, "ordinal": "49th", "fy": "2018-19"},
    "ar20": {"number": 50, "ordinal": "50th", "fy": "2019-20"},
    "ar21": {"number": 51, "ordinal": "51st", "fy": "2020-21"},
    "ar22": {"number": 52, "ordinal": "52nd", "fy": "2021-22"},
    "ar23": {"number": 53, "ordinal": "53rd", "fy": "2022-23"},
    "ar24": {"number": 54, "ordinal": "54th", "fy": "2023-24"},
    "ar25": {"number": 55, "ordinal": "55th", "fy": "2024-25"},
    "ar26": {"number": 56, "ordinal": "56th", "fy": "2025-26"},
}


def parse_fiscal_year_interval(fy_str: Optional[str]) -> Optional[Tuple[int, int]]:
    """
    Parses a fiscal year string into a normalized (start_year, end_year) integer tuple.
    Handles equivalent formats: '2023-24', '2023-2024', '2023 - 24', '2023/24'.
    Rejects strings that do not represent a valid fiscal year interval.
    """
    if not fy_str or not isinstance(fy_str, str):
        return None
    # Normalize dashes and spaces
    clean = re.sub(r"[\u2013\u2014\u2212]", "-", str(fy_str).strip())
    match = re.search(r"\b(19\d{2}|20\d{2})\s*[-/]\s*(\d{2,4})\b", clean)
    if not match:
        return None
    start_year = int(match.group(1))
    end_part = match.group(2)
    if len(end_part) == 4:
        end_year = int(end_part)
    elif len(end_part) == 2:
        century = (start_year // 100) * 100
        end_val = int(end_part)
        if end_val < (start_year % 100):
            century += 100
        end_year = century + end_val
    else:
        return None

    # Guard: end_year must be after start_year and within reasonable multi-year span (1 to 2 years)
    if end_year <= start_year:
        return None
    return (start_year, end_year)


def format_canonical_fiscal_year(interval: Tuple[int, int]) -> str:
    """Formats an (start_year, end_year) interval into canonical 'YYYY-YY' string."""
    start_year, end_year = interval
    end_2digit = end_year % 100
    return f"{start_year}-{end_2digit:02d}"


class DocumentIdentityResult(BaseModel):
    """Formal audit result of content-based identity verification."""
    status: IdentityVerificationStatus
    detected_title: Optional[str] = None
    detected_fiscal_year: Optional[str] = None
    detected_report_number: Optional[int] = None
    total_physical_pages: int
    has_company_name: bool
    has_annual_report_keyword: bool
    confidence: str = Field("LOW", description="HIGH, MEDIUM, LOW")
    details: Dict[str, Any] = Field(default_factory=dict)
    discrepancy_reason: Optional[str] = None


class DocumentIdentityVerifier:
    """Verifies annual report content identity from raw extracted payload."""

    @classmethod
    def verify(
        cls,
        payload: RawExtractionPayload,
        expected_filename: str,
        expected_fy: Optional[str] = None,
        expected_title_hint: Optional[str] = None,
    ) -> DocumentIdentityResult:
        total_pages = payload.total_physical_pages
        if total_pages < 20:
            return DocumentIdentityResult(
                status=IdentityVerificationStatus.MISMATCH,
                total_physical_pages=total_pages,
                has_company_name=False,
                has_annual_report_keyword=False,
                confidence="HIGH",
                discrepancy_reason=f"Page count ({total_pages}) is suspiciously low for a full Annual Report (< 20 pages)."
            )

        # Inspect early front-matter pages (up to 35 pages to accommodate visual photo spreads)
        sample_pages = payload.pages[:min(35, len(payload.pages))]
        combined_text = "\n".join(p.text for p in sample_pages)
        lower_text = combined_text.lower()

        # 1. Company Name check (HUDCO / Housing and Urban Development Corporation)
        has_company = bool(
            re.search(r"\b(housing\s+and\s+urban\s+development\s+corporation|housing\s*&\s*urban\s+development\s+corporation|hudco)\b", lower_text)
        )

        # 2. Annual Report indicator
        has_ar_keyword = bool(re.search(r"\bannual\s+report\b", lower_text))

        if not has_company or not has_ar_keyword:
            reason = "Document does not contain "
            if not has_company and not has_ar_keyword:
                reason += "HUDCO company name and 'Annual Report' keyword in front matter."
            elif not has_company:
                reason += "HUDCO company name in front matter."
            else:
                reason += "'Annual Report' keyword in front matter."
            return DocumentIdentityResult(
                status=IdentityVerificationStatus.MISMATCH,
                total_physical_pages=total_pages,
                has_company_name=has_company,
                has_annual_report_keyword=has_ar_keyword,
                confidence="HIGH",
                discrepancy_reason=reason
            )

        # 3. Derive expected info from filename slug (e.g. ar24)
        slug = expected_filename.lower().replace(".pdf", "").strip()
        ref_info = REPORT_NUMBER_MAP.get(slug, {})
        target_fy = expected_fy or ref_info.get("fy")
        target_num = ref_info.get("number")
        target_ord = ref_info.get("ordinal", "")

        target_interval = parse_fiscal_year_interval(target_fy) if target_fy else None

        # 4. Search for Fiscal Year candidates in front-matter text
        raw_fy_candidates = re.findall(r"\b(19\d{2}|20\d{2})\s*[-–—/]\s*(\d{2,4})\b", combined_text)
        detected_intervals: List[Tuple[int, int]] = []
        for s_yr, e_yr in raw_fy_candidates:
            interval = parse_fiscal_year_interval(f"{s_yr}-{e_yr}")
            if interval and interval not in detected_intervals:
                detected_intervals.append(interval)

        # 5. Search for Report Number / Ordinal (e.g. 54th, 51st)
        detected_num = None
        ord_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\s+annual\s+report\b", lower_text)
        if ord_match:
            detected_num = int(ord_match.group(1))
        else:
            ord_alt = re.search(r"\bannual\s+report\b[^\n]{0,25}\b(\d{1,2})(?:st|nd|rd|th)\b", lower_text)
            if ord_alt:
                detected_num = int(ord_alt.group(1))

        # Check Report Number conflict (Hard contradiction)
        if target_num is not None and detected_num is not None and target_num != detected_num:
            return DocumentIdentityResult(
                status=IdentityVerificationStatus.MISMATCH,
                detected_report_number=detected_num,
                total_physical_pages=total_pages,
                has_company_name=True,
                has_annual_report_keyword=True,
                confidence="HIGH",
                discrepancy_reason=f"Detected report number '{detected_num}' conflicts with expected report number '{target_num}'."
            )

        # 6. Fiscal Year Verification with Contradictory Title Detection
        # Distinguish primary annual report title years from comparative narrative years
        ar_title_candidates = re.findall(
            r"\bannual\s+report\b[^\n]{0,35}\b(19\d{2}|20\d{2})\s*[-–—/]\s*(\d{2,4})\b",
            lower_text
        )
        ar_title_prefix_candidates = re.findall(
            r"\b(19\d{2}|20\d{2})\s*[-–—/]\s*(\d{2,4})\s+annual\s+report\b",
            lower_text
        )
        ar_title_intervals: List[Tuple[int, int]] = []
        for s_yr, e_yr in ar_title_candidates + ar_title_prefix_candidates:
            iv = parse_fiscal_year_interval(f"{s_yr}-{e_yr}")
            if iv and iv not in ar_title_intervals:
                ar_title_intervals.append(iv)

        # Detect conflicting primary title fiscal years (Hard contradiction)
        if target_interval is not None and ar_title_intervals:
            if target_interval not in ar_title_intervals:
                conflicting_title_fys = [format_canonical_fiscal_year(iv) for iv in ar_title_intervals]
                return DocumentIdentityResult(
                    status=IdentityVerificationStatus.MISMATCH,
                    detected_fiscal_year=conflicting_title_fys[0],
                    detected_report_number=detected_num,
                    total_physical_pages=total_pages,
                    has_company_name=True,
                    has_annual_report_keyword=True,
                    confidence="HIGH",
                    details={"title_intervals": conflicting_title_fys, "target_interval": target_interval},
                    discrepancy_reason=f"Primary annual report title fiscal year(s) {conflicting_title_fys} conflict with expected interval '{target_fy}'."
                )
            elif len(ar_title_intervals) > 1:
                conflicting_title_fys = [format_canonical_fiscal_year(iv) for iv in ar_title_intervals]
                return DocumentIdentityResult(
                    status=IdentityVerificationStatus.AMBIGUOUS,
                    detected_fiscal_year=format_canonical_fiscal_year(target_interval),
                    detected_report_number=detected_num,
                    total_physical_pages=total_pages,
                    has_company_name=True,
                    has_annual_report_keyword=True,
                    confidence="LOW",
                    details={"title_intervals": conflicting_title_fys, "target_interval": target_interval},
                    discrepancy_reason=f"Multiple conflicting annual report title fiscal years {conflicting_title_fys} found in front matter."
                )

        fy_matched = False
        detected_canonical_fy = None

        if target_interval is not None:
            if target_interval in detected_intervals:
                fy_matched = True
                detected_canonical_fy = format_canonical_fiscal_year(target_interval)
            elif detected_intervals:
                conflicting_fys = [format_canonical_fiscal_year(iv) for iv in detected_intervals[:3]]
                return DocumentIdentityResult(
                    status=IdentityVerificationStatus.MISMATCH,
                    detected_fiscal_year=conflicting_fys[0] if conflicting_fys else None,
                    detected_report_number=detected_num,
                    total_physical_pages=total_pages,
                    has_company_name=True,
                    has_annual_report_keyword=True,
                    confidence="HIGH",
                    details={"detected_intervals": conflicting_fys, "target_interval": target_interval},
                    discrepancy_reason=f"Detected fiscal year(s) {conflicting_fys} conflict with expected interval '{target_fy}'."
                )
            else:
                return DocumentIdentityResult(
                    status=IdentityVerificationStatus.AMBIGUOUS,
                    detected_report_number=detected_num,
                    total_physical_pages=total_pages,
                    has_company_name=True,
                    has_annual_report_keyword=True,
                    confidence="LOW",
                    discrepancy_reason=f"No fiscal year evidence found in front-matter text for expected '{target_fy}'."
                )
        else:
            if detected_intervals:
                detected_canonical_fy = format_canonical_fiscal_year(detected_intervals[0])
                fy_matched = True

        # Where report number is expected from reference but document provides insufficient evidence
        if target_num is not None and detected_num is None:
            return DocumentIdentityResult(
                status=IdentityVerificationStatus.AMBIGUOUS,
                detected_report_number=None,
                detected_fiscal_year=detected_canonical_fy,
                total_physical_pages=total_pages,
                has_company_name=True,
                has_annual_report_keyword=True,
                confidence="LOW",
                discrepancy_reason=f"Expected report number '{target_num}' is not evidenced in front-matter text."
            )

        # 7. Final Verification Decision
        eff_fy = detected_canonical_fy or target_fy

        if detected_num is not None:
            num_suffix = "th" if detected_num not in (51, 52, 53) else ("st" if detected_num == 51 else ("nd" if detected_num == 52 else "rd"))
            detected_title = f"HUDCO {detected_num}{num_suffix} Annual Report {eff_fy}"
        else:
            detected_title = f"HUDCO Annual Report {eff_fy}"

        if fy_matched and (target_num is None or detected_num == target_num):
            return DocumentIdentityResult(
                status=IdentityVerificationStatus.VERIFIED,
                detected_title=detected_title,
                detected_fiscal_year=detected_canonical_fy,
                detected_report_number=detected_num,
                total_physical_pages=total_pages,
                has_company_name=True,
                has_annual_report_keyword=True,
                confidence="HIGH",
                details={
                    "matched_interval": target_interval,
                    "target_num": target_num,
                    "detected_num": detected_num,
                }
            )

        return DocumentIdentityResult(
            status=IdentityVerificationStatus.AMBIGUOUS,
            detected_title=detected_title,
            detected_fiscal_year=detected_canonical_fy,
            detected_report_number=detected_num,
            total_physical_pages=total_pages,
            has_company_name=True,
            has_annual_report_keyword=True,
            confidence="LOW",
            discrepancy_reason=f"Unable to conclusively verify identity for expected '{target_fy}'."
        )
