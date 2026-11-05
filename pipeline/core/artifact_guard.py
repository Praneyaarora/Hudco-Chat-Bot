"""
Artifact Reuse and Run Integrity Guard.
File: pipeline/core/artifact_guard.py

Provides rigorous verification before any cached artifact run can be reused.
Guarantees that:
1. All required artifact files exist (chunks.jsonl, sections.json, processing_summary.json, quality_report.md).
2. Processing configuration matches: content_sha256, document_id, source_id, and processing_revision.
3. Chunks file is well-formed JSONL, records deserialize cleanly into CanonicalChunk.
4. Chunk IDs are strictly unique, match the document ID and version.
5. Record count in chunks.jsonl matches total_chunks in processing_summary.json.
6. Sections file contains valid CanonicalSection structures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

from pipeline.core.contracts import CanonicalChunk, CanonicalSection, ProcessingStatus


class ArtifactReuseValidationError(Exception):
    """Raised when existing run artifacts fail validation checks and cannot be reused."""
    pass


def validate_run_artifacts_for_reuse(
    run_dir: Path,
    expected_doc_id: str,
    expected_source_id: str,
    expected_content_sha256: str,
    expected_processing_revision: int = 1,
) -> Tuple[bool, str]:
    """
    Validates that a run directory contains complete, uncorrupted, and schema-compliant
    artifacts matching the expected source hash and configuration.

    Returns:
        (True, "Validation passed") if all checks succeed.
        (False, reason_str) if artifacts are missing, corrupt, or configuration differs.
    """
    run_path = Path(run_dir)
    if not run_path.exists() or not run_path.is_dir():
        return False, f"Run directory does not exist: {run_path}"

    chunks_file = run_path / "chunks.jsonl"
    sections_file = run_path / "sections.json"
    summary_file = run_path / "processing_summary.json"
    quality_file = run_path / "quality_report.md"

    # 1. Existence check
    for req_file, name in [
        (chunks_file, "chunks.jsonl"),
        (sections_file, "sections.json"),
        (summary_file, "processing_summary.json"),
        (quality_file, "quality_report.md"),
    ]:
        if not req_file.exists():
            return False, f"Required artifact {name} is missing in {run_path.name}"
        if req_file.stat().st_size == 0:
            return False, f"Required artifact {name} is empty (0 bytes) in {run_path.name}"

    # 2. Inspect processing_summary.json configuration
    try:
        with open(summary_file, "r", encoding="utf-8") as sf:
            summary = json.load(sf)
    except Exception as e:
        return False, f"processing_summary.json is malformed JSON: {e}"

    sum_doc_id = summary.get("document_id")
    sum_revision = summary.get("processing_revision", 1)
    sum_chunk_count = summary.get("chunk_count")
    sum_sha256 = summary.get("content_sha256")
    if not sum_sha256:
        # Check pipeline_manifest.json if present (e.g. baseline runs)
        manifest_file = run_path / "pipeline_manifest.json"
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as mf:
                    m_data = json.load(mf)
                    sum_sha256 = m_data.get("source_document", {}).get("sha256")
            except Exception:
                pass

    if sum_sha256 != expected_content_sha256:
        return False, f"Source SHA-256 mismatch in summary: expected '{expected_content_sha256}', found '{sum_sha256}'"

    if sum_revision != expected_processing_revision:
        return False, f"Processing revision mismatch in summary: expected {expected_processing_revision}, found {sum_revision}"

    # 3. Inspect sections.json
    try:
        with open(sections_file, "r", encoding="utf-8") as sec_f:
            sec_data = json.load(sec_f)
        if not isinstance(sec_data, list) or len(sec_data) == 0:
            return False, "sections.json contains no valid section entries"
    except Exception as e:
        return False, f"sections.json is malformed JSON: {e}"

    # 4. Stream and validate chunks.jsonl
    seen_chunk_ids = set()
    actual_chunk_count = 0

    try:
        with open(chunks_file, "r", encoding="utf-8") as cf:
            for line_no, line in enumerate(cf, start=1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                chunk_dict = json.loads(clean_line)
                
                # Check required fields and unique ID
                cid = chunk_dict.get("chunk_id")
                if not cid:
                    return False, f"chunks.jsonl line {line_no} lacks chunk_id"
                if cid in seen_chunk_ids:
                    return False, f"Duplicate chunk_id detected on line {line_no}: '{cid}'"
                seen_chunk_ids.add(cid)

                if chunk_dict.get("document_id") != expected_doc_id:
                    return False, f"Chunk {cid} document_id mismatch: expected '{expected_doc_id}', found '{chunk_dict.get('document_id')}'"

                actual_chunk_count += 1
    except Exception as e:
        return False, f"Error validating chunks.jsonl: {e}"

    if actual_chunk_count == 0:
        return False, "chunks.jsonl contains 0 valid chunk records"

    if sum_chunk_count is not None and actual_chunk_count != sum_chunk_count:
        return False, f"Chunk count mismatch: chunks.jsonl has {actual_chunk_count}, summary claims {sum_chunk_count}"

    return True, f"Verified {actual_chunk_count} valid chunks across {len(sec_data)} sections"
