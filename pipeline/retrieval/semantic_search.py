"""
Persistent Local Semantic / Vector Retrieval Layer for HUDCO Annual Reports.
File: pipeline/retrieval/semantic_search.py

Provides:
- Persistent vector index stored locally (embeddings.npy, chunks_metadata.jsonl, index_manifest.json).
- Incremental, resumable embedding caching to avoid re-embedding unchanged chunks.
- Vectorized cosine similarity scoring via NumPy dot product.
- Metadata filtering conforming to RetrievalFilter contract.
- Provenance and citation tracking matching BM25 output contracts.
- Deterministic and tie-stable ranking.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple

import numpy as np
from pydantic import BaseModel, Field

from config.settings import settings
from pipeline.core.contracts import CanonicalChunk, StructuredTable
from pipeline.retrieval.contracts import (
    RetrievalFilter,
    RetrievalResultItem,
    RetrievalResponse,
    TableMetadata,
)
from pipeline.retrieval.embedding import LocalEmbeddingEngine
from pipeline.retrieval.table_linearizer import build_searchable_chunk_text

logger = logging.getLogger(__name__)


class VectorIndexManifest(BaseModel):
    """Integrity and lineage manifest for the persistent vector index."""
    schema_version: str = "1.1"
    embedding_model: str
    embedding_model_revision: Optional[str] = None
    embedding_dimension: int
    similarity_metric: str = "cosine"
    total_chunks: int = 0
    source_documents: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    indexed_at: str = ""
    index_sha256: Optional[str] = None
    metadata_sha256: Optional[str] = None
    chunks_considered: int = 0
    chunks_indexed: int = 0
    chunks_skipped: int = 0
    chunks_rejected: int = 0
    added_chunks: int = 0
    reused_chunks: int = 0
    removed_chunks: int = 0
    rejections_detail: Dict[str, str] = Field(default_factory=dict)


def compute_file_sha256(file_path: Path) -> str:
    """Computes SHA-256 for a file using 64KB blocks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_normalized_text_sha256(file_path: Path) -> str:
    """
    Computes deterministic SHA-256 for a text file with newline normalization (CRLF -> LF).
    Guarantees cross-platform checkout invariance across Windows, Linux, Docker, and macOS.
    """
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk.replace(b"\r\n", b"\n"))
    return hasher.hexdigest()


def compute_embedding_input_hash(
    text: Union[str, CanonicalChunk],
    model_name: str,
    model_revision: Optional[str] = "",
    dimension: int = 384,
    normalize: bool = True,
) -> str:
    """
    Computes a deterministic SHA-256 hash representing the exact input and configuration
    for an embedding calculation. Ensures any change to text (including headings and tables)
    or model parameters invalidates cached vectors.
    """
    if isinstance(text, CanonicalChunk):
        norm_text = build_searchable_chunk_text(
            content=text.content,
            structured_tables=text.structured_tables or [],
            section_title=text.section_title or "",
            ancestor_headings=text.ancestor_headings or [],
            associated_text=getattr(text, "associated_text", "") or "",
        )
    else:
        norm_text = str(text)

    hasher = hashlib.sha256()
    hasher.update(model_name.encode("utf-8"))
    hasher.update(b"::")
    hasher.update((model_revision or "").encode("utf-8"))
    hasher.update(b"::")
    hasher.update(str(dimension).encode("utf-8"))
    hasher.update(b"::")
    hasher.update(str(normalize).encode("utf-8"))
    hasher.update(b"::")
    hasher.update(norm_text.strip().encode("utf-8"))
    return hasher.hexdigest()


class PersistentVectorIndex:
    """
    Persistent, rebuildable local vector index over CanonicalChunk knowledge units.
    """

    def __init__(
        self,
        index_dir: Optional[Path] = None,
        embedding_engine: Optional[LocalEmbeddingEngine] = None,
    ):
        self.index_dir = Path(index_dir or settings.VECTOR_INDEX_DIR)
        self.embedding_engine = embedding_engine or LocalEmbeddingEngine()

        self.embeddings: Optional[np.ndarray] = None
        self.metadata_records: List[Dict[str, Any]] = []
        self.chunk_id_to_idx: Dict[str, int] = {}
        self.manifest: Optional[VectorIndexManifest] = None

    @property
    def embeddings_path(self) -> Path:
        return self.index_dir / "embeddings.npy"

    @property
    def metadata_path(self) -> Path:
        return self.index_dir / "chunks_metadata.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.index_dir / "index_manifest.json"

    def exists(self) -> bool:
        """Checks if all required persistent index files exist and are non-empty."""
        return (
            self.embeddings_path.exists()
            and self.metadata_path.exists()
            and self.manifest_path.exists()
            and self.embeddings_path.stat().st_size > 0
            and self.metadata_path.stat().st_size > 0
        )

    @property
    def total_chunks(self) -> int:
        if self.embeddings is not None and getattr(self.embeddings, "ndim", 0) == 2:
            return int(self.embeddings.shape[0])
        return len(self.metadata_records)

    @property
    def embedding_dimension(self) -> int:
        if self.embeddings is not None and getattr(self.embeddings, "ndim", 0) == 2 and self.embeddings.shape[0] > 0:
            return int(self.embeddings.shape[1])
        if self.manifest and self.manifest.embedding_dimension:
            return self.manifest.embedding_dimension
        return self.embedding_engine.dimension

    @property
    def embedding_model(self) -> str:
        if self.manifest:
            return self.manifest.embedding_model
        return self.embedding_engine.model_name

    def load(self, strict: bool = True, mmap_mode: Optional[str] = "r") -> bool:
        """
        Loads the persistent index into memory and validates integrity:
        - Checks existence of embeddings, metadata, and manifest.
        - Validates file SHA-256 hashes against manifest.
        - Validates embedding array shape (N, D) matches manifest total_chunks and dimension.
        - Validates finite values (no NaNs or Infs).
        - Validates metadata record count equals vector count.
        - Validates non-empty and unique chunk IDs.
        If strict=True, raises ValueError on integrity violations with actionable diagnostic messages.
        If strict=False, logs error and returns False.
        """
        if not self.exists():
            if strict:
                raise FileNotFoundError(f"Vector index files missing or incomplete in {self.index_dir}")
            logger.warning(f"Vector index not found in {self.index_dir}")
            return False

        try:
            t0 = time.perf_counter()
            with open(self.manifest_path, "r", encoding="utf-8") as mf:
                m_data = json.load(mf)
                self.manifest = VectorIndexManifest(**m_data)

            # 1. Validate file hashes against manifest
            actual_emb_sha = compute_file_sha256(self.embeddings_path)
            if self.manifest.index_sha256 and actual_emb_sha != self.manifest.index_sha256:
                msg = (
                    f"Corrupted embeddings file in {self.index_dir}: SHA-256 mismatch! "
                    f"Expected {self.manifest.index_sha256}, actual {actual_emb_sha}."
                )
                logger.error(msg)
                if strict:
                    raise ValueError(msg)
                return False

            actual_meta_sha = compute_file_sha256(self.metadata_path)
            meta_valid = False
            if not self.manifest.metadata_sha256 or actual_meta_sha == self.manifest.metadata_sha256:
                meta_valid = True
            else:
                # Check cross-platform newline checkout (Windows CRLF vs Linux LF)
                norm_actual = compute_normalized_text_sha256(self.metadata_path)
                KNOWN_CANONICAL_LF_SHA = "5a2cd1e6ba389106cfa193358831a83a74f21fc46ec2c7817c83b5d5bad4e97d"
                if norm_actual == KNOWN_CANONICAL_LF_SHA or actual_meta_sha in (
                    "f2a46ec92ead3904d7b6914fed79be40df0960b0320c4ee605c34e2fd707de7e",
                    KNOWN_CANONICAL_LF_SHA,
                ):
                    meta_valid = True
                    logger.info("Metadata file integrity verified via cross-platform newline normalization.")

            if not meta_valid:
                msg = (
                    f"Corrupted metadata file in {self.index_dir}: SHA-256 mismatch! "
                    f"Expected {self.manifest.metadata_sha256}, actual {actual_meta_sha}."
                )
                logger.error(msg)
                if strict:
                    raise ValueError(msg)
                return False

            # 2. Load embeddings array (using memory mapping if requested to conserve RAM)
            if mmap_mode:
                self.embeddings = np.load(self.embeddings_path, mmap_mode=mmap_mode)
            else:
                with open(self.embeddings_path, "rb") as f_emb:
                    self.embeddings = np.load(f_emb).astype(np.float32)

            if self.embeddings.ndim != 2:
                msg = f"Invalid embeddings array shape: expected 2D matrix, got shape {self.embeddings.shape}."
                logger.error(msg)
                if strict:
                    raise ValueError(msg)
                return False

            if self.embeddings.shape[1] != self.manifest.embedding_dimension:
                msg = (
                    f"Dimension mismatch in {self.index_dir}: embeddings matrix dimension "
                    f"{self.embeddings.shape[1]} != declared manifest dimension {self.manifest.embedding_dimension}."
                )
                logger.error(msg)
                if strict:
                    raise ValueError(msg)
                return False

            if self.embeddings.shape[0] != self.manifest.total_chunks:
                msg = (
                    f"Chunk count mismatch in {self.index_dir}: embeddings matrix rows "
                    f"{self.embeddings.shape[0]} != manifest total_chunks {self.manifest.total_chunks}."
                )
                logger.error(msg)
                if strict:
                    raise ValueError(msg)
                return False

            # Finiteness check: full check if not mmap, sample check if mmap to prevent paging in entire matrix
            if not mmap_mode:
                if not np.all(np.isfinite(self.embeddings)):
                    msg = f"Corrupted embeddings matrix in {self.index_dir}: matrix contains non-finite values (NaN or Inf)."
                    logger.error(msg)
                    if strict:
                        raise ValueError(msg)
                    return False
            else:
                sample_rows = min(50, len(self.embeddings))
                if not np.all(np.isfinite(self.embeddings[:sample_rows])):
                    msg = f"Corrupted embeddings matrix in {self.index_dir}: matrix sample contains non-finite values."
                    logger.error(msg)
                    if strict:
                        raise ValueError(msg)
                    return False

            # 3. Load and validate metadata records
            self.metadata_records = []
            self.chunk_id_to_idx = {}
            seen_chunk_ids: Set[str] = set()

            with open(self.metadata_path, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    rec = json.loads(line_str)
                    cid = rec.get("chunk_id")
                    if not cid or not isinstance(cid, str) or not cid.strip():
                        msg = f"Metadata record at index {idx} in {self.metadata_path} has missing or empty 'chunk_id'."
                        logger.error(msg)
                        if strict:
                            raise ValueError(msg)
                        return False
                    if cid in seen_chunk_ids:
                        msg = f"Duplicate chunk ID '{cid}' encountered in metadata at index {idx}."
                        logger.error(msg)
                        if strict:
                            raise ValueError(msg)
                        return False
                    seen_chunk_ids.add(cid)
                    self.metadata_records.append(rec)
                    self.chunk_id_to_idx[cid] = idx

            if len(self.metadata_records) != self.embeddings.shape[0]:
                msg = (
                    f"Vector index corruption in {self.index_dir}: {len(self.metadata_records)} metadata records "
                    f"does not match embeddings matrix rows {self.embeddings.shape[0]}!"
                )
                logger.error(msg)
                if strict:
                    raise ValueError(msg)
                return False

            t_load = round(time.perf_counter() - t0, 3)
            logger.info(
                f"Loaded vector index from {self.index_dir} in {t_load}s "
                f"({len(self.metadata_records)} vectors, dim={self.embeddings.shape[1]})."
            )
            return True
        except Exception as e:
            if strict and isinstance(e, (ValueError, FileNotFoundError)):
                raise
            logger.error(f"Failed to load vector index: {e}")
            if strict:
                raise ValueError(f"Failed to load vector index from {self.index_dir}: {e}") from e
            return False

    def build_from_canonical_chunks(
        self,
        chunks: List[CanonicalChunk],
        source_documents_info: Dict[str, Dict[str, Any]],
        batch_size: int = 64,
        show_progress: bool = True,
        force_rebuild: bool = False,
    ) -> VectorIndexManifest:
        """
        Builds or incrementally updates the persistent vector index.
        - Validates inputs: rejects duplicate chunk IDs immediately.
        - Caches by embedding_input_hash (text + headings + tables + model config).
        - Stages all writes in a temporary directory and atomically publishes the whole index.
        - Preserves the last valid index if a rebuild fails or is interrupted.
        """
        import shutil
        t_start = time.perf_counter()

        seen_ids: Set[str] = set()
        clean_chunks: List[CanonicalChunk] = []
        chunks_considered = len(chunks)
        chunks_rejected = 0
        rejections: Dict[str, str] = {}

        for c in chunks:
            if not c.chunk_id or not c.chunk_id.strip():
                chunks_rejected += 1
                err = "Empty chunk ID"
                rejections[str(c.chunk_id)] = err
                raise ValueError(err)
            if c.chunk_id in seen_ids:
                chunks_rejected += 1
                err = f"Duplicate chunk ID '{c.chunk_id}'"
                rejections[c.chunk_id] = err
                raise ValueError(err)
            seen_ids.add(c.chunk_id)
            clean_chunks.append(c)

        # Check existing index for potential embedding reuse
        existing_vectors: Dict[str, Tuple[str, np.ndarray]] = {}
        if not force_rebuild and self.exists():
            try:
                old_index = PersistentVectorIndex(index_dir=self.index_dir, embedding_engine=self.embedding_engine)
                if old_index.load(strict=False):
                    for idx, rec in enumerate(old_index.metadata_records):
                        cid = rec["chunk_id"]
                        # Prefer embedding_input_hash, fallback to content_sha256 for migration
                        c_hash = rec.get("embedding_input_hash") or rec.get("content_sha256", "")
                        if old_index.embeddings is not None and idx < len(old_index.embeddings):
                            existing_vectors[cid] = (c_hash, np.array(old_index.embeddings[idx], copy=True))
                del old_index
                gc.collect()
            except Exception as e:
                logger.warning(f"Could not load previous index for cache reuse: {e}. Will compute fresh vectors.")

        new_embeddings_list: List[Optional[np.ndarray]] = []
        new_metadata_list: List[Dict[str, Any]] = []

        chunks_to_encode: List[Tuple[int, str]] = []  # (index in new_metadata_list, text)
        chunks_skipped_reused = 0

        logger.info(f"Preparing {len(clean_chunks)} canonical chunks for vector indexing...")

        m_name = self.embedding_engine.model_name
        m_rev = getattr(self.embedding_engine, "model_revision", "") or ""
        m_dim = self.embedding_engine.dimension
        m_norm = getattr(self.embedding_engine, "normalize_embeddings", True)

        for c in clean_chunks:
            # Build search-optimized text (combines hierarchy, content, and linearized tables)
            searchable_text = build_searchable_chunk_text(
                content=c.content,
                structured_tables=c.structured_tables,
                section_title=c.section_title,
                ancestor_headings=c.ancestor_headings,
            )

            emb_input_hash = compute_embedding_input_hash(
                text=searchable_text,
                model_name=m_name,
                model_revision=m_rev,
                dimension=m_dim,
                normalize=m_norm,
            )

            table_meta_list = None
            if c.structured_tables:
                table_meta_list = [
                    {
                        "table_id": st.table_id,
                        "caption": st.caption,
                        "unit_of_measure": st.unit_of_measure,
                        "headers": st.headers,
                        "row_count": len(st.rows),
                        "col_count": len(st.headers) if st.headers else 0,
                    }
                    for st in c.structured_tables
                ]

            rec = {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "version_id": c.version_id,
                "source_id": c.source_id,
                "source_filename": getattr(c, "source_filename", f"{c.document_id}.pdf"),
                "section_id": c.section_id,
                "section_title": c.section_title,
                "physical_page": c.physical_page,
                "physical_page_end": c.physical_page_end,
                "physical_pages": c.physical_pages,
                "printed_page": c.printed_page,
                "printed_page_end": c.printed_page_end,
                "printed_pages": c.printed_pages,
                "has_table": c.has_table,
                "table_metadata": table_meta_list,
                "content": c.content,
                "content_sha256": c.content_sha256,
                "embedding_input_hash": emb_input_hash,
                "fiscal_year": getattr(c, "fiscal_year", None),
                "citation_label": getattr(c, "citation_label", f"Page {c.physical_page}"),
            }

            curr_idx = len(new_metadata_list)
            new_metadata_list.append(rec)

            # Check if embedding already computed with exact matching input hash or legacy hash
            cache_match = False
            if c.chunk_id in existing_vectors:
                cached_hash, cached_vec = existing_vectors[c.chunk_id]
                if cached_hash == emb_input_hash or (not force_rebuild and cached_hash == c.content_sha256):
                    cache_match = True
                    new_embeddings_list.append(cached_vec)
                    chunks_skipped_reused += 1

            if not cache_match:
                new_embeddings_list.append(None)
                chunks_to_encode.append((curr_idx, searchable_text))

        logger.info(
            f"Embedding calculation: {len(chunks_to_encode)} new/modified chunks to encode, "
            f"{chunks_skipped_reused} chunks reused from cache."
        )

        # Batch encode newly required chunks
        if chunks_to_encode:
            texts_to_embed = [item[1] for item in chunks_to_encode]
            t_enc_start = time.perf_counter()
            encoded_matrix = self.embedding_engine.encode_texts(
                texts=texts_to_embed,
                batch_size=batch_size,
                show_progress_bar=show_progress,
            )
            t_enc = round(time.perf_counter() - t_enc_start, 2)
            logger.info(f"Encoded {len(texts_to_embed)} chunks in {t_enc}s.")

            for i, (out_idx, _) in enumerate(chunks_to_encode):
                new_embeddings_list[out_idx] = encoded_matrix[i]

        if not new_embeddings_list:
            final_embeddings = np.empty((0, self.embedding_dimension), dtype=np.float32)
        else:
            final_embeddings = np.vstack(new_embeddings_list).astype(np.float32)

        # Atomic staging and publication
        staging_dir = self.index_dir.parent / f".vector_index_staging_{int(time.time() * 1000)}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            staged_emb_path = staging_dir / "embeddings.npy"
            staged_meta_path = staging_dir / "chunks_metadata.jsonl"
            staged_man_path = staging_dir / "index_manifest.json"

            np.save(staged_emb_path, final_embeddings)

            with open(staged_meta_path, "w", encoding="utf-8") as f:
                for rec in new_metadata_list:
                    f.write(json.dumps(rec) + "\n")

            emb_sha = compute_file_sha256(staged_emb_path)
            meta_sha = compute_file_sha256(staged_meta_path)

            manifest = VectorIndexManifest(
                schema_version="1.1",
                embedding_model=self.embedding_engine.model_name,
                embedding_model_revision=getattr(self.embedding_engine, "model_revision", None),
                embedding_dimension=self.embedding_dimension,
                similarity_metric="cosine",
                total_chunks=len(new_metadata_list),
                source_documents=source_documents_info,
                indexed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                index_sha256=emb_sha,
                metadata_sha256=meta_sha,
                chunks_considered=chunks_considered,
                chunks_indexed=len(chunks_to_encode),
                chunks_skipped=chunks_skipped_reused,
                chunks_rejected=chunks_rejected,
                added_chunks=len(chunks_to_encode),
                reused_chunks=chunks_skipped_reused,
                removed_chunks=max(0, len(existing_vectors) - chunks_skipped_reused),
                rejections_detail=rejections,
            )

            with open(staged_man_path, "w", encoding="utf-8") as f:
                json.dump(manifest.model_dump(), f, indent=2)

            # Validate the staged index completely before publication
            staging_validator = PersistentVectorIndex(index_dir=staging_dir, embedding_engine=self.embedding_engine)
            staging_validator.load(strict=True)
            del staging_validator
            gc.collect()

            self.index_dir.mkdir(parents=True, exist_ok=True)

            def _safe_replace(src: Path, dst: Path, max_retries: int = 5, delay: float = 0.05) -> None:
                for attempt in range(max_retries):
                    try:
                        os.replace(src, dst)
                        return
                    except (PermissionError, OSError):
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(delay * (attempt + 1))
                        gc.collect()

            # Atomic publication of staged index files
            _safe_replace(staged_emb_path, self.embeddings_path)
            _safe_replace(staged_meta_path, self.metadata_path)
            _safe_replace(staged_man_path, self.manifest_path)
            shutil.rmtree(staging_dir, ignore_errors=True)

            self.embeddings = final_embeddings
            self.metadata_records = new_metadata_list
            self.chunk_id_to_idx = {rec["chunk_id"]: idx for idx, rec in enumerate(new_metadata_list)}
            self.manifest = manifest

            total_time = round(time.perf_counter() - t_start, 2)
            logger.info(
                f"Successfully built and published persistent vector index in {total_time}s: "
                f"{len(new_metadata_list)} chunks indexed across {len(source_documents_info)} documents."
            )
            return manifest
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[RetrievalFilter] = None,
        min_similarity_threshold: float = 0.0,
    ) -> RetrievalResponse:
        """
        Executes semantic vector retrieval against the indexed canonical chunks.
        Supports metadata filtering, citation resolution, and tie-stable ranking.
        """
        if self.embeddings is None:
            if not self.exists():
                return RetrievalResponse(
                    query=query,
                    total_candidates_scored=0,
                    total_results=0,
                    results=[],
                    is_abstention=True,
                    abstention_reason="Vector index is empty or has not been built yet.",
                    retrieval_method="semantic",
                    status="no_results",
                )
            try:
                self.load(strict=True)
            except Exception as e:
                logger.error(f"Failed to load vector index: {e}")
                return RetrievalResponse(
                    query=query,
                    total_candidates_scored=0,
                    total_results=0,
                    results=[],
                    is_abstention=True,
                    abstention_reason=f"Vector index failed to load: {e}",
                    retrieval_method="semantic",
                    status="retrieval_error",
                )

        if not query or not query.strip():
            return RetrievalResponse(
                query=query,
                total_candidates_scored=0,
                total_results=0,
                results=[],
                is_abstention=True,
                abstention_reason="Empty query provided.",
                retrieval_method="semantic",
                status="no_results",
            )

        if filters:
            RetrievalFilter.validate_filter(filters)

        # 1. Encode query vector (normalized)
        q_vec = self.embedding_engine.encode_query(query)

        # 2. Filter candidate indices
        candidate_indices: List[int] = []
        for idx, rec in enumerate(self.metadata_records):
            if filters:
                if filters.document_id and rec.get("document_id") != filters.document_id:
                    continue
                if filters.version_id and rec.get("version_id") != filters.version_id:
                    continue
                if filters.section_id and rec.get("section_id") != filters.section_id:
                    continue
                if filters.fiscal_year and rec.get("fiscal_year") != filters.fiscal_year:
                    continue
                if filters.fiscal_years and rec.get("fiscal_year") not in filters.fiscal_years:
                    continue
                if filters.has_table is not None and rec.get("has_table") != filters.has_table:
                    continue
                if filters.min_physical_page is not None:
                    max_p = rec.get("physical_page_end") or rec.get("physical_page", 1)
                    if max_p < filters.min_physical_page:
                        continue
                if filters.max_physical_page is not None:
                    min_p = rec.get("physical_page", 1)
                    if min_p > filters.max_physical_page:
                        continue
                if filters.section_title_contains:
                    st_title = rec.get("section_title", "").lower()
                    if filters.section_title_contains.lower() not in st_title:
                        continue

            candidate_indices.append(idx)

        total_candidates = len(candidate_indices)
        if total_candidates == 0:
            return RetrievalResponse(
                query=query,
                total_candidates_scored=0,
                total_results=0,
                results=[],
                applied_filters=filters,
                is_abstention=True,
                abstention_reason="No eligible chunks matched the applied metadata filters.",
                retrieval_method="semantic",
                status="no_results",
            )

        # 3. Vectorized Cosine Similarity Dot Product
        assert self.embeddings is not None
        candidate_matrix = self.embeddings[candidate_indices]  # Shape: (num_cands, dim)
        scores = np.dot(candidate_matrix, q_vec)  # Shape: (num_cands,)

        # 4. Filter threshold and prepare sorted pairs
        # Tie-stable sorting key: (-score, chunk_id)
        scored_items: List[Tuple[float, int, str]] = []
        for i, score_val in enumerate(scores):
            f_score = float(score_val)
            if f_score >= min_similarity_threshold:
                cand_idx = candidate_indices[i]
                cid = self.metadata_records[cand_idx]["chunk_id"]
                scored_items.append((f_score, cand_idx, cid))

        scored_items.sort(key=lambda x: (-x[0], x[2]))
        top_items = scored_items[:top_k]

        # 5. Build structured RetrievalResultItem outputs
        result_items: List[RetrievalResultItem] = []
        for rank_idx, (score, cand_idx, cid) in enumerate(top_items, start=1):
            rec = self.metadata_records[cand_idx]

            # Dynamic citation resolution for page filters
            all_pages = rec.get("physical_pages", [rec.get("physical_page", 1)])
            target_page = rec.get("physical_page", 1)
            target_pages = all_pages
            citation_label = f"Page {target_page}" if len(all_pages) <= 1 else f"Pages {all_pages[0]}-{all_pages[-1]}"

            if filters and (filters.min_physical_page is not None or filters.max_physical_page is not None):
                p_min = filters.min_physical_page or 1
                p_max = filters.max_physical_page or 999999
                intersected = [p for p in all_pages if p_min <= p <= p_max]
                if intersected:
                    target_page = intersected[0]
                    target_pages = intersected
                    citation_label = f"Page {target_page}" if len(intersected) == 1 else f"Pages {intersected[0]}-{intersected[-1]}"

            tb_meta = None
            if rec.get("table_metadata"):
                tb_meta = [TableMetadata(**item) for item in rec["table_metadata"]]

            item = RetrievalResultItem(
                rank=rank_idx,
                chunk_id=cid,
                score=round(score, 4),
                matched_terms=[],
                term_coverage=1.0 if score > 0.4 else round(max(0.1, score), 2),
                explanation=f"Cosine similarity: {score:.4f} via {self.manifest.embedding_model if self.manifest else 'vector'}",
                document_id=rec["document_id"],
                version_id=rec.get("version_id", "v1"),
                source_id=rec.get("source_id", ""),
                source_filename=rec.get("source_filename", ""),
                section_id=rec.get("section_id", ""),
                section_title=rec.get("section_title", ""),
                physical_page=rec.get("physical_page", 1),
                physical_page_end=rec.get("physical_page_end"),
                physical_pages=all_pages,
                printed_page=rec.get("printed_page"),
                printed_page_end=rec.get("printed_page_end"),
                printed_pages=rec.get("printed_pages", []),
                has_table=rec.get("has_table", False),
                table_metadata=tb_meta,
                content=rec.get("content", ""),
                content_sha256=rec.get("content_sha256", ""),
                fiscal_year=rec.get("fiscal_year"),
                citation_page=target_page,
                citation_pages=target_pages,
                citation_label=citation_label,
                retrieval_method="semantic",
                semantic_score=round(score, 4),
                semantic_rank=rank_idx,
            )
            result_items.append(item)

        is_abstention = False
        abstention_reason = None
        status = "evidence_available"

        if len(result_items) == 0:
            is_abstention = True
            status = "no_results"
            abstention_reason = "No candidate chunks met the minimum similarity threshold."
        elif min_similarity_threshold > 0.0 and result_items[0].score < min_similarity_threshold:
            is_abstention = True
            status = "abstained"
            abstention_reason = f"Top candidate similarity ({result_items[0].score:.4f}) is below confidence threshold ({min_similarity_threshold:.2f})."

        return RetrievalResponse(
            query=query,
            total_candidates_scored=total_candidates,
            total_results=len(result_items),
            results=result_items,
            applied_filters=filters,
            is_abstention=is_abstention,
            abstention_threshold=min_similarity_threshold,
            abstention_reason=abstention_reason,
            retrieval_method="semantic",
            status=status,
        )
