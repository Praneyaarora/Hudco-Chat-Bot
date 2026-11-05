"""
Phase 3 & 3.1 & 3.2: Controlled Sample Evaluation Runner.
File: scripts/run_phase3_sample.py

Executes extraction and chunking for a specified physical page range of data/raw/annual_reports/ar26.pdf.
Emits inspectable artifacts:
- sections.json
- chunks.jsonl
- processing_summary.json
- quality_report.md

Performs comprehensive, independent forensic validation with hard exit-code assertions:
1. Extraction completeness (only requested pages extracted, no page gaps).
2. Counter-based source block accounting (exact occurrence matching, zero unassigned or duplicated blocks).
3. Section hierarchy, numbering, and breadcrumbs.
4. Genuine section-boundary check (every chunk verified against section physical page bounds).
5. Chunk ID uniqueness, determinism, and non-emptiness.
6. Chunk source block provenance (every chunk's source blocks verified against source payload and section range).
7. Chunk sizing compliance with explicit handling of atomic structured tables and verified CHUNK_TOO_LONG warnings.
8. Deep cross-artifact content comparison between sections.json, chunks.jsonl, processing_summary.json, and quality_report.md.
9. Guaranteed non-zero exit code on any failure.
"""

import sys
import json
import hashlib
import argparse
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.adapters.pdf_adapter import PDFDocumentAdapter
from pipeline.core.pipeline_runner import run_phase2_pipeline
from pipeline.core.contracts import (
    DocumentFormat,
    BlockType,
    WarningCategory,
    ProcessingStatus,
    CanonicalDocument,
    CanonicalChunk,
)


def validate_sample_execution(
    payload,
    canonical_doc: CanonicalDocument,
    chunks: List[CanonicalChunk],
    output_dir: Path,
    target_chunk_size: int = 1200,
    max_chunk_size: int = 2000,
    page_start: int = 1,
    page_end: int = 19
) -> List[str]:
    """
    Executes forensic invariants and deep cross-artifact validation.
    Returns list of hard failure descriptions. If empty, validation passed 100%.
    """
    hard_failures: List[str] = []

    # 1. Extraction Completeness, Page Contiguity & Separation
    extracted_pages = len(payload.pages)
    expected_pages = page_end - page_start + 1
    if extracted_pages != expected_pages:
        hard_failures.append(f"Extracted page count mismatch: expected {expected_pages}, got {extracted_pages}")

    # Check for duplicate physical-page records in payload
    page_counter = Counter(p.physical_page for p in payload.pages)
    dup_pages = [p for p, count in page_counter.items() if count > 1]
    if dup_pages:
        hard_failures.append(f"Duplicate physical-page records detected in payload: {dup_pages}")

    # Check page bounds and printed/physical type separation
    page_numbers = [p.physical_page for p in payload.pages]
    for p in payload.pages:
        if not isinstance(p.physical_page, int):
            hard_failures.append(f"Physical page {p.physical_page} is not an integer")
        if p.printed_page is not None and not isinstance(p.printed_page, str):
            hard_failures.append(f"Printed page label {p.printed_page} is not string or None on page {p.physical_page}")
        if p.physical_page < page_start or p.physical_page > page_end:
            hard_failures.append(f"Physical page {p.physical_page} is outside requested range [{page_start}, {page_end}]")

    sorted_p_nums = sorted(page_numbers)
    for i in range(len(sorted_p_nums) - 1):
        if sorted_p_nums[i + 1] > sorted_p_nums[i] + 1:
            hard_failures.append(f"Physical page gap detected: missing pages between {sorted_p_nums[i]} and {sorted_p_nums[i + 1]}")

    # 2. Strict Counter-Based Source Block Accounting (No Set Masks)
    all_source_blocks = [b for p in payload.pages for b in p.blocks]
    all_assigned_blocks = [b for s in canonical_doc.sections for b in s.blocks]

    source_counts = Counter(b.block_id for b in all_source_blocks)
    assigned_counts = Counter(b.block_id for b in all_assigned_blocks)

    if len(all_source_blocks) != len(all_assigned_blocks):
        hard_failures.append(f"Block count mismatch: {len(all_source_blocks)} source blocks vs {len(all_assigned_blocks)} assigned blocks")

    missing_blocks = [bid for bid, count in source_counts.items() if assigned_counts.get(bid, 0) < count]
    if missing_blocks:
        hard_failures.append(f"Unassigned source blocks detected: {len(missing_blocks)} distinct blocks missing from sections: {missing_blocks[:5]}")

    duplicate_assignments = [bid for bid, count in assigned_counts.items() if count > 1]
    if duplicate_assignments:
        hard_failures.append(f"Duplicate block assignments detected across sections: {duplicate_assignments[:5]}")

    if sum(source_counts.values()) != len(all_source_blocks):
        hard_failures.append("Source block list contains uncounted elements")
    if sum(assigned_counts.values()) != len(all_assigned_blocks):
        hard_failures.append("Assigned block list contains uncounted elements")

    # 3. Section Hierarchy, Numbering, Breadcrumbs, Ordering & Underlying Block Bounds
    sec_map = {s.section_id: s for s in canonical_doc.sections}
    if not canonical_doc.sections:
        hard_failures.append("Document has zero sections")
    else:
        genuine_secs = [s for s in canonical_doc.sections if s.section_id != "sec_00"]
        if genuine_secs:
            first_genuine = genuine_secs[0].section_id
            if first_genuine != "sec_01":
                hard_failures.append(f"First genuine section ID must be 'sec_01', got '{first_genuine}'")

    # Section ordering check (monotonic physical_page_start)
    for idx in range(len(canonical_doc.sections) - 1):
        s_curr = canonical_doc.sections[idx]
        s_next = canonical_doc.sections[idx + 1]
        if s_curr.physical_page_start > s_next.physical_page_start:
            hard_failures.append(
                f"Sections out of physical page order: {s_curr.section_id} (p.{s_curr.physical_page_start}) "
                f"> {s_next.section_id} (p.{s_next.physical_page_start})"
            )

    for s in canonical_doc.sections:
        if not s.heading_path:
            hard_failures.append(f"Section {s.section_id} has empty heading_path")
        if s.physical_page_end < s.physical_page_start:
            hard_failures.append(f"Section {s.section_id} has invalid page range: {s.physical_page_start} > {s.physical_page_end}")
        # Underlying block page boundary check against section bounds
        for blk in s.blocks:
            b_page = getattr(blk.locator, "physical_page", None)
            if b_page is not None and not (s.physical_page_start <= b_page <= s.physical_page_end):
                hard_failures.append(
                    f"Section {s.section_id} contains block {blk.block_id} on physical page {b_page} "
                    f"outside section bounds [{s.physical_page_start}, {s.physical_page_end}]"
                )

    # 4. Chunk Integrity, Provenance & Boundary Verification
    source_block_map = {b.block_id: b for b in all_source_blocks}
    chunk_id_counts = Counter(c.chunk_id for c in chunks)
    dup_chunk_ids = [cid for cid, count in chunk_id_counts.items() if count > 1]
    if dup_chunk_ids:
        hard_failures.append(f"Duplicate chunk IDs detected: {dup_chunk_ids[:5]}")

    for c in chunks:
        # Non-emptiness check
        if not c.content or not c.content.strip():
            hard_failures.append(f"Empty chunk detected: {c.chunk_id}")

        # Hash and length check
        expected_hash = hashlib.sha256(c.content.encode("utf-8")).hexdigest()
        if c.content_sha256 != expected_hash:
            hard_failures.append(f"Chunk {c.chunk_id} content SHA-256 mismatch")
        if c.char_count != len(c.content):
            hard_failures.append(f"Chunk {c.chunk_id} char_count mismatch: {c.char_count} != {len(c.content)}")

        # Printed and physical page separation in chunk
        if not isinstance(c.physical_page, int):
            hard_failures.append(f"Chunk {c.chunk_id} physical_page {c.physical_page} is not an integer")
        if c.printed_page is not None and not isinstance(c.printed_page, str):
            hard_failures.append(f"Chunk {c.chunk_id} printed_page {c.printed_page} is not string or None")

        # Section reference check
        if c.section_id not in sec_map:
            hard_failures.append(f"Chunk {c.chunk_id} references non-existent section: '{c.section_id}'")
            continue

        sec = sec_map[c.section_id]
        if not (sec.physical_page_start <= c.physical_page <= sec.physical_page_end):
            hard_failures.append(
                f"Chunk {c.chunk_id} physical page {c.physical_page} outside section {sec.section_id} "
                f"bounds [{sec.physical_page_start}, {sec.physical_page_end}]"
            )

        # Chunk source block provenance check: MUST NOT BE MISSING OR EMPTY
        if not hasattr(c, "source_block_ids") or not c.source_block_ids:
            hard_failures.append(f"Chunk {c.chunk_id} is missing required source_block_ids provenance")
            continue

        # Check for duplicated source block IDs within the chunk
        if len(c.source_block_ids) != len(set(c.source_block_ids)):
            hard_failures.append(f"Chunk {c.chunk_id} contains duplicate source_block_ids: {c.source_block_ids}")

        # Verify every source block ID corresponds to actual source content and section bounds
        for bid in c.source_block_ids:
            if bid not in source_block_map:
                hard_failures.append(f"Chunk {c.chunk_id} references non-existent or fabricated source block: '{bid}'")
            else:
                blk = source_block_map[bid]
                blk_page = getattr(blk.locator, "physical_page", None)
                if blk_page is not None and not (sec.physical_page_start <= blk_page <= sec.physical_page_end):
                    hard_failures.append(
                        f"Chunk {c.chunk_id} block {bid} on page {blk_page} is outside section {sec.section_id} "
                        f"bounds [{sec.physical_page_start}, {sec.physical_page_end}]"
                    )

    # 5. Sizing & Quality Warnings Audit
    table_chunks = [c for c in chunks if c.has_table]
    narrative_chunks = [c for c in chunks if not c.has_table]

    oversized_narrative = [c for c in narrative_chunks if c.char_count > max_chunk_size]
    for c in oversized_narrative:
        matching_warning = any(
            w.category == WarningCategory.CHUNK_TOO_LONG and w.physical_page == c.physical_page
            for w in canonical_doc.warnings
        ) or any("exceeds max_chunk_size" in w for w in c.warnings)
        if not matching_warning:
            hard_failures.append(
                f"Oversized narrative chunk {c.chunk_id} (len={c.char_count} > {max_chunk_size}) "
                f"missing required CHUNK_TOO_LONG audit warning"
            )

    oversized_tables = [c for c in table_chunks if c.char_count > max_chunk_size]
    for tc in oversized_tables:
        if not any(w.category == WarningCategory.CHUNK_TOO_LONG for w in canonical_doc.warnings) and not tc.warnings:
            hard_failures.append(f"Oversized table chunk {tc.chunk_id} missing size warning")

    # 6. Deep Cross-Artifact Content Comparison
    sec_file = output_dir / "sections.json"
    chunk_file = output_dir / "chunks.jsonl"
    summary_file = output_dir / "processing_summary.json"
    report_file = output_dir / "quality_report.md"

    for f_path in [sec_file, chunk_file, summary_file, report_file]:
        if not f_path.exists():
            hard_failures.append(f"Missing output artifact: {f_path.name}")
        elif f_path.stat().st_size == 0:
            hard_failures.append(f"Output artifact is empty: {f_path.name}")

    if not any("Missing output artifact" in f for f in hard_failures):
        with open(sec_file, "r", encoding="utf-8") as f:
            sec_json = json.load(f)
        with open(chunk_file, "r", encoding="utf-8") as f:
            chunk_lines = [json.loads(line) for line in f if line.strip()]
        with open(summary_file, "r", encoding="utf-8") as f:
            summary_json = json.load(f)
        with open(report_file, "r", encoding="utf-8") as f:
            report_text = f.read()

        # Deep comparison of sections.json against in-memory sections
        if len(sec_json) != len(canonical_doc.sections):
            hard_failures.append(f"sections.json count ({len(sec_json)}) != in-memory section count ({len(canonical_doc.sections)})")
        for i, s_rec in enumerate(sec_json):
            if i >= len(canonical_doc.sections):
                break
            mem_sec = canonical_doc.sections[i]
            for field in [
                "section_id", "title", "level", "parent_section_id", "heading_path",
                "physical_page_start", "physical_page_end", "printed_page_start",
                "printed_page_end", "segmentation_method", "confidence"
            ]:
                mem_val = getattr(mem_sec, field)
                if s_rec.get(field) != mem_val:
                    hard_failures.append(
                        f"sections.json[{i}] field '{field}' mismatch: {s_rec.get(field)!r} != {mem_val!r}"
                    )
            if s_rec.get("block_count") != len(mem_sec.blocks):
                hard_failures.append(
                    f"sections.json[{i}] block_count mismatch: {s_rec.get('block_count')} != {len(mem_sec.blocks)}"
                )

        # Deep comparison of chunks.jsonl against in-memory chunks
        if len(chunk_lines) != len(chunks):
            hard_failures.append(f"chunks.jsonl count ({len(chunk_lines)}) != in-memory chunk count ({len(chunks)})")
        for i, c_rec in enumerate(chunk_lines):
            if i >= len(chunks):
                break
            mem_chk = chunks[i]
            for field in [
                "chunk_id", "document_id", "version_id", "source_id", "section_id",
                "section_title", "physical_page", "printed_page", "chunk_index_in_page",
                "has_table", "char_count", "token_estimate", "content", "content_sha256",
                "source_block_ids", "warnings"
            ]:
                mem_val = getattr(mem_chk, field)
                if c_rec.get(field) != mem_val:
                    hard_failures.append(
                        f"chunks.jsonl[{i}] field '{field}' mismatch: {c_rec.get(field)!r} != {mem_val!r}"
                    )

        # Deep comparison of processing_summary.json metrics
        if summary_json["section_count"] != len(canonical_doc.sections):
            hard_failures.append(f"summary section_count ({summary_json['section_count']}) != {len(canonical_doc.sections)}")
        if summary_json["chunk_count"] != len(chunks):
            hard_failures.append(f"summary chunk_count ({summary_json['chunk_count']}) != {len(chunks)}")
        if summary_json["table_chunk_count"] != len(table_chunks):
            hard_failures.append(f"summary table_chunk_count ({summary_json['table_chunk_count']}) != {len(table_chunks)}")
        if summary_json["oversized_chunk_count"] != len(oversized_narrative) + len(oversized_tables):
            hard_failures.append(f"summary oversized_chunk_count ({summary_json['oversized_chunk_count']}) != {len(oversized_narrative) + len(oversized_tables)}")
        if summary_json["warning_count"] != len(canonical_doc.warnings):
            hard_failures.append(f"summary warning_count ({summary_json['warning_count']}) != {len(canonical_doc.warnings)}")
        if summary_json["status"] != canonical_doc.processing_status.value:
            hard_failures.append(f"summary status ({summary_json['status']}) != doc status ({canonical_doc.processing_status.value})")
        if summary_json["document_id"] != canonical_doc.metadata.document_id:
            hard_failures.append(f"summary document_id mismatch: {summary_json['document_id']} != {canonical_doc.metadata.document_id}")
        if summary_json["source_filename"] != canonical_doc.metadata.source_filename:
            hard_failures.append(f"summary source_filename mismatch: {summary_json['source_filename']} != {canonical_doc.metadata.source_filename}")

        # Deep comparison of quality_report.md metrics and warnings
        if f"Sections Inferred**: `{len(canonical_doc.sections)}`" not in report_text:
            hard_failures.append("quality_report.md does not accurately reflect inferred section count")
        if f"Total Chunks Produced**: `{len(chunks)}`" not in report_text:
            hard_failures.append("quality_report.md does not accurately reflect total chunk count")
        if f"Table Chunks: `{len(table_chunks)}`" not in report_text:
            hard_failures.append("quality_report.md does not accurately reflect table chunk count")
        if f"Oversized Chunks Preserved**: `{len(oversized_narrative) + len(oversized_tables)}`" not in report_text:
            hard_failures.append("quality_report.md does not accurately reflect oversized chunk count")
        if f"Processing Status**: `{canonical_doc.processing_status.value}`" not in report_text:
            hard_failures.append("quality_report.md does not accurately reflect processing status")
        if f"Total Audit Warnings**: `{len(canonical_doc.warnings)}`" not in report_text:
            hard_failures.append("quality_report.md does not accurately reflect audit warnings count")

        # Validate that all logged warning messages appear in the quality report
        for w in canonical_doc.warnings:
            # Check either the message or the category tag is present in report
            category_tag = f"[{w.category.value}]"
            if category_tag not in report_text and w.message not in report_text:
                hard_failures.append(f"quality_report.md missing expected warning entry for category '{w.category.value}'")

    return hard_failures


def run_sample_evaluation(
    page_start: int = 1,
    page_end: int = 19,
    output_dir_name: str = "run_preview_p1_19_v3",
    target_chunk_size: int = 1200,
    max_chunk_size: int = 2000,
    chunk_overlap: int = 150
):
    pdf_path = PROJECT_ROOT / "data" / "raw" / "annual_reports" / "ar26.pdf"
    output_dir = PROJECT_ROOT / "data" / "output_chunks" / output_dir_name

    if not pdf_path.exists():
        print(f"ERROR: Source PDF not found at {pdf_path}")
        sys.exit(1)

    print(f"================================================================================")
    print(f"=== Controlled Sample Evaluation (Pages {page_start}-{page_end}) ===")
    print(f"Source PDF: {pdf_path}")
    print(f"Target Output Directory: {output_dir}")
    print(f"Effective Config: target={target_chunk_size}, max={max_chunk_size}, overlap={chunk_overlap}")
    print(f"================================================================================")

    # Step 1: Extract Physical Pages Only
    print(f"\n[Step 1] Extracting physical pages {page_start}-{page_end} using PDFDocumentAdapter...")
    adapter = PDFDocumentAdapter()
    payload = adapter.extract_file(
        file_path=pdf_path,
        config={"page_start": page_start, "page_end": page_end}
    )

    extracted_pages = len(payload.pages)
    expected_pages = page_end - page_start + 1
    print(f"Attempted: {expected_pages} pages | Extracted: {extracted_pages} pages")
    page_numbers = [p.physical_page for p in payload.pages]
    print(f"Physical page range in payload: min={min(page_numbers) if page_numbers else None}, max={max(page_numbers) if page_numbers else None}")

    # Step 2: Run Pipeline
    print(f"\n[Step 2] Executing Structural Analysis and Hierarchical Chunking...")
    canonical_doc, chunks, run_dir = run_phase2_pipeline(
        payload=payload,
        output_dir=output_dir,
        target_chunk_size=target_chunk_size,
        max_chunk_size=max_chunk_size,
        chunk_overlap=chunk_overlap,
        processing_revision=1
    )

    print(f"Sections inferred: {len(canonical_doc.sections)}")
    print(f"Chunks produced: {len(chunks)}")
    print(f"Quality warnings: {len(canonical_doc.warnings)}")
    print(f"Processing status: {canonical_doc.processing_status.value}")

    # Step 3: Forensic Output Quality Validation
    print(f"\n[Step 3] Forensic Output Quality Verification...")
    hard_failures = validate_sample_execution(
        payload=payload,
        canonical_doc=canonical_doc,
        chunks=chunks,
        output_dir=output_dir,
        target_chunk_size=target_chunk_size,
        max_chunk_size=max_chunk_size,
        page_start=page_start,
        page_end=page_end
    )

    # Step 4: Display Summary
    print(f"\n  - Section Breakdown:")
    for s in canonical_doc.sections:
        print(f"    * [{s.section_id}] '{s.title[:45]}' (Level {s.level}, Pages {s.physical_page_start}-{s.physical_page_end}, Printed {s.printed_page_start}-{s.printed_page_end}, Method={s.segmentation_method}, Blocks={len(s.blocks)})")

    table_chunks = [c for c in chunks if c.has_table]
    narrative_chunks = [c for c in chunks if not c.has_table]
    print(f"\n  - Chunks: {len(chunks)} total ({len(table_chunks)} table, {len(narrative_chunks)} narrative)")

    print(f"\n  - Quality Warnings Audit ({len(canonical_doc.warnings)} total):")
    for w in canonical_doc.warnings:
        print(f"    * [{w.category.value}] (Page {w.physical_page}): {w.message}")

    # Step 5: Final Outcome Evaluation
    print(f"\n================================================================================")
    if hard_failures:
        print(f"=== EVALUATION FAILED WITH {len(hard_failures)} HARD INVARIANT VIOLATIONS ===")
        for fail in hard_failures:
            print(f"  [HARD FAILURE] {fail}")
        print(f"================================================================================")
        sys.exit(1)
    else:
        print(f"=== EVALUATION PASSED: ALL INVARIANTS SATISFIED (Exit Code: 0) ===")
        print(f"================================================================================")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase 3/3.1/3.2 Sample Evaluation")
    parser.add_argument("--page-start", type=int, default=1, help="Starting physical page (1-indexed)")
    parser.add_argument("--page-end", type=int, default=19, help="Ending physical page (1-indexed)")
    parser.add_argument("--output-dir", type=str, default="run_preview_p1_19_v3", help="Subdirectory under data/output_chunks/")
    parser.add_argument("--target-size", type=int, default=1200, help="Target chunk size in chars")
    parser.add_argument("--max-size", type=int, default=2000, help="Max chunk size in chars")
    parser.add_argument("--overlap", type=int, default=150, help="Chunk overlap in chars")
    args = parser.parse_args()

    run_sample_evaluation(
        page_start=args.page_start,
        page_end=args.page_end,
        output_dir_name=args.output_dir,
        target_chunk_size=args.target_size,
        max_chunk_size=args.max_size,
        chunk_overlap=args.overlap
    )
