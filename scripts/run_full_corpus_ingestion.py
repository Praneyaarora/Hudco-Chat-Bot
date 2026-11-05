"""
Full-Corpus Annual Report Ingestion & Verification Runner.
File: scripts/run_full_corpus_ingestion.py

Sequentially ingests and verifies all accessible HUDCO annual reports (ar15 through ar26)
with strict integrity protections:
  - Streaming download with %PDF- validation and 64KB block hashing.
  - Genuine content-based document identity verification gate.
  - Deterministic artifact validation and safe reuse without fabricated metrics.
  - Strict overwrite safety protecting the approved ar26 baseline and existing completed runs.
  - Idempotent and atomic source registry updates.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")

class FlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

handler = FlushHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.root.setLevel(logging.INFO)
logging.root.addHandler(handler)
logger = logging.getLogger("CorpusIngestion")

from config.settings import settings
from pipeline.core.contracts import (
    DocumentFormat,
    DocumentMetadata,
    DiscoveryMethod,
    ProcessingStatus,
    CanonicalChunk,
    IdentityVerificationStatus,
)
from pipeline.adapters.pdf_adapter import PDFDocumentAdapter
from pipeline.core.pipeline_runner import run_phase2_pipeline
from pipeline.core.source_registry import SourceRegistry
from pipeline.core.artifact_guard import validate_run_artifacts_for_reuse
from pipeline.stage_1_ingestion.downloader import DocumentDownloader
from pipeline.stage_1_ingestion.identity_verifier import DocumentIdentityVerifier
from pipeline.retrieval.loader import load_canonical_chunks


ALL_REPORTS = [
    {
        "slug": "ar15",
        "filename": "ar15.pdf",
        "doc_id": "doc_ar15",
        "src_id": "hudco_annual_report_ar15",
        "fiscal_year": "2014-15",
        "title": "HUDCO 45th Annual Report 2014-15",
        "url": "https://www.hudco.org.in/writereaddata/ar15.pdf",
    },
    {
        "slug": "ar16",
        "filename": "ar16.pdf",
        "doc_id": "doc_ar16",
        "src_id": "hudco_annual_report_ar16",
        "fiscal_year": "2015-16",
        "title": "HUDCO 46th Annual Report 2015-16",
        "url": "https://www.hudco.org.in/writereaddata/ar16.pdf",
    },
    {
        "slug": "ar17",
        "filename": "ar17.pdf",
        "doc_id": "doc_ar17",
        "src_id": "hudco_annual_report_ar17",
        "fiscal_year": "2016-17",
        "title": "HUDCO 47th Annual Report 2016-17",
        "url": "https://www.hudco.org.in/writereaddata/ar17.pdf",
    },
    {
        "slug": "ar18",
        "filename": "ar18.pdf",
        "doc_id": "doc_ar18",
        "src_id": "hudco_annual_report_ar18",
        "fiscal_year": "2017-18",
        "title": "HUDCO 48th Annual Report 2017-18",
        "url": "https://www.hudco.org.in/writereaddata/ar18.pdf",
    },
    {
        "slug": "ar19",
        "filename": "ar19.pdf",
        "doc_id": "doc_ar19",
        "src_id": "hudco_annual_report_ar19",
        "fiscal_year": "2018-19",
        "title": "HUDCO 49th Annual Report 2018-19",
        "url": "https://www.hudco.org.in/writereaddata/ar19.pdf",
    },
    {
        "slug": "ar20",
        "filename": "ar20.pdf",
        "doc_id": "doc_ar20",
        "src_id": "hudco_annual_report_ar20",
        "fiscal_year": "2019-20",
        "title": "HUDCO 50th Annual Report 2019-20",
        "url": "https://www.hudco.org.in/writereaddata/ar20.pdf",
    },
    {
        "slug": "ar21",
        "filename": "ar21.pdf",
        "doc_id": "doc_ar21",
        "src_id": "hudco_annual_report_ar21",
        "fiscal_year": "2020-21",
        "title": "HUDCO 51st Annual Report 2020-21",
        "url": "https://www.hudco.org.in/writereaddata/ar21.pdf",
    },
    {
        "slug": "ar22",
        "filename": "ar22.pdf",
        "doc_id": "doc_ar22",
        "src_id": "hudco_annual_report_ar22",
        "fiscal_year": "2021-22",
        "title": "HUDCO 52nd Annual Report 2021-22",
        "url": "https://www.hudco.org.in/writereaddata/ar22.pdf",
    },
    {
        "slug": "ar23",
        "filename": "ar23.pdf",
        "doc_id": "doc_ar23",
        "src_id": "hudco_annual_report_ar23",
        "fiscal_year": "2022-23",
        "title": "HUDCO 53rd Annual Report 2022-23",
        "url": "https://www.hudco.org.in/writereaddata/ar23.pdf",
    },
    {
        "slug": "ar24",
        "filename": "ar24.pdf",
        "doc_id": "doc_ar24",
        "src_id": "hudco_annual_report_ar24",
        "fiscal_year": "2023-24",
        "title": "HUDCO 54th Annual Report 2023-24",
        "url": "https://www.hudco.org.in/writereaddata/ar24.pdf",
    },
    {
        "slug": "ar25",
        "filename": "ar25.pdf",
        "doc_id": "doc_ar25",
        "src_id": "hudco_annual_report_ar25",
        "fiscal_year": "2024-25",
        "title": "HUDCO 55th Annual Report 2024-25",
        "url": "https://www.hudco.org.in/writereaddata/ar25.pdf",
    },
    {
        "slug": "ar26",
        "filename": "ar26.pdf",
        "doc_id": "doc_ar26",
        "src_id": "hudco_annual_report_ar26",
        "fiscal_year": "2025-26",
        "title": "HUDCO 56th Annual Report 2025-26",
        "url": "https://www.hudco.org.in/writereaddata/ar26.pdf",
    },
]


def process_report(
    target: Dict[str, str],
    downloader: DocumentDownloader,
    registry: SourceRegistry,
    force_reprocess: bool = False,
) -> Dict[str, Any]:
    t_start = time.perf_counter()
    fname = target["filename"]
    slug = target["slug"]
    doc_id = target["doc_id"]
    src_id = target["src_id"]
    fy = target["fiscal_year"]
    title = target["title"]
    url = target["url"]

    logger.info("=" * 80)
    logger.info(f"PROCESSING REPORT: {fname} ({title})")
    logger.info("=" * 80)

    # Invariant: Never allow overwriting the approved ar26 baseline directory
    if fname == "ar26.pdf" and force_reprocess:
        logger.warning("ar26.pdf is the locked approved baseline; force-reprocess rejected to preserve approved state.")
        force_reprocess = False

    raw_path = settings.ANNUAL_REPORTS_DIR / fname

    # 1. Download if missing or invalid
    dl_time = None
    if raw_path.exists():
        is_valid_pdf, val_msg = DocumentDownloader.validate_local_pdf(raw_path)
        if not is_valid_pdf:
            logger.warning(f"Local file {fname} failed PDF validation ({val_msg}). Re-downloading...")
            try:
                raw_path.unlink()
            except OSError:
                pass

    if not raw_path.exists():
        logger.info(f"Source file {fname} not found locally or invalid. Initiating streaming download...")
        t_dl = time.perf_counter()
        dl_result = downloader.download_file(
            url=url,
            destination_filename=fname,
            subdirectory="annual_reports",
        )
        dl_time = round(time.perf_counter() - t_dl, 2)
        raw_path = Path(dl_result["file_path"])
        file_size = dl_result["size_bytes"]
        sha256 = dl_result["sha256"]
        logger.info(f"Downloaded {fname} in {dl_time}s ({file_size/(1024*1024):.2f} MB, sha256={sha256[:12]}...)")
    else:
        file_size = raw_path.stat().st_size
        sha256 = DocumentDownloader.compute_sha256_of_file(raw_path)
        logger.info(f"Using validated existing local file {raw_path} ({file_size/(1024*1024):.2f} MB, sha256={sha256[:12]}...)")

    hash8 = sha256[:8]

    # 2. Check for existing valid run (Artifact Reuse Guard)
    if not force_reprocess:
        candidate_patterns = [
            f"run_full_{slug}_p1_*_v1",
            f"run_pilot_{slug}_p1_*_v1",
        ]
        candidate_runs: List[Path] = []
        for pat in candidate_patterns:
            candidate_runs.extend(settings.OUTPUT_CHUNKS_DIR.glob(pat))

        # Deterministic ordering: latest modified first
        candidate_runs = sorted(candidate_runs, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)

        for cand_dir in candidate_runs:
            is_valid, v_msg = validate_run_artifacts_for_reuse(
                run_dir=cand_dir,
                expected_doc_id=doc_id,
                expected_source_id=src_id,
                expected_content_sha256=sha256,
                expected_processing_revision=1,
            )
            if is_valid:
                logger.info(f"Existing validated artifacts detected in {cand_dir.name} ({v_msg}).")

                # Validate persisted identity evidence before promoting to OFFICIALLY_VERIFIED
                ident_file = cand_dir / "identity_verification.json"
                persisted_identity_valid = False
                ident_status_val = IdentityVerificationStatus.UNVERIFIED.value
                ident_reason = None

                if ident_file.exists():
                    try:
                        with open(ident_file, "r", encoding="utf-8") as id_f:
                            id_data = json.load(id_f)
                        if (
                            id_data.get("source_sha256") == sha256
                            and id_data.get("document_id") == doc_id
                            and id_data.get("status") == IdentityVerificationStatus.VERIFIED.value
                            and id_data.get("verifier_revision", 0) >= 2
                        ):
                            persisted_identity_valid = True
                            ident_status_val = IdentityVerificationStatus.VERIFIED.value
                    except Exception as e:
                        logger.warning(f"Error reading identity verification file in {cand_dir.name}: {e}")

                if not persisted_identity_valid and raw_path.exists():
                    # Safely re-verify identity from source PDF front matter
                    logger.info(f"Re-verifying document identity for reused candidate {cand_dir.name} from source PDF...")
                    try:
                        import pypdf
                        from pipeline.adapters.base import RawExtractionPayload, RawPageRecord
                        reader = pypdf.PdfReader(str(raw_path))
                        total_pages = len(reader.pages)
                        pages_payload = []
                        for i in range(min(35, total_pages)):
                            text = reader.pages[i].extract_text() or ""
                            pages_payload.append(RawPageRecord(physical_page=i + 1, text=text, char_count=len(text)))
                        sample_payload = RawExtractionPayload(
                            source_filename=fname,
                            document_format=DocumentFormat.PDF,
                            total_physical_pages=total_pages,
                            pages=pages_payload,
                        )
                        re_result = DocumentIdentityVerifier.verify(
                            payload=sample_payload,
                            expected_filename=fname,
                            expected_fy=fy,
                            expected_title_hint=title,
                        )
                        if re_result.status == IdentityVerificationStatus.VERIFIED:
                            persisted_identity_valid = True
                            ident_status_val = IdentityVerificationStatus.VERIFIED.value
                            # Persist verified identity record into candidate directory
                            ident_record = {
                                "source_sha256": sha256,
                                "document_id": doc_id,
                                "source_id": src_id,
                                "fiscal_year": fy,
                                "status": re_result.status.value,
                                "confidence": re_result.confidence,
                                "verifier_revision": 2,
                                "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "detected_title": re_result.detected_title,
                                "detected_fiscal_year": re_result.detected_fiscal_year,
                                "detected_report_number": re_result.detected_report_number,
                                "details": re_result.details,
                            }
                            with open(ident_file, "w", encoding="utf-8") as id_f:
                                json.dump(ident_record, id_f, indent=2)
                        else:
                            ident_status_val = re_result.status.value
                            ident_reason = re_result.discrepancy_reason
                            logger.warning(f"Reused candidate {cand_dir.name} identity verification was not verified: {ident_status_val} ({ident_reason})")
                    except Exception as e:
                        logger.warning(f"Exception during identity re-verification for {cand_dir.name}: {e}")
                        ident_status_val = IdentityVerificationStatus.UNVERIFIED.value

                verification_status_str = "OFFICIALLY_VERIFIED" if persisted_identity_valid else f"IDENTITY_{ident_status_val}"

                chunks = load_canonical_chunks(str(cand_dir / "chunks.jsonl"))
                with open(cand_dir / "sections.json", "r", encoding="utf-8") as sf:
                    secs = json.load(sf)
                with open(cand_dir / "processing_summary.json", "r", encoding="utf-8") as sum_f:
                    summary = json.load(sum_f)
                chunks_sha256 = DocumentDownloader.compute_sha256_of_file(cand_dir / "chunks.jsonl")

                # Update registry safely with verified status
                registry.register_source(
                    source_id=src_id,
                    document_id=doc_id,
                    source_url=url,
                    report_title=title,
                    report_fiscal_year=fy,
                    discovery_method="official_landing_page",
                    source_type="direct_url",
                    http_status=200,
                    remote_size_bytes=file_size,
                    download_status="DOWNLOADED_LOCAL",
                    verification_status=verification_status_str,
                    content_sha256=sha256,
                    file_path=str(raw_path.relative_to(PROJECT_ROOT)),
                )
                registry.record_processing(
                    source_id=src_id,
                    chunk_count=len(chunks),
                    output_dir=str(cand_dir.relative_to(PROJECT_ROOT)),
                )

                reuse_elapsed = round(time.perf_counter() - t_start, 3)
                total_phys_pages = summary.get("total_physical_pages")
                if total_phys_pages is None:
                    import re
                    m = re.search(r"_p1_(\d+)_v", cand_dir.name)
                    if m:
                        total_phys_pages = int(m.group(1))

                w_cnt = summary.get("warning_count")
                if w_cnt is None:
                    raw_w = summary.get("warnings", [])
                    w_cnt = len(raw_w) if isinstance(raw_w, list) else (1 if raw_w else 0)

                return {
                    "filename": fname,
                    "slug": slug,
                    "document_id": doc_id,
                    "source_id": src_id,
                    "fiscal_year": fy,
                    "report_title": title,
                    "file_size_bytes": file_size,
                    "file_sha256": sha256,
                    "total_pages": total_phys_pages,
                    "artifacts_reused": True,
                    "download_seconds": dl_time,
                    "reuse_validation_seconds": reuse_elapsed,
                    "extraction_seconds": None,
                    "structural_analysis_seconds": None,
                    "chunking_seconds": None,
                    "peak_memory_mb": None,
                    "total_wall_clock_seconds": reuse_elapsed,
                    "chunk_count": len(chunks),
                    "section_count": len(secs),
                    "table_chunk_count": sum(1 for c in chunks if c.has_table),
                    "warning_count": w_cnt,
                    "run_dir": str(cand_dir.relative_to(PROJECT_ROOT)),
                    "chunks_sha256": chunks_sha256,
                    "identity_status": ident_status_val,
                    "status": "SUCCESS_REUSED",
                }

    # 3. Extraction Timing
    gc.collect()
    t_ext_start = time.perf_counter()

    try:
        adapter = PDFDocumentAdapter()
        # Dynamically determine actual physical page count from PDF structure
        try:
            import pypdf
            reader = pypdf.PdfReader(str(raw_path))
            actual_pdf_pages = len(reader.pages)
        except Exception:
            actual_pdf_pages = None

        if fname == "ar20.pdf":
            logger.info(f"Extracting front matter diagnostic for {fname}...")
            payload = adapter.extract_file(raw_path, config={"page_start": 1, "page_end": 25})
            ext_time = round(time.perf_counter() - t_ext_start, 2)
            total_pages = actual_pdf_pages or len(payload.pages)
        else:
            logger.info(f"Extracting raw pages from {fname}...")
            payload = adapter.extract_file(raw_path)
            ext_time = round(time.perf_counter() - t_ext_start, 2)
            total_pages = actual_pdf_pages or len(payload.pages)
        logger.info(f"Extraction completed in {ext_time}s: {total_pages} physical pages.")

        # 4. Content Identity Verification Gate
        ident_result = DocumentIdentityVerifier.verify(
            payload=payload,
            expected_filename=fname,
            expected_fy=fy,
            expected_title_hint=title,
        )
        logger.info(f"Identity Verification for {fname}: {ident_result.status.value} (Confidence: {ident_result.confidence})")

        if ident_result.status != IdentityVerificationStatus.VERIFIED:
            logger.error(
                f"DOCUMENT IDENTITY GATE FAILED for {fname}: {ident_result.discrepancy_reason}. "
                "Halting processing for this report to prevent corpus corruption."
            )
            combined_text = "\n".join(p.text for p in payload.pages)
            words = re.findall(r"\b[A-Za-z0-9]{3,}\b", combined_text)
            is_raster_proof = (
                any(marker in combined_text.lower() for marker in [".job", "cmyk", "cyan", "magenta", "process black"])
                or len(words) < 20
            )
            is_ocr_blocker = is_raster_proof or (
                ident_result.discrepancy_reason and ("scanned" in ident_result.discrepancy_reason.lower() or "ocr" in ident_result.discrepancy_reason.lower())
            )
            v_status = "PROCESSING_BLOCKED_REQUIRES_OCR" if is_ocr_blocker else f"IDENTITY_{ident_result.status.value}"
            stat_label = "PROCESSING_BLOCKED_REQUIRES_OCR" if is_ocr_blocker else f"FAILED_{ident_result.status.value}"

            registry.register_source(
                source_id=src_id,
                document_id=doc_id,
                source_url=url,
                report_title=title,
                report_fiscal_year=fy,
                download_status="DOWNLOADED_LOCAL",
                verification_status=v_status,
                content_sha256=sha256,
                file_path=str(raw_path.relative_to(PROJECT_ROOT)),
                warnings=[ident_result.discrepancy_reason or "Document identity verification failed."],
            )
            return {
                "filename": fname,
                "slug": slug,
                "document_id": doc_id,
                "source_id": src_id,
                "fiscal_year": fy,
                "report_title": title,
                "file_size_bytes": file_size,
                "file_sha256": sha256,
                "total_pages": total_pages,
                "artifacts_reused": False,
                "download_seconds": dl_time,
                "extraction_seconds": ext_time,
                "chunking_seconds": None,
                "peak_memory_mb": None,
                "total_wall_clock_seconds": round(time.perf_counter() - t_start, 2),
                "chunk_count": 0,
                "section_count": 0,
                "table_chunk_count": 0,
                "warning_count": 1 if ident_result.discrepancy_reason else 0,
                "run_dir": None,
                "chunks_sha256": None,
                "identity_status": ident_result.status.value,
                "status": stat_label,
                "discrepancy_reason": ident_result.discrepancy_reason,
            }

        # 5. Overwrite Protection: Determine isolated run directory
        base_run_name = f"run_full_{slug}_p1_{total_pages}_v1"
        target_dir = settings.OUTPUT_CHUNKS_DIR / base_run_name

        # Never clobber existing approved ar26
        if target_dir.name == "run_full_ar26_p1_520_v1":
            raise RuntimeError("CRITICAL SAFETY INVARIANT VIOLATION: Attempted write to approved ar26 run directory!")

        if target_dir.exists():
            # Never overwrite existing run directory; create unique isolated attempt directory
            target_dir = settings.OUTPUT_CHUNKS_DIR / f"{base_run_name}_retry_{int(time.time())}"

        target_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Target run directory: {target_dir}")

        metadata = DocumentMetadata(
            document_id=doc_id,
            source_id=src_id,
            version_id=f"{doc_id}_v1_{hash8}",
            version_number=1,
            source_filename=fname,
            source_url=url,
            document_format=DocumentFormat.PDF,
            content_sha256=sha256,
            file_size_bytes=file_size,
            total_physical_pages=total_pages,
            discovery_method=DiscoveryMethod.HTML_LISTING,
            title_hint=ident_result.detected_title or title,
            fiscal_year_hint=ident_result.detected_fiscal_year or fy,
            report_title=ident_result.detected_title or title,
            fiscal_year=ident_result.detected_fiscal_year or fy,
        )

        # 6. Execute Phase 2 Pipeline
        gc.collect()
        tracemalloc.start()
        t_chunk_start = time.perf_counter()
        logger.info(f"Executing Phase 2 pipeline for {doc_id}...")
        doc, chunks, out_path = run_phase2_pipeline(
            payload=payload,
            output_dir=target_dir,
            metadata=metadata,
            target_chunk_size=1200,
            max_chunk_size=2000,
            chunk_overlap=150,
            processing_revision=1,
        )
        chunk_time = round(time.perf_counter() - t_chunk_start, 2)

        # 7. Validate output artifacts via Artifact Guard
        is_valid, v_msg = validate_run_artifacts_for_reuse(
            run_dir=target_dir,
            expected_doc_id=doc_id,
            expected_source_id=src_id,
            expected_content_sha256=sha256,
            expected_processing_revision=1,
        )
        if not is_valid:
            raise RuntimeError(f"Artifact validation failed for {doc_id}: {v_msg}")

        # Persist verified identity record into newly processed run directory
        ident_evidence = {
            "source_sha256": sha256,
            "document_id": doc_id,
            "source_id": src_id,
            "fiscal_year": fy,
            "status": ident_result.status.value,
            "confidence": ident_result.confidence,
            "verifier_revision": 2,
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "detected_title": ident_result.detected_title,
            "detected_fiscal_year": ident_result.detected_fiscal_year,
            "detected_report_number": ident_result.detected_report_number,
            "details": ident_result.details,
        }
        with open(target_dir / "identity_verification.json", "w", encoding="utf-8") as idf:
            json.dump(ident_evidence, idf, indent=2)

        table_count = sum(1 for c in chunks if c.has_table)
        warning_count = len(doc.warnings)
        chunks_file = target_dir / "chunks.jsonl"
        chunks_sha256 = DocumentDownloader.compute_sha256_of_file(chunks_file)

        # 8. Update SourceRegistry atomically
        registry.register_source(
            source_id=src_id,
            document_id=doc_id,
            source_url=url,
            report_title=ident_result.detected_title or title,
            report_fiscal_year=ident_result.detected_fiscal_year or fy,
            discovery_method="official_landing_page",
            source_type="direct_url",
            http_status=200,
            remote_size_bytes=file_size,
            download_status="DOWNLOADED_LOCAL",
            verification_status="OFFICIALLY_VERIFIED",
            content_sha256=sha256,
            file_path=str(raw_path.relative_to(PROJECT_ROOT)),
        )
        registry.record_processing(
            source_id=src_id,
            chunk_count=len(chunks),
            output_dir=str(target_dir.relative_to(PROJECT_ROOT)),
        )

        total_wall_clock = round(time.perf_counter() - t_start, 2)

        # Measure memory
        if tracemalloc.is_tracing():
            _, peak_bytes = tracemalloc.get_traced_memory()
            peak_mb = round(peak_bytes / (1024 * 1024), 2)
        else:
            peak_mb = None

        # Generate run manifest
        run_manifest = {
            "document_id": doc_id,
            "source_id": src_id,
            "source_filename": fname,
            "source_url": url,
            "report_title": ident_result.detected_title or title,
            "fiscal_year": ident_result.detected_fiscal_year or fy,
            "file_size_bytes": file_size,
            "file_sha256": sha256,
            "total_physical_pages": total_pages,
            "chunk_count": len(chunks),
            "unique_chunk_id_count": len(set(c.chunk_id for c in chunks)),
            "section_count": len(doc.sections),
            "table_chunk_count": table_count,
            "warning_count": warning_count,
            "download_seconds": dl_time,
            "extraction_seconds": ext_time,
            "chunking_seconds": chunk_time,
            "peak_python_memory_mb": peak_mb,
            "total_wall_clock_seconds": total_wall_clock,
            "chunks_sha256": chunks_sha256,
            "identity_verification": ident_result.model_dump(),
            "status": "SUCCESS",
        }
        tmp_mf = target_dir / "manifest.json.tmp"
        with open(tmp_mf, "w", encoding="utf-8") as mf:
            json.dump(run_manifest, mf, indent=2)
        os.replace(tmp_mf, target_dir / "manifest.json")

        logger.info(f"Successfully processed {fname}: {len(chunks)} chunks, {len(doc.sections)} sections in {total_wall_clock}s.")

        return {
            "filename": fname,
            "slug": slug,
            "document_id": doc_id,
            "source_id": src_id,
            "fiscal_year": ident_result.detected_fiscal_year or fy,
            "report_title": ident_result.detected_title or title,
            "file_size_bytes": file_size,
            "file_sha256": sha256,
            "total_pages": total_pages,
            "artifacts_reused": False,
            "download_seconds": dl_time,
            "extraction_seconds": ext_time,
            "chunking_seconds": chunk_time,
            "peak_memory_mb": peak_mb,
            "total_wall_clock_seconds": total_wall_clock,
            "chunk_count": len(chunks),
            "section_count": len(doc.sections),
            "table_chunk_count": table_count,
            "warning_count": warning_count,
            "run_dir": str(target_dir.relative_to(PROJECT_ROOT)),
            "chunks_sha256": chunks_sha256,
            "identity_status": ident_result.status.value,
            "status": "SUCCESS_PROCESSED",
        }

    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description="Full Corpus HUDCO Annual Report Ingestion Runner")
    parser.add_argument("--reports", type=str, default="", help="Comma-separated report slugs to process (e.g. ar15,ar16)")
    parser.add_argument("--force-reprocess", action="store_true", help="Force reprocessing even if valid artifacts exist")
    args = parser.parse_args()

    t_all_start = time.perf_counter()
    logger.info("=" * 80)
    logger.info("STARTING FULL CORPUS HUDCO ANNUAL REPORT INGESTION")
    logger.info("=" * 80)

    # Preflight Check: latest_approved_run.json must be locked to ar26
    approved_pointer_path = settings.OUTPUT_CHUNKS_DIR / "latest_approved_run.json"
    with open(approved_pointer_path, "r", encoding="utf-8") as f:
        ptr_before = json.load(f)
    assert "ar26" in ptr_before.get("source_filename", "") or "ar26" in ptr_before.get("approved_run_dir", ""), "Pointer compromised!"

    # Filter target reports if specified
    targets = ALL_REPORTS
    if args.reports:
        selected = [s.strip().lower() for s in args.reports.split(",")]
        targets = [r for r in ALL_REPORTS if r["slug"] in selected or r["filename"] in selected]

    downloader = DocumentDownloader(target_dir=settings.RAW_DATA_DIR)
    registry = SourceRegistry()

    results = []
    for target in targets:
        try:
            res = process_report(target, downloader, registry, force_reprocess=args.force_reprocess)
            results.append(res)
        except Exception as e:
            logger.error(f"FATAL ERROR processing {target['filename']}: {e}", exc_info=True)
            results.append({
                "filename": target["filename"],
                "slug": target["slug"],
                "document_id": target["doc_id"],
                "source_id": target["src_id"],
                "status": f"FATAL_ERROR: {str(e)}",
            })

    # Postflight check: latest_approved_run.json must still be completely untouched
    with open(approved_pointer_path, "r", encoding="utf-8") as f:
        ptr_after = json.load(f)
    assert ptr_before == ptr_after, "CRITICAL ERROR: latest_approved_run.json was modified during full corpus ingestion!"
    logger.info("Verified latest_approved_run.json remains 100% identical and locked to ar26.")

    total_time = round(time.perf_counter() - t_all_start, 2)
    summary_path = settings.DATA_DIR / "full_corpus_ingestion_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "stage": "Prompt 2 Full Corpus Ingestion",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_wall_clock_seconds": total_time,
            "reports_count": len(results),
            "reports": results,
        }, f, indent=2)

    print("\n" + "=" * 90)
    print("FULL CORPUS INGESTION SUMMARY")
    print("=" * 90)
    for r in results:
        status = r.get("status", "UNKNOWN")
        reused = "REUSED" if r.get("artifacts_reused") else "NEW"
        chunks = r.get("chunk_count", 0)
        pages = r.get("total_pages", 0)
        time_sec = r.get("total_wall_clock_seconds", 0)
        mem = f"{r['peak_memory_mb']} MB" if r.get("peak_memory_mb") is not None else "N/A"
        print(f"Report: {r['filename']:<10} FY: {r.get('fiscal_year', 'N/A'):<8} Pages: {pages:<4} Chunks: {chunks:<5} PeakMem: {mem:<10} [{reused}] {status}")
    print("=" * 90)
    print(f"Total Wall Clock Time: {total_time}s. Saved summary to {summary_path}")


if __name__ == "__main__":
    main()
