"""
Hybrid BM25 + Semantic Vector Retrieval Layer with Reciprocal Rank Fusion (RRF).
File: pipeline/retrieval/hybrid_search.py

Combines lexical search (Layer4BM25Index) and persistent dense vector search
(PersistentVectorIndex) over validated canonical chunks using Reciprocal Rank Fusion:
    RRF_score(d) = \\sum_{b \\in \\{bm25, semantic\\}} 1 / (k + rank_b(d))

Guarantees:
- Common join key: canonical chunk_id.
- Identical underlying chunk provenance and citation attribution.
- Compatible metadata filtering applied uniformly across branches.
- Deterministic, tie-stable ranking.
- Distinguishes "no candidates matched filters" from "retrieval failed".
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, Any

from pipeline.retrieval.contracts import (
    RetrievalFilter,
    RetrievalResultItem,
    RetrievalResponse,
)
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.semantic_search import PersistentVectorIndex

logger = logging.getLogger(__name__)

DEFAULT_RRF_K: int = 60
DEFAULT_BRANCH_DEPTH: int = 50
DEFAULT_SEMANTIC_CONFIDENCE_THRESHOLD: float = 0.65


class HybridRetriever:
    """
    Hybrid retriever fusing BM25 lexical search and dense semantic vector retrieval
    via Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        bm25_index: Optional[Layer4BM25Index] = None,
        semantic_index: Optional[PersistentVectorIndex] = None,
        rrf_k: int = DEFAULT_RRF_K,
        default_bm25_depth: int = DEFAULT_BRANCH_DEPTH,
        default_semantic_depth: int = DEFAULT_BRANCH_DEPTH,
        semantic_confidence_threshold: float = DEFAULT_SEMANTIC_CONFIDENCE_THRESHOLD,
    ):
        self.bm25_index = bm25_index
        self.semantic_index = semantic_index
        self.rrf_k = rrf_k
        self.default_bm25_depth = default_bm25_depth
        self.default_semantic_depth = default_semantic_depth
        self.semantic_confidence_threshold = semantic_confidence_threshold

    def fuse_rankings(
        self,
        bm25_results: List[RetrievalResultItem],
        semantic_results: List[RetrievalResultItem],
        top_k: int = 5,
        rrf_k: Optional[int] = None,
        min_rrf_threshold: float = 0.0,
    ) -> List[RetrievalResultItem]:
        """
        Reciprocal Rank Fusion (RRF) algorithm:
        RRF_score(d) = sum_{b in {bm25, semantic}} 1 / (k + rank_b(d))

        Only includes rankings where a document was actually retrieved.
        Provides deterministic tie-breaking: (-score, min_branch_rank, chunk_id).
        Preserves original branch scores, branch ranks, and full canonical provenance.
        """
        effective_k = rrf_k if rrf_k is not None else self.rrf_k
        fused_scores: Dict[str, float] = {}
        bm25_data: Dict[str, Tuple[int, RetrievalResultItem]] = {}
        semantic_data: Dict[str, Tuple[int, RetrievalResultItem]] = {}

        for rank_idx, item in enumerate(bm25_results, start=1):
            cid = item.chunk_id
            bm25_data[cid] = (rank_idx, item)
            fused_scores[cid] = fused_scores.get(cid, 0.0) + (1.0 / (effective_k + rank_idx))

        for rank_idx, item in enumerate(semantic_results, start=1):
            cid = item.chunk_id
            semantic_data[cid] = (rank_idx, item)
            fused_scores[cid] = fused_scores.get(cid, 0.0) + (1.0 / (effective_k + rank_idx))

        candidate_ids = list(fused_scores.keys())

        def sort_key(cid: str) -> Tuple[float, int, str]:
            score = fused_scores[cid]
            b_rank = bm25_data[cid][0] if cid in bm25_data else 999999
            s_rank = semantic_data[cid][0] if cid in semantic_data else 999999
            min_rank = min(b_rank, s_rank)
            return (-score, min_rank, cid)

        candidate_ids.sort(key=sort_key)

        result_items: List[RetrievalResultItem] = []
        for rank_idx, cid in enumerate(candidate_ids, start=1):
            score = fused_scores[cid]
            if score < min_rrf_threshold:
                continue

            source_item = bm25_data[cid][1] if cid in bm25_data else semantic_data[cid][1]

            b_rank = bm25_data[cid][0] if cid in bm25_data else None
            b_score = bm25_data[cid][1].score if cid in bm25_data else None

            s_rank = semantic_data[cid][0] if cid in semantic_data else None
            s_score = semantic_data[cid][1].score if cid in semantic_data else None

            parts = [f"RRF: {score:.6f} (k={effective_k})"]
            if b_rank is not None and b_score is not None:
                parts.append(f"BM25 rank {b_rank} (score {b_score:.2f})")
            if s_rank is not None and s_score is not None:
                parts.append(f"Semantic rank {s_rank} (score {s_score:.4f})")
            explanation = " | ".join(parts)

            matched_terms = bm25_data[cid][1].matched_terms if cid in bm25_data else []
            term_cov = bm25_data[cid][1].term_coverage if cid in bm25_data else (
                1.0 if (s_score is not None and s_score > 0.4) else 0.5
            )

            merged_item = RetrievalResultItem(
                rank=rank_idx,
                chunk_id=cid,
                score=round(score, 6),
                matched_terms=matched_terms,
                term_coverage=term_cov,
                explanation=explanation,
                document_id=source_item.document_id,
                version_id=source_item.version_id,
                source_id=source_item.source_id,
                source_filename=source_item.source_filename,
                section_id=source_item.section_id,
                section_title=source_item.section_title,
                ancestor_headings=getattr(source_item, "ancestor_headings", []),
                physical_page=source_item.physical_page,
                physical_page_end=source_item.physical_page_end,
                physical_pages=source_item.physical_pages,
                printed_page=source_item.printed_page,
                printed_page_end=source_item.printed_page_end,
                printed_pages=source_item.printed_pages,
                has_table=source_item.has_table,
                table_metadata=source_item.table_metadata,
                content=source_item.content,
                content_sha256=source_item.content_sha256,
                fiscal_year=source_item.fiscal_year,
                reporting_period=source_item.reporting_period,
                citation_page=source_item.citation_page,
                citation_pages=source_item.citation_pages,
                citation_label=source_item.citation_label,
                retrieval_method="hybrid_rrf",
                bm25_score=b_score,
                bm25_rank=b_rank,
                semantic_score=s_score,
                semantic_rank=s_rank,
                rrf_score=round(score, 6),
            )
            result_items.append(merged_item)
            if len(result_items) >= top_k:
                break

        return result_items

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[RetrievalFilter] = None,
        bm25_depth: Optional[int] = None,
        semantic_depth: Optional[int] = None,
        rrf_k: Optional[int] = None,
        min_rrf_threshold: float = 0.0,
        semantic_confidence_threshold: Optional[float] = None,
    ) -> RetrievalResponse:
        """
        Executes hybrid retrieval by querying BM25 and Semantic branches,
        fusing candidates using Reciprocal Rank Fusion (RRF), preserving
        complete provenance and branch diagnostics, and distinguishing outcome states:
        - 'evidence_available': Confident candidates found across branches.
        - 'abstained': Evaluated candidates fell below confidence thresholds.
        - 'no_results': No candidates matched query or applied metadata filters.
        - 'partial_branch_failure': One branch encountered an error, but remaining branch provided results.
        - 'retrieval_error': All active retrieval branches failed with runtime errors.
        """
        effective_k = rrf_k if rrf_k is not None else self.rrf_k
        sem_conf_thresh = (
            semantic_confidence_threshold
            if semantic_confidence_threshold is not None
            else self.semantic_confidence_threshold
        )

        # 1. Handle empty queries
        if not query or not query.strip():
            return RetrievalResponse(
                query=query,
                total_candidates_scored=0,
                total_results=0,
                results=[],
                applied_filters=filters,
                is_abstention=True,
                abstention_reason="Empty query provided.",
                retrieval_method="hybrid_rrf",
                status="no_results",
                rrf_k=effective_k,
                branch_candidate_counts={"bm25": 0, "semantic": 0},
            )

        # 2. Check branch availability
        has_bm25 = self.bm25_index is not None and getattr(self.bm25_index, "N", 0) > 0
        has_semantic = self.semantic_index is not None and (
            self.semantic_index.exists() or (self.semantic_index.embeddings is not None and len(self.semantic_index.embeddings) > 0)
        )

        if not has_bm25 and not has_semantic:
            return RetrievalResponse(
                query=query,
                total_candidates_scored=0,
                total_results=0,
                results=[],
                applied_filters=filters,
                is_abstention=True,
                abstention_reason="No retrieval branches available (both BM25 and Semantic indices are uninitialized or empty).",
                retrieval_method="hybrid_rrf",
                status="no_results",
                rrf_k=effective_k,
                branch_candidate_counts={"bm25": 0, "semantic": 0},
            )

        # 3. Determine candidate retrieval depths
        k_bm25 = max(top_k, bm25_depth or self.default_bm25_depth)
        k_sem = max(top_k, semantic_depth or self.default_semantic_depth)

        bm25_results: List[RetrievalResultItem] = []
        bm25_scored_total = 0
        bm25_error: Optional[str] = None
        bm25_resp: Optional[RetrievalResponse] = None

        semantic_results: List[RetrievalResultItem] = []
        semantic_scored_total = 0
        semantic_error: Optional[str] = None
        sem_resp: Optional[RetrievalResponse] = None

        # 4. Query BM25 branch
        if has_bm25 and self.bm25_index is not None:
            try:
                if hasattr(self.bm25_index, "search"):
                    bm25_resp = self.bm25_index.search(query=query, top_k=k_bm25, filters=filters)
                else:
                    bm25_resp = self.bm25_index.retrieve(query=query, top_k=k_bm25, filters=filters)
                bm25_results = bm25_resp.results
                bm25_scored_total = bm25_resp.total_candidates_scored
            except Exception as e:
                bm25_error = str(e)
                logger.error(f"BM25 retrieval branch failed: {e}")

        # 5. Query Semantic branch
        if has_semantic and self.semantic_index is not None:
            try:
                sem_resp = self.semantic_index.search(query=query, top_k=k_sem, filters=filters)
                semantic_results = sem_resp.results
                semantic_scored_total = sem_resp.total_candidates_scored
            except Exception as e:
                semantic_error = str(e)
                logger.error(f"Semantic retrieval branch failed: {e}")

        # 6. Check for total failure across all active branches (never classify runtime errors as abstentions)
        if (has_bm25 and bm25_error and not has_semantic) or (has_semantic and semantic_error and not has_bm25) or (bm25_error and semantic_error):
            return RetrievalResponse(
                query=query,
                total_candidates_scored=0,
                total_results=0,
                results=[],
                applied_filters=filters,
                is_abstention=False,
                abstention_reason=None,
                retrieval_method="hybrid_rrf",
                status="retrieval_error",
                rrf_k=effective_k,
                branch_candidate_counts={"bm25": 0, "semantic": 0},
            )

        partial_branch_failure = bool(bm25_error or semantic_error)

        # 7. Check if candidates were evaluated but none matched filters
        total_candidates_scored = bm25_scored_total + semantic_scored_total
        branch_counts = {"bm25": len(bm25_results), "semantic": len(semantic_results)}

        if not bm25_results and not semantic_results:
            abstention_reason = "No candidate chunks matched the query or applied metadata filters across retrieval branches."
            return RetrievalResponse(
                query=query,
                total_candidates_scored=total_candidates_scored,
                total_results=0,
                results=[],
                applied_filters=filters,
                is_abstention=True,
                abstention_reason=abstention_reason,
                retrieval_method="hybrid_rrf",
                status="no_results",
                rrf_k=effective_k,
                branch_candidate_counts=branch_counts,
            )

        # 8. Reciprocal Rank Fusion calculation
        result_items = self.fuse_rankings(
            bm25_results=bm25_results,
            semantic_results=semantic_results,
            top_k=top_k,
            rrf_k=effective_k,
            min_rrf_threshold=min_rrf_threshold,
        )

        # 9. Calibrated abstention check for hybrid retrieval:
        # Preserve BM25's abstention signal if semantic similarity is weak (< sem_conf_thresh)
        is_abstention = False
        abstention_reason: Optional[str] = None
        status = "partial_branch_failure" if partial_branch_failure else "evidence_available"

        sem_top_score = semantic_results[0].score if semantic_results else 0.0

        if len(result_items) == 0:
            is_abstention = True
            status = "no_results"
            abstention_reason = "No candidates met the minimum RRF threshold."
        elif has_bm25 and bm25_resp is not None and bm25_resp.is_abstention:
            # BM25 branch evaluated the corpus and abstained (score < 14.5 or term coverage < 40%).
            # If semantic branch does not show strong confidence (score >= sem_conf_thresh),
            # preserve BM25's abstention signal instead of answering from weak vector proximity.
            if sem_top_score < sem_conf_thresh:
                is_abstention = True
                status = "abstained"
                abstention_reason = (
                    f"Hybrid abstention: BM25 branch abstained ({bm25_resp.abstention_reason}) "
                    f"and semantic candidate score ({sem_top_score:.4f}) did not exceed confidence threshold ({sem_conf_thresh:.2f})."
                )
        elif not has_bm25 and has_semantic and semantic_results:
            if sem_top_score < sem_conf_thresh:
                is_abstention = True
                status = "abstained"
                abstention_reason = (
                    f"Top semantic candidate score ({sem_top_score:.4f}) is below confidence threshold ({sem_conf_thresh:.2f})."
                )

        return RetrievalResponse(
            query=query,
            total_candidates_scored=total_candidates_scored,
            total_results=len(result_items),
            results=result_items,
            applied_filters=filters,
            is_abstention=is_abstention,
            abstention_threshold=min_rrf_threshold,
            abstention_reason=abstention_reason,
            retrieval_method="hybrid_rrf",
            status=status,
            rrf_k=effective_k,
            branch_candidate_counts=branch_counts,
        )

    # API compatibility alias
    retrieve = search

