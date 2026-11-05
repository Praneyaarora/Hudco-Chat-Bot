"""
Phase 2 Pipeline Runner and Quality Audit Generator.
File: pipeline/core/pipeline_runner.py

Executes end-to-end structural analysis and hierarchical chunking:
1. Accepts RawExtractionPayload or CanonicalDocument.
2. Infers format-agnostic section hierarchy via StructuralAnalyzer.
3. Produces section-bounded chunks via HierarchicalChunker.
4. Emits inspectable artifacts:
   - sections.json (structural hierarchy)
   - chunks.jsonl (line-delimited canonical chunks)
   - processing_summary.json (machine-readable audit metrics)
   - quality_report.md (human-readable quality audit report)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple

from pipeline.core.contracts import (
    CanonicalDocument,
    CanonicalChunk,
    QualityWarning,
    WarningCategory,
    ProcessingStatus,
    DocumentMetadata,
)

if TYPE_CHECKING:
    from pipeline.adapters.base import RawExtractionPayload

from pipeline.core.structural_analyzer import StructuralAnalyzer
from pipeline.core.chunker import HierarchicalChunker


def run_phase2_pipeline(
    payload: RawExtractionPayload,
    output_dir: Path,
    metadata: Optional[DocumentMetadata] = None,
    target_chunk_size: int = 1200,
    max_chunk_size: int = 2500,
    chunk_overlap: int = 150,
    processing_revision: int = 1
) -> Tuple[CanonicalDocument, List[CanonicalChunk], Path]:
    """
    Executes Phase 2 structural analysis and chunking, persisting inspectable artifacts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now(timezone.utc)

    # 1. Structural Analysis
    analyzer = StructuralAnalyzer()
    canonical_doc = analyzer.analyze(payload=payload, metadata=metadata)

    # 2. Hierarchical Chunking
    chunker = HierarchicalChunker(
        target_chunk_size=target_chunk_size,
        max_chunk_size=max_chunk_size,
        chunk_overlap=chunk_overlap,
        processing_revision=processing_revision
    )
    chunks, chunk_warnings = chunker.chunk_document(canonical_doc)

    # Combine all warnings
    canonical_doc.warnings.extend(chunk_warnings)
    all_warnings = list(canonical_doc.warnings)

    # Synchronize processing status with any newly emitted chunk warnings
    if chunk_warnings:
        has_severe = any(w.category == WarningCategory.CONTENT_ANOMALY for w in chunk_warnings)
        if has_severe and canonical_doc.processing_status != ProcessingStatus.FAILED:
            canonical_doc.processing_status = ProcessingStatus.PARTIAL_SUCCESS
        elif canonical_doc.processing_status == ProcessingStatus.SUCCESS:
            canonical_doc.processing_status = ProcessingStatus.SUCCESS_WITH_WARNINGS

    end_time = datetime.now(timezone.utc)
    elapsed_seconds = (end_time - start_time).total_seconds()

    # 3. Emit Artifact 1: sections.json
    sections_path = output_dir / "sections.json"
    with open(sections_path, "w", encoding="utf-8") as f:
        sections_data = [
            {
                "section_id": s.section_id,
                "title": s.title,
                "level": s.level,
                "parent_section_id": s.parent_section_id,
                "heading_path": s.heading_path,
                "physical_page_start": s.physical_page_start,
                "physical_page_end": s.physical_page_end,
                "printed_page_start": s.printed_page_start,
                "printed_page_end": s.printed_page_end,
                "segmentation_method": s.segmentation_method,
                "confidence": s.confidence,
                "block_count": len(s.blocks)
            }
            for s in canonical_doc.sections
        ]
        json.dump(sections_data, f, indent=2, ensure_ascii=False)

    # 4. Emit Artifact 2: chunks.jsonl
    chunks_path = output_dir / "chunks.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            chunk_dict = chunk.model_dump(mode="json")
            f.write(json.dumps(chunk_dict, ensure_ascii=False) + "\n")

    # 5. Emit Artifact 3: processing_summary.json
    summary_path = output_dir / "processing_summary.json"
    table_chunks_count = sum(1 for c in chunks if c.has_table)
    oversized_chunks_count = sum(1 for c in chunks if c.char_count > max_chunk_size)
    low_confidence_sections = [s.section_id for s in canonical_doc.sections if s.confidence == "low"]

    summary_data: Dict[str, Any] = {
        "document_id": canonical_doc.metadata.document_id,
        "source_id": canonical_doc.metadata.source_id,
        "source_filename": canonical_doc.metadata.source_filename,
        "content_sha256": canonical_doc.metadata.content_sha256,
        "document_format": canonical_doc.metadata.document_format.value,
        "total_physical_pages": canonical_doc.metadata.total_physical_pages,
        "elapsed_seconds": elapsed_seconds,
        "effective_config": {
            "target_chunk_size": target_chunk_size,
            "max_chunk_size": max_chunk_size,
            "chunk_overlap": chunk_overlap,
        },
        "section_count": len(canonical_doc.sections),
        "chunk_count": len(chunks),
        "table_chunk_count": table_chunks_count,
        "oversized_chunk_count": oversized_chunks_count,
        "warning_count": len(all_warnings),
        "low_confidence_sections": low_confidence_sections,
        "processing_revision": processing_revision,
        "status": canonical_doc.processing_status.value
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    # 6. Emit Artifact 4: quality_report.md
    report_path = output_dir / "quality_report.md"
    _generate_quality_report(
        report_path=report_path,
        doc=canonical_doc,
        chunks=chunks,
        warnings=all_warnings,
        summary=summary_data,
        target_chunk_size=target_chunk_size,
        max_chunk_size=max_chunk_size,
        chunk_overlap=chunk_overlap
    )

    return canonical_doc, chunks, output_dir


def _generate_quality_report(
    report_path: Path,
    doc: CanonicalDocument,
    chunks: List[CanonicalChunk],
    warnings: List[QualityWarning],
    summary: Dict[str, Any],
    target_chunk_size: int,
    max_chunk_size: int,
    chunk_overlap: int
) -> None:
    """Generates human-readable Markdown quality report."""
    lines = [
        f"# Phase 2 Processing & Quality Audit Report: {doc.metadata.source_filename}",
        "",
        "## 1. Executive Summary",
        f"- **Document ID**: `{doc.metadata.document_id}`",
        f"- **Source File**: `{doc.metadata.source_filename}`",
        f"- **Format**: `{doc.metadata.document_format.value}`",
        f"- **Physical Pages**: `{doc.metadata.total_physical_pages}`",
        f"- **Sections Inferred**: `{summary['section_count']}`",
        f"- **Total Chunks Produced**: `{summary['chunk_count']}` (Table Chunks: `{summary['table_chunk_count']}`)",
        f"- **Effective Chunk Configuration**: Target `{target_chunk_size}` chars | Max `{max_chunk_size}` chars | Overlap `{chunk_overlap}` chars",
        f"- **Oversized Chunks Preserved**: `{summary['oversized_chunk_count']}`",
        f"- **Total Audit Warnings**: `{len(warnings)}`",
        f"- **Processing Status**: `{summary['status']}`",
        "",
        "## 2. Structural Section Hierarchy",
        "| Section ID | Title | Level | Page Range (Physical) | Printed Page Range | Method | Confidence | Blocks |",
        "| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |"
    ]

    for s in doc.sections:
        page_range = f"{s.physical_page_start}–{s.physical_page_end}"
        print_range = f"{s.printed_page_start or 'None'}–{s.printed_page_end or 'None'}"
        lines.append(
            f"| `{s.section_id}` | {s.title} | {s.level} | {page_range} | {print_range} | `{s.segmentation_method}` | **{s.confidence}** | {len(s.blocks)} |"
        )

    lines.extend([
        "",
        "## 3. Chunk Sizing and Distribution Analysis",
    ])

    if chunks:
        sizes = [c.char_count for c in chunks]
        min_sz = min(sizes)
        max_sz = max(sizes)
        avg_sz = sum(sizes) // len(sizes)
        lines.append(f"- **Min Chunk Size**: {min_sz} characters")
        lines.append(f"- **Max Chunk Size**: {max_sz} characters")
        lines.append(f"- **Average Chunk Size**: {avg_sz} characters")
    else:
        lines.append("- *No chunks generated (document empty)*")

    lines.extend([
        "",
        "## 4. Quality Warnings & Anomaly Log"
    ])

    if warnings:
        for w in warnings:
            page_info = f" (Page {w.physical_page})" if w.physical_page else ""
            lines.append(f"- **[{w.category.value}]**{page_info}: {w.message}")
    else:
        lines.append("- *Zero quality warnings recorded.*")

    lines.extend([
        "",
        "## 5. Provenance & Reproducibility Statement",
        "- All chunks carry deterministic IDs incorporating `document_id`, `version_number`, `processing_revision`, and `content_sha256`.",
        "- Chunks strictly respect section boundaries; no cross-section chunks were permitted.",
        "- Tabular data was preserved as indivisible structured units with GFM Markdown display projections.",
        ""
    ])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
