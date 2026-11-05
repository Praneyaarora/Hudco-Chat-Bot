"""
Canonical Chunk Loader Module for Layer 4 Retrieval.
File: pipeline/retrieval/loader.py

Loads, validates, and verifies CanonicalChunk records from on-disk JSONL artifacts.
Guarantees schema compliance and rejects duplicate chunk IDs.
"""

import json
import logging
from pathlib import Path
from typing import List, Union, Set, Optional
from pydantic import ValidationError

from pipeline.core.contracts import CanonicalChunk

logger = logging.getLogger(__name__)


class ChunkLoaderError(Exception):
    """Raised when chunk loading or schema validation encounters fatal invariants."""
    pass


def load_canonical_chunks(
    jsonl_path: Union[str, Path],
    strict: bool = True
) -> List[CanonicalChunk]:
    """
    Loads, parses, and validates CanonicalChunk records from a chunks.jsonl file.
    
    Enforces invariants:
    1. Every line must be valid JSON adhering to CanonicalChunk schema.
    2. Zero duplicate chunk IDs allowed.
    3. Non-empty content and valid 64-char SHA256 hashes.
    
    Args:
        jsonl_path: Path to the chunks.jsonl file.
        strict: If True, raises ChunkLoaderError on first malformed or duplicate record.
                If False, logs warning and skips invalid lines.
                
    Returns:
        List of validated CanonicalChunk instances in file order.
    """
    path_obj = Path(jsonl_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Chunks file does not exist: {path_obj}")

    chunks: List[CanonicalChunk] = []
    seen_chunk_ids: Set[str] = set()

    with open(path_obj, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue

            try:
                record = json.loads(line_str)
            except json.JSONDecodeError as e:
                err_msg = f"Line {line_num} in {path_obj.name} contains invalid JSON: {e}"
                if strict:
                    raise ChunkLoaderError(err_msg) from e
                logger.warning(err_msg)
                continue

            try:
                chunk = CanonicalChunk.model_validate(record)
            except ValidationError as e:
                err_msg = f"Line {line_num} in {path_obj.name} failed CanonicalChunk validation: {e}"
                if strict:
                    raise ChunkLoaderError(err_msg) from e
                logger.warning(err_msg)
                continue

            if chunk.chunk_id in seen_chunk_ids:
                err_msg = f"Duplicate chunk_id '{chunk.chunk_id}' detected at line {line_num} in {path_obj.name}."
                raise ChunkLoaderError(err_msg)

            seen_chunk_ids.add(chunk.chunk_id)
            chunks.append(chunk)

    logger.info(f"Successfully loaded {len(chunks)} canonical chunks from {path_obj.name}.")
    return chunks
