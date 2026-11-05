"""
CLI Runner to Build and Verify the Persistent Semantic Vector Index.
File: scripts/build_semantic_index.py

Indexes all eligible, verified HUDCO annual report canonical chunks into
the local persistent vector index (data/vector_index).
Excludes unverified, mismatched, or blocked documents (such as ar20.pdf).
Supports incremental updates, force-rebuilds, and query probing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

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
logger = logging.getLogger("SemanticIndexer")

from config.settings import settings
from pipeline.core.contracts import CanonicalChunk, IdentityVerificationStatus
from pipeline.retrieval.loader import load_canonical_chunks
from pipeline.retrieval.embedding import LocalEmbeddingEngine
from pipeline.retrieval.semantic_search import PersistentVectorIndex


def collect_eligible_corpus_chunks() -> Tuple[List[CanonicalChunk], Dict[str, Dict[str, Any]], Dict[str, str]]:
    """
    Scans the corpus ingestion summary and source registry to gather
    strictly eligible, verified canonical chunks.
    Returns:
        (eligible_chunks, source_documents_info, excluded_reports)
    """
    summary_path = settings.DATA_DIR / "full_corpus_ingestion_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Corpus ingestion summary not found at {summary_path}. Run full corpus ingestion first.")

    with open(summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    eligible_chunks: List[CanonicalChunk] = []
    source_docs: Dict[str, Dict[str, Any]] = {}
    excluded: Dict[str, str] = {}

    for rep in summary_data.get("reports", []):
        fname = rep["filename"]
        doc_id = rep["document_id"]
        status = rep["status"]
        ident_status = rep.get("identity_status")
        run_dir_str = rep.get("run_dir")

        # Invariant: Only index reports with verified identity and successful run
        if ident_status != IdentityVerificationStatus.VERIFIED.value or not run_dir_str or "BLOCKED" in status:
            reason = rep.get("discrepancy_reason") or f"Status: {status}, Identity: {ident_status}"
            excluded[fname] = reason
            logger.warning(f"Excluding {fname} from vector indexing: {reason}")
            continue

        run_dir = PROJECT_ROOT / run_dir_str
        chunks_file = run_dir / "chunks.jsonl"
        if not chunks_file.exists():
            excluded[fname] = f"Chunks file not found: {chunks_file}"
            logger.error(f"Chunks file missing for {fname} in {run_dir_str}")
            continue

        # Load canonical chunks
        loaded = load_canonical_chunks(str(chunks_file))
        # Ensure fiscal year and source filename attributes are populated
        fy = rep.get("fiscal_year")
        for c in loaded:
            if not getattr(c, "fiscal_year", None):
                setattr(c, "fiscal_year", fy)
            if not getattr(c, "source_filename", None):
                setattr(c, "source_filename", fname)

        eligible_chunks.extend(loaded)
        source_docs[doc_id] = {
            "source_id": rep.get("source_id"),
            "filename": fname,
            "fiscal_year": fy,
            "title": rep.get("report_title"),
            "source_sha256": rep.get("file_sha256"),
            "chunks_sha256": rep.get("chunks_sha256"),
            "chunk_count": len(loaded),
            "run_dir": run_dir_str,
        }
        logger.info(f"Accepted {fname} ({fy}): {len(loaded)} canonical chunks from {run_dir.name}")

    return eligible_chunks, source_docs, excluded


def main():
    parser = argparse.ArgumentParser(description="HUDCO Annual Reports Semantic Vector Indexer")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size (default: 64)")
    parser.add_argument(
        "--force-rebuild",
        "--recompute-all",
        dest="force_rebuild",
        action="store_true",
        help="Force rebuild index from scratch without reusing cached embeddings",
    )
    parser.add_argument("--query", type=str, default=None, help="Probe query after index build")
    parser.add_argument("--top-k", type=int, default=5, help="Top K results for probe query (default: 5)")
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("HUDCO SEMANTIC VECTOR INDEX BUILDER")
    logger.info("=" * 80)

    t_start = time.perf_counter()
    chunks, source_docs, excluded = collect_eligible_corpus_chunks()

    logger.info(f"Eligible corpus: {len(chunks)} chunks across {len(source_docs)} verified reports.")
    logger.info(f"Excluded reports: {len(excluded)} (including: {list(excluded.keys())})")

    engine = LocalEmbeddingEngine(batch_size=args.batch_size)
    index = PersistentVectorIndex(embedding_engine=engine)

    manifest = index.build_from_canonical_chunks(
        chunks=chunks,
        source_documents_info=source_docs,
        batch_size=args.batch_size,
        show_progress=True,
        force_rebuild=args.force_rebuild,
    )

    t_total = round(time.perf_counter() - t_start, 2)
    logger.info("=" * 80)
    logger.info("INDEX BUILD COMPLETE")
    logger.info(f"Total Chunks Indexed: {manifest.total_chunks}")
    logger.info(f"Chunks Reused / Skipped: {manifest.chunks_skipped}")
    logger.info(f"Chunks Newly Encoded: {manifest.chunks_indexed}")
    logger.info(f"Index Embedding Dimension: {manifest.embedding_dimension}")
    logger.info(f"Index Location: {index.index_dir}")
    logger.info(f"Index SHA-256: {manifest.index_sha256[:16]}...")
    logger.info(f"Metadata SHA-256: {manifest.metadata_sha256[:16]}...")
    logger.info(f"Total Wall-Clock Time: {t_total}s")
    logger.info("=" * 80)

    # Optional Probe Query
    if args.query:
        logger.info(f"\nExecuting probe query: '{args.query}' (top_k={args.top_k})")
        t_q0 = time.perf_counter()
        response = index.search(args.query, top_k=args.top_k)
        t_q = round((time.perf_counter() - t_q0) * 1000, 2)
        logger.info(f"Query returned {len(response.results)} results in {t_q} ms (Total candidates scored: {response.total_candidates_scored}):")
        for item in response.results:
            logger.info(
                f"  Rank {item.rank}: score={item.score:.4f} | {item.document_id} ({item.fiscal_year}) | "
                f"{item.citation_label} | {item.chunk_id}"
            )
            preview = item.content.strip().split("\n")[0][:100]
            logger.info(f"    Preview: {preview}...")


if __name__ == "__main__":
    main()
