"""
Controlled Historical Pilot: ar24.pdf
File: scripts/run_ar24_pilot.py

Executes Layer 1-2 extraction and hierarchical chunking for HUDCO 54th Annual Report (FY 2023-24),
writing artifacts to an isolated run directory without overwriting existing ar26 artifacts or the approved run pointer.
"""

from __future__ import annotations

import sys
import os
import json
import time
import hashlib
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AR24Pilot")

from pipeline.core.contracts import (
    DocumentFormat,
    DocumentMetadata,
    DiscoveryMethod,
    ProcessingStatus,
    CanonicalChunk,
)
from pipeline.adapters.pdf_adapter import PDFDocumentAdapter
from pipeline.core.pipeline_runner import run_phase2_pipeline
from pipeline.core.source_registry import SourceRegistry
from pipeline.core.artifact_guard import validate_run_artifacts_for_reuse
from pipeline.retrieval.loader import load_canonical_chunks



def main():
    t0 = time.time()
    logger.info("=" * 80)
    logger.info("STARTING CONTROLLED HISTORICAL PILOT: ar24.pdf (FY 2023-24)")
    logger.info("=" * 80)

    source_path = PROJECT_ROOT / "data" / "raw" / "annual_reports" / "ar24.pdf"
    if not source_path.exists():
        raise FileNotFoundError(f"Source file ar24.pdf not found at {source_path}")

    # 1. Source verification
    file_bytes = source_path.read_bytes()
    file_size = len(file_bytes)
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    hash8 = sha256[:8]
    logger.info(f"Verified source file: size={file_size} bytes ({file_size/(1024*1024):.2f} MB), sha256={sha256}")

    run_dir = PROJECT_ROOT / "data" / "output_chunks" / "run_pilot_ar24_p1_426_v1"
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Target pilot output directory: {run_dir}")

    # 2. Prepare metadata
    metadata = DocumentMetadata(
        document_id="doc_ar24",
        source_id="hudco_annual_report_ar24",
        version_id=f"doc_ar24_v1_{hash8}",
        version_number=1,
        source_filename="ar24.pdf",
        source_url="https://www.hudco.org.in/writereaddata/ar24.pdf",
        document_format=DocumentFormat.PDF,
        content_sha256=sha256,
        file_size_bytes=file_size,
        total_physical_pages=426,
        discovery_method=DiscoveryMethod.HTML_LISTING,
        title_hint="HUDCO 54th Annual Report 2023-24",
        fiscal_year_hint="2023-24",
        report_title="HUDCO 54th Annual Report 2023-24",
        fiscal_year="2023-24",
    )

    import argparse
    parser = argparse.ArgumentParser(description="HUDCO ar24.pdf Historical Pilot Runner")
    parser.add_argument("--force-reprocess", action="store_true", help="Force extraction and chunking even if artifacts exist")
    args = parser.parse_args()

    can_reuse = False
    if not args.force_reprocess:
        is_valid, validation_msg = validate_run_artifacts_for_reuse(
            run_dir=run_dir,
            expected_doc_id=metadata.document_id,
            expected_source_id=metadata.source_id,
            expected_content_sha256=sha256,
            expected_processing_revision=1,
        )
        if is_valid:
            can_reuse = True
            logger.info(f"Existing artifacts verified in {run_dir.name} ({validation_msg}). Safely reusing.")
        else:
            logger.info(f"Cannot reuse existing artifacts ({validation_msg}); will reprocess.")

    if can_reuse:
        elapsed = time.time() - t0
        logger.info(f"Existing validated artifacts detected in {run_dir.name} ({chunks_file.stat().st_size} bytes). Safely reusing cached artifacts.")

    else:
        # 3. Extract raw pages via PDFDocumentAdapter
        logger.info("Extracting raw pages from ar24.pdf via PDFDocumentAdapter...")
        adapter = PDFDocumentAdapter()
        payload = adapter.extract_file(source_path)
        logger.info(f"Extraction complete: {len(payload.pages)} physical pages extracted.")

        # 4. Run Phase 2 Pipeline (Structural Analysis + Hierarchical Chunking)
        logger.info("Executing Phase 2 pipeline (structural analyzer + hierarchical chunker)...")
        doc, chunks, out_path = run_phase2_pipeline(
            payload=payload,
            output_dir=run_dir,
            metadata=metadata,
            target_chunk_size=1200,
            max_chunk_size=2000,
            chunk_overlap=150,
            processing_revision=1,
        )

        elapsed = time.time() - t0
        logger.info(f"Phase 2 pipeline execution completed in {elapsed:.2f}s.")
        logger.info(f"Generated {len(chunks)} canonical chunks across {len(doc.sections)} sections.")

    # 5. Detailed Verification of Output Artifacts

    chunks_file = run_dir / "chunks.jsonl"
    sections_file = run_dir / "sections.json"
    summary_file = run_dir / "processing_summary.json"
    quality_file = run_dir / "quality_report.md"

    for f in [chunks_file, sections_file, summary_file, quality_file]:
        if not f.exists():
            raise FileNotFoundError(f"Missing required artifact: {f}")
        logger.info(f"Verified artifact exists: {f.name} ({f.stat().st_size} bytes)")

    # Load canonical chunks via standard loader to verify deserialization
    loaded_chunks = load_canonical_chunks(str(chunks_file))
    logger.info(f"Successfully deserialized {len(loaded_chunks)} chunks via load_canonical_chunks().")

    # Invariant checks
    chunk_ids = [c.chunk_id for c in loaded_chunks]
    assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk IDs found!"
    logger.info(f"All {len(chunk_ids)} chunk IDs are strictly unique.")

    fy_values = set(c.fiscal_year for c in loaded_chunks)
    logger.info(f"Chunk fiscal_year values: {fy_values}")
    assert fy_values == {"2023-24"}, f"Expected only '2023-24', got {fy_values}"

    titles = set(c.report_title for c in loaded_chunks)
    logger.info(f"Chunk report_title values: {titles}")
    assert titles == {"HUDCO 54th Annual Report 2023-24"}

    table_chunks = [c for c in loaded_chunks if c.has_table]
    logger.info(f"Chunks with structured tables: {len(table_chunks)}")

    pages_covered = set(c.physical_page for c in loaded_chunks)
    logger.info(f"Physical pages represented in chunks: {len(pages_covered)} (min={min(pages_covered)}, max={max(pages_covered)})")

    # 6. Update SourceRegistry
    registry = SourceRegistry()
    registry.register_source(
        source_id="hudco_annual_report_ar24",
        document_id="doc_ar24",
        source_url="https://www.hudco.org.in/writereaddata/ar24.pdf",
        report_title="HUDCO 54th Annual Report 2023-24",
        report_fiscal_year="2023-24",
        publication_date="2024-09-01",
        discovery_method="official_landing_page",
        source_type="direct_url",
        http_status=200,
        remote_size_bytes=file_size,
        download_status="DOWNLOADED_LOCAL",
        verification_status="OFFICIALLY_VERIFIED",
        content_sha256=sha256,
        file_path=str(source_path.relative_to(PROJECT_ROOT)),
    )
    logger.info(f"SourceRegistry updated: hudco_annual_report_ar24 (doc_ar24) registered as PROCESSED ({len(loaded_chunks)} chunks).")


    # Double check approved run pointer is intact
    approved_pointer = PROJECT_ROOT / "data" / "output_chunks" / "latest_approved_run.json"
    with open(approved_pointer, "r", encoding="utf-8") as f:
        ptr_data = json.load(f)
    assert "ar26" in ptr_data.get("source_filename", "") or "ar26" in ptr_data.get("approved_run_dir", ""), "Approved run pointer was modified!"
    logger.info(f"Verified approved run pointer remains locked to ar26: {ptr_data.get('source_filename')}")


    print("\n" + "=" * 80)
    print(f"PILOT SUCCESS: ar24.pdf processed into {len(loaded_chunks)} canonical chunks in {elapsed:.1f}s.")
    print(f"Output directory: {run_dir}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
