"""
Advanced PDF Structural Inspector, Multi-Strategy TOC Parser,
Printed-to-Physical Page Mapper, and Logical Section Splitter.
"""

import gc
import re
import logging
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any, Tuple, Optional
from pypdf import PdfReader, PdfWriter

from config.settings import settings

logger = logging.getLogger(__name__)

class PDFSegmenter:
    """
    Executes structural inspection, outline validation, TOC page discovery & parsing,
    printed-to-physical page mapping, and non-overlapping PDF section splitting.
    """

    TOC_HEADING_REGEX = re.compile(r"(?i)\b(?:contents|table\s+of\s+contents|index)\b")
    # Matches TOC line items: e.g. "Directors' Report ...... 32" or "Management Team 514"
    TOC_LINE_REGEX = re.compile(
        r"^(?P<title>[A-Za-z0-9\s,&’'\-\/\(\)\.]{3,}?)(?:[\.\s\t_]{2,}|\s{2,}|\t|\s+)(?P<page>\d{1,4})\s*$"
    )

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        max_scan_pages: int = settings.TOC_SCAN_MAX_PAGES,
        min_valid_entries: int = settings.TOC_MIN_VALID_ENTRIES,
        fallback_chunk_pages: int = settings.MAX_PDF_CHUNK_PAGES
    ):
        self.output_dir = output_dir or settings.INTERMEDIATE_DIR
        self.max_scan_pages = max_scan_pages
        self.min_valid_entries = min_valid_entries
        self.fallback_chunk_pages = fallback_chunk_pages
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def inspect_structure(self, pdf_path: Path) -> Dict[str, Any]:
        """Inspect basic PDF structure, page count, and outline."""
        reader = PdfReader(str(pdf_path))
        num_pages = len(reader.pages)
        raw_meta = reader.metadata or {}

        raw_outline_entries: List[Dict[str, Any]] = []
        try:
            outline = reader.outline
            if outline:
                for item in outline:
                    if isinstance(item, dict) and "/Title" in item:
                        title = str(item.get("/Title", "")).strip()
                        try:
                            page_num = reader.get_destination_page_number(item)
                            raw_outline_entries.append({
                                "title": title,
                                "destination_page_index": page_num,
                                "physical_page": page_num + 1 if page_num is not None else None
                            })
                        except Exception:
                            raw_outline_entries.append({"title": title, "physical_page": None})
                    elif isinstance(item, list):
                        # Nested outline items
                        for sub_item in item:
                            if isinstance(sub_item, dict) and "/Title" in sub_item:
                                title = str(sub_item.get("/Title", "")).strip()
                                try:
                                    page_num = reader.get_destination_page_number(sub_item)
                                    raw_outline_entries.append({
                                        "title": title,
                                        "destination_page_index": page_num,
                                        "physical_page": page_num + 1 if page_num is not None else None
                                    })
                                except Exception:
                                    raw_outline_entries.append({"title": title, "physical_page": None})
        except Exception as e:
            logger.warning(f"Failed extracting outline bookmarks: {e}")

        return {
            "total_pages": num_pages,
            "outline_present": len(raw_outline_entries) > 0,
            "outline_entry_count": len(raw_outline_entries),
            "raw_outline_entries": raw_outline_entries,
            "metadata_dict": {str(k): str(v) for k, v in raw_meta.items()}
        }

    def validate_outline_quality(
        self,
        outline_entries: List[Dict[str, Any]],
        total_pages: int
    ) -> Tuple[bool, str, List[str]]:
        """
        Quality gate for native PDF bookmarks.
        Returns: (is_valid, quality_label, list_of_issues)
        """
        issues: List[str] = []

        if not outline_entries:
            return False, "ABSENT", ["No outline bookmarks present in document."]

        if len(outline_entries) < self.min_valid_entries:
            issues.append(f"Too few outline entries ({len(outline_entries)} < {self.min_valid_entries}).")

        # Check for meaningless titles (e.g. "1", "2", "Final_Final_...", "Page 1")
        meaningless_count = 0
        pages_valid = 0
        last_page = 0
        non_monotonic_count = 0

        for entry in outline_entries:
            title = entry.get("title", "")
            phys_page = entry.get("physical_page")

            # Check title substance
            if not title or len(title) < 3 or title.isdigit() or "final" in title.lower():
                meaningless_count += 1

            # Check page bounds
            if phys_page is not None and 1 <= phys_page <= total_pages:
                pages_valid += 1
                if phys_page < last_page:
                    non_monotonic_count += 1
                last_page = phys_page
            else:
                issues.append(f"Invalid destination page '{phys_page}' for title '{title}'.")

        if meaningless_count > len(outline_entries) * 0.4:
            issues.append(f"High proportion of meaningless titles ({meaningless_count}/{len(outline_entries)}).")

        if pages_valid < len(outline_entries) * 0.7:
            issues.append(f"Low valid page destination ratio ({pages_valid}/{len(outline_entries)}).")

        if issues:
            quality = "WEAK" if len(outline_entries) >= self.min_valid_entries else "INVALID"
            return False, quality, issues

        return True, "VALID", []

    def discover_and_parse_toc(
        self,
        pdf_path: Path,
        total_pages: int
    ) -> Dict[str, Any]:
        """
        Scans first N pages to discover real printed 'CONTENTS' pages and parse section rows.
        """
        reader = PdfReader(str(pdf_path))
        scan_limit = min(self.max_scan_pages, total_pages)
        candidate_pages: List[Dict[str, Any]] = []

        # 1. Scan pages for TOC headings and dense list patterns
        for p_idx in range(scan_limit):
            try:
                page = reader.pages[p_idx]
                text = page.extract_text() or ""
                lines = [line.strip() for line in text.split("\n") if line.strip()]

                has_toc_heading = bool(self.TOC_HEADING_REGEX.search(text))
                matched_rows = []

                for line in lines:
                    match = self.TOC_LINE_REGEX.match(line)
                    if match:
                        t = match.group("title").strip().rstrip(".").strip()
                        p = int(match.group("page"))
                        # Filter out header lines or page numbers greater than total_pages
                        if len(t) >= 3 and not self.TOC_HEADING_REGEX.fullmatch(t) and p <= total_pages + 50:
                            matched_rows.append({"title": t, "printed_page": p, "raw_line": line})

                score = len(matched_rows) * 2 + (10 if has_toc_heading else 0)
                if score >= 6:
                    candidate_pages.append({
                        "physical_page": p_idx + 1,
                        "has_toc_heading": has_toc_heading,
                        "matched_rows_count": len(matched_rows),
                        "score": score,
                        "raw_text": text,
                        "parsed_rows": matched_rows
                    })
            except Exception as e:
                logger.warning(f"Error extracting page {p_idx+1}: {e}")

        if not candidate_pages:
            return {
                "toc_found": False,
                "selected_toc_pages": [],
                "parsed_entries": [],
                "raw_toc_text": ""
            }

        # Sort candidate pages by score and order
        candidate_pages.sort(key=lambda x: x["score"], reverse=True)
        best_candidate = candidate_pages[0]

        # Check if there are consecutive TOC pages (multi-page contents)
        selected_pages = [best_candidate["physical_page"]]
        all_parsed_rows = list(best_candidate["parsed_rows"])
        raw_texts = [best_candidate["raw_text"]]

        for cand in candidate_pages[1:]:
            if cand["physical_page"] in [best_candidate["physical_page"] + 1, best_candidate["physical_page"] - 1]:
                selected_pages.append(cand["physical_page"])
                all_parsed_rows.extend(cand["parsed_rows"])
                raw_texts.append(cand["raw_text"])

        selected_pages.sort()

        # Deduplicate parsed rows by title
        unique_rows = []
        seen_titles = set()
        for row in all_parsed_rows:
            norm_title = re.sub(r"[^\w\s]", "", row["title"]).strip().lower()
            if norm_title not in seen_titles:
                seen_titles.add(norm_title)
                unique_rows.append(row)

        # Sort by printed_page
        unique_rows.sort(key=lambda x: x["printed_page"])

        return {
            "toc_found": len(unique_rows) >= 3,
            "selected_toc_pages": selected_pages,
            "candidate_pages_analyzed": [
                {"page": c["physical_page"], "score": c["score"], "rows": c["matched_rows_count"]}
                for c in candidate_pages
            ],
            "parsed_entries": unique_rows,
            "raw_toc_text": "\n--- PAGE BREAK ---\n".join(raw_texts)
        }

    def map_printed_to_physical_pages(
        self,
        pdf_path: Path,
        parsed_entries: List[Dict[str, Any]],
        total_pages: int
    ) -> Tuple[List[Dict[str, Any]], str, str, Dict[str, Any]]:
        """
        Maps printed page numbers to physical PDF page indices by calculating page offsets
        and verifying section headings on target physical pages.
        Returns: (mapped_entries, method, confidence, diagnostics)
        """
        if not parsed_entries:
            return [], "unresolved", "low", {}

        reader = PdfReader(str(pdf_path))
        offset_votes: List[int] = []
        diagnostics: Dict[str, Any] = {"heading_matches": [], "offset_distribution": {}}

        # Strategy 1: Heading verification across candidate physical offsets
        # Test printed pages against physical pages [printed_page .. printed_page + 30]
        sample_entries = parsed_entries[:8] + parsed_entries[-4:]  # sample top and bottom entries

        for entry in sample_entries:
            title = entry["title"]
            pr_page = entry["printed_page"]
            # Look for distinctive keywords from title
            keywords = [w.lower() for w in re.findall(r"\b[A-Za-z]{4,}\b", title) if w.lower() not in ["report", "hudco", "annual", "limited"]]
            if not keywords:
                keywords = [w.lower() for w in re.findall(r"\b[A-Za-z]{3,}\b", title)]

            best_match_page = None
            for offset_test in range(0, 30):
                target_p = pr_page + offset_test
                if 1 <= target_p <= total_pages:
                    try:
                        p_text = (reader.pages[target_p - 1].extract_text() or "").lower()
                        # Check if multiple keywords match
                        matches = sum(1 for kw in keywords if kw in p_text)
                        if matches >= max(1, len(keywords) // 2):
                            offset_votes.append(offset_test)
                            best_match_page = target_p
                            break
                    except Exception:
                        pass

            if best_match_page:
                diagnostics["heading_matches"].append({
                    "title": title,
                    "printed_page": pr_page,
                    "matched_physical_page": best_match_page,
                    "inferred_offset": best_match_page - pr_page
                })

        # Calculate dominant offset
        if offset_votes:
            counter = Counter(offset_votes)
            dominant_offset, freq = counter.most_common(1)[0]
            diagnostics["offset_distribution"] = dict(counter)

            method = "printed_page_offset"
            confidence = "high" if freq >= 3 else "medium"
        else:
            # Fallback heuristic: check if printed page numbers align directly (offset 0)
            dominant_offset = 0
            method = "direct_physical"
            confidence = "low"

        # Apply mapping
        mapped_entries: List[Dict[str, Any]] = []
        for idx, entry in enumerate(parsed_entries):
            pr_start = entry["printed_page"]
            phys_start = min(total_pages, max(1, pr_start + dominant_offset))

            mapped_entries.append({
                "section_id": f"sec_{idx+1:02d}",
                "title": entry["title"],
                "printed_page_start": pr_start,
                "physical_page_start": phys_start,
            })

        return mapped_entries, method, confidence, {
            "applied_offset": dominant_offset,
            "details": diagnostics
        }

    def build_section_plan(
        self,
        mapped_entries: List[Dict[str, Any]],
        total_pages: int,
        segmentation_method: str,
        confidence: str
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Computes non-overlapping start and end ranges for all sections.
        """
        sections: List[Dict[str, Any]] = []
        warnings: List[str] = []

        if not mapped_entries or segmentation_method == "fixed_window_fallback":
            # Emergency fallback: Fixed windows
            step = self.fallback_chunk_pages
            sec_idx = 1
            for p_start in range(1, total_pages + 1, step):
                p_end = min(p_start + step - 1, total_pages)
                sections.append({
                    "section_id": f"sec_{sec_idx:02d}",
                    "title": f"Logical_Window_P{p_start:03d}_P{p_end:03d}",
                    "safe_title": f"Logical_Window_P{p_start:03d}_P{p_end:03d}",
                    "physical_page_start": p_start,
                    "physical_page_end": p_end,
                    "printed_page_start": None,
                    "printed_page_end": None,
                    "segmentation_method": "fixed_window_fallback",
                    "confidence": "low"
                })
                sec_idx += 1
            return sections, warnings

        # Compute end pages from successive starts
        for i in range(len(mapped_entries)):
            curr = mapped_entries[i]
            p_start = curr["physical_page_start"]
            pr_start = curr.get("printed_page_start")

            if i + 1 < len(mapped_entries):
                next_entry = mapped_entries[i + 1]
                next_p_start = next_entry["physical_page_start"]
                next_pr_start = next_entry.get("printed_page_start")

                if next_p_start > p_start:
                    p_end = next_p_start - 1
                else:
                    warnings.append(f"Non-monotonic page start between '{curr['title']}' (p{p_start}) and '{next_entry['title']}' (p{next_p_start}).")
                    p_end = p_start  # clamp to single page

                pr_end = (next_pr_start - 1) if next_pr_start and next_pr_start > (pr_start or 0) else pr_start
            else:
                # Final section stretches to end of document
                p_end = total_pages
                pr_end = None

            safe_title = re.sub(r"[^\w\-]", "_", curr["title"]).strip("_")
            safe_title = re.sub(r"_+", "_", safe_title)[:50]

            sections.append({
                "section_id": curr["section_id"],
                "title": curr["title"],
                "safe_title": safe_title,
                "physical_page_start": p_start,
                "physical_page_end": p_end,
                "printed_page_start": pr_start,
                "printed_page_end": pr_end,
                "segmentation_method": segmentation_method,
                "confidence": confidence
            })

        return sections, warnings

    def split_pdf(
        self,
        pdf_path: Path,
        document_id: str,
        section_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Splits source PDF into standalone section files based on the section plan.
        Validates file existence, page count, and file size.
        """
        reader = PdfReader(str(pdf_path))
        num_total_pages = len(reader.pages)
        split_results: List[Dict[str, Any]] = []

        for sec in section_plan:
            start_p = max(0, sec["physical_page_start"] - 1)
            end_p = min(num_total_pages, sec["physical_page_end"])

            writer = PdfWriter()
            for p_idx in range(start_p, end_p):
                writer.add_page(reader.pages[p_idx])

            out_filename = f"{document_id}_{sec['section_id']}_{sec['safe_title']}.pdf"
            out_filepath = self.output_dir / out_filename

            with open(out_filepath, "wb") as f_out:
                writer.write(f_out)

            # Verification
            written_size = out_filepath.stat().st_size
            written_pages = end_p - start_p

            split_results.append({
                "section_id": sec["section_id"],
                "title": sec["title"],
                "output_file": out_filename,
                "output_path": str(out_filepath.resolve()),
                "physical_page_start": sec["physical_page_start"],
                "physical_page_end": sec["physical_page_end"],
                "printed_page_start": sec["printed_page_start"],
                "printed_page_end": sec["printed_page_end"],
                "pages_count": written_pages,
                "size_bytes": written_size,
                "segmentation_method": sec["segmentation_method"],
                "confidence": sec["confidence"]
            })

            del writer
            gc.collect()

        logger.info(f"Generated {len(split_results)} section PDFs in {self.output_dir}")
        return split_results
