"""
Section-Aware Chunking Module for HUDCO Evaluation Harness.
Creates deterministic, page-grounded chunks preserving exact physical PDF page numbers,
verified printed page numbers, section metadata, and table flags.
"""

import hashlib
import json
import logging
from typing import List, Optional
from evaluation.config import (
    EVALUATION_CHUNKS_FILE,
    TARGET_CHUNK_CHARS,
    CHUNK_OVERLAP_CHARS,
    MIN_CHUNK_CHARS,
    init_eval_directories,
)
from evaluation.schemas import PageExtractionRecord, EvaluationChunk

logger = logging.getLogger("EvaluationChunker")


def split_text_into_page_windows(
    text: str,
    target_chars: int = TARGET_CHUNK_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
    min_chars: int = MIN_CHUNK_CHARS,
) -> List[str]:
    """
    Splits a single page's text into paragraph-aware chunks with overlap.
    If text length is within target + 200 chars, returns a single chunk.
    """
    cleaned = text.strip()
    if len(cleaned) < min_chars:
        # Keep short text as single chunk only if it has substantive content
        if len(cleaned) >= 40:
            return [cleaned]
        return []

    # If small enough, keep as single chunk for exact page integrity
    if len(cleaned) <= target_chars + 250:
        return [cleaned]

    # Split on paragraph breaks
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in cleaned.split("\n") if p.strip()]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > target_chars and current_chunk:
            chunk_str = "\n\n".join(current_chunk)
            if len(chunk_str) >= min_chars:
                chunks.append(chunk_str)

            # Start next chunk with overlap from end of current chunk
            overlap_seed = []
            overlap_len = 0
            for item in reversed(current_chunk):
                if overlap_len + len(item) <= overlap_chars:
                    overlap_seed.insert(0, item)
                    overlap_len += len(item)
                else:
                    break
            current_chunk = overlap_seed + [para]
            current_len = sum(len(x) for x in current_chunk) + len(current_chunk) * 2
        else:
            current_chunk.append(para)
            current_len += para_len + 2

    if current_chunk:
        chunk_str = "\n\n".join(current_chunk)
        if len(chunk_str) >= min_chars or not chunks:
            chunks.append(chunk_str)

    return chunks


class EvaluationChunker:
    """Produces deterministic EvaluationChunk instances from PageExtractionRecords."""

    def __init__(self, output_file=EVALUATION_CHUNKS_FILE):
        self.output_file = output_file
        init_eval_directories()

    def chunk_pages(self, pages: List[PageExtractionRecord]) -> List[EvaluationChunk]:
        """
        Processes all page extraction records into section-aware, page-grounded chunks.
        """
        all_chunks: List[EvaluationChunk] = []

        for page in pages:
            if page.is_empty:
                continue

            windows = split_text_into_page_windows(page.text)
            for c_idx, window_text in enumerate(windows):
                sha256 = hashlib.sha256(window_text.encode("utf-8")).hexdigest()
                chunk_id = (
                    f"{page.document_id}_{page.section_id}"
                    f"_p{page.physical_page:03d}_c{c_idx:02d}"
                )

                chunk = EvaluationChunk(
                    chunk_id=chunk_id,
                    document_id=page.document_id,
                    source_filename=page.source_filename,
                    section_id=page.section_id,
                    section_title=page.section_title,
                    physical_page=page.physical_page,
                    printed_page=page.printed_page,
                    chunk_index=c_idx,
                    char_count=len(window_text),
                    token_estimate=len(window_text) // 4,
                    has_table=page.has_table,
                    content=window_text,
                    sha256=sha256,
                )
                all_chunks.append(chunk)

        # Write to JSONL
        with open(self.output_file, "w", encoding="utf-8") as f:
            for c in all_chunks:
                f.write(c.model_dump_json() + "\n")

        logger.info(
            f"Chunking complete: {len(all_chunks)} chunks generated across "
            f"{len(pages)} physical pages. Output written to {self.output_file}."
        )
        return all_chunks

    @classmethod
    def load_chunks(cls, chunks_file=EVALUATION_CHUNKS_FILE) -> List[EvaluationChunk]:
        """Loads chunks from an existing evaluation chunks JSONL file."""
        if not chunks_file.exists():
            raise FileNotFoundError(f"Chunks file does not exist: {chunks_file}")

        chunks: List[EvaluationChunk] = []
        with open(chunks_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunks.append(EvaluationChunk.model_validate_json(line))
        return chunks
