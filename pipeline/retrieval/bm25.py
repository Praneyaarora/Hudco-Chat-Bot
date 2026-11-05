"""
Production BM25 Lexical Index for Layer 4 Retrieval.
File: pipeline/retrieval/bm25.py

Deterministic BM25Okapi implementation with table-aware indexing,
metadata filtering, per-term explanation generation, and calibrated abstention.
"""

import math
from collections import Counter
from typing import List, Dict, Tuple, Optional, Any, Set

from pipeline.core.contracts import CanonicalChunk
from pipeline.retrieval.contracts import (
    RetrievalFilter,
    RetrievalResultItem,
    RetrievalResponse,
    TableMetadata,
)
from pipeline.retrieval.table_linearizer import build_searchable_chunk_text
from pipeline.retrieval.tokenizer import tokenize

# Default Okapi BM25 parameters
DEFAULT_K1: float = 1.2
DEFAULT_B: float = 0.45
DEFAULT_ABSTENTION_THRESHOLD: float = 14.5
DEFAULT_MIN_TERM_COVERAGE: float = 0.40


class Layer4BM25Index:
    """
    In-memory BM25Okapi retrieval engine for CanonicalChunk knowledge units.
    
    Features:
    - Table-aware lexical indexing (combines markdown and linearized table rows).
    - Metadata filtering across document, section, page bounds, and table status.
    - Transparent term scoring and explanation generation.
    - Calibrated confidence thresholding for unanswerable question abstention.
    - Deterministic index rebuilds from canonical records.
    """

    def __init__(
        self,
        chunks: Optional[List[CanonicalChunk]] = None,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        abstention_threshold: float = DEFAULT_ABSTENTION_THRESHOLD,
        min_term_coverage: float = DEFAULT_MIN_TERM_COVERAGE,
    ):
        self.k1 = k1
        self.b = b
        self.abstention_threshold = abstention_threshold
        self.min_term_coverage = min_term_coverage
        
        self.chunks: List[CanonicalChunk] = []
        self.searchable_texts: List[str] = []
        self.doc_lens: List[int] = []
        self.doc_term_freqs: List[Counter] = []
        self.inverted_index: Dict[str, List[Tuple[int, int]]] = {}
        self.doc_freq: Counter = Counter()
        self.idf: Dict[str, float] = {}
        self.N: int = 0
        self.avg_doc_len: float = 1.0

        if chunks:
            self.build_index(chunks)

    def build_index(self, chunks: List[CanonicalChunk]) -> None:
        """
        Builds the inverted index and precomputes term frequencies and IDF.
        Deterministic and idempotent: duplicate chunk IDs are rejected.
        """
        seen_ids: Set[str] = set()
        clean_chunks: List[CanonicalChunk] = []

        for c in chunks:
            if c.chunk_id in seen_ids:
                raise ValueError(f"Duplicate chunk ID '{c.chunk_id}' encountered during index build.")
            seen_ids.add(c.chunk_id)
            clean_chunks.append(c)

        self.chunks = clean_chunks
        self.N = len(clean_chunks)
        self.searchable_texts = []
        self.doc_lens = []
        self.doc_term_freqs = []
        self.doc_freq = Counter()
        self.inverted_index = {}

        # Pre-pass: track sequential subsection headings and directory contact bindings
        chunk_subheadings: List[Optional[str]] = [None] * self.N
        companion_contacts: Dict[int, List[str]] = {}
        current_subh: Optional[str] = None
        current_section: Optional[str] = None

        for i, c in enumerate(self.chunks):
            if c.section_id != current_section:
                current_section = c.section_id
                current_subh = None

            content_s = c.content.strip()
            # Recognize structural subsection boundary markers
            if content_s in ("REGIONAL OFFICES", "DEVELOPMENT OFFICES", "OTHER OFFICES", "HEAD OFFICE", "REGISTERED OFFICE"):
                current_subh = content_s

            chunk_subheadings[i] = current_subh

            # Bind companion contact lines (Email:, Tel:, Phone:) with preceding directory entry
            if content_s.startswith(("Email:", "Tel:", "Tel.:", "Phone:")):
                for prev_idx in range(i - 1, max(-1, i - 4), -1):
                    prev_c = self.chunks[prev_idx]
                    if prev_c.section_id == c.section_id and prev_c.physical_page == c.physical_page:
                        prev_content = prev_c.content.strip()
                        if not prev_content.startswith(("Email:", "Tel:", "Tel.:", "Phone:")):
                            if prev_idx not in companion_contacts:
                                companion_contacts[prev_idx] = []
                            companion_contacts[prev_idx].append(content_s)
                            break

        for doc_idx, chunk in enumerate(self.chunks):
            # Combine ancestor headings with active subsection heading
            ancestors = list(chunk.ancestor_headings) if chunk.ancestor_headings else []
            subh = chunk_subheadings[doc_idx]
            if subh and subh not in ancestors:
                if ancestors and ancestors[0] == chunk.section_title:
                    ancestors.insert(1, subh)
                else:
                    ancestors.append(subh)

            associated_text = "\n".join(companion_contacts.get(doc_idx, []))

            # Combine content with linearized table rows, breadcrumbs, and directory fields
            searchable_text = build_searchable_chunk_text(
                content=chunk.content,
                structured_tables=chunk.structured_tables,
                section_title=chunk.section_title,
                ancestor_headings=ancestors,
                associated_text=associated_text,
            )
            self.searchable_texts.append(searchable_text)

            tokens = tokenize(searchable_text)
            self.doc_lens.append(len(tokens))

            tf = Counter(tokens)
            self.doc_term_freqs.append(tf)

            for term, count in tf.items():
                self.doc_freq[term] += 1
                if term not in self.inverted_index:
                    self.inverted_index[term] = []
                self.inverted_index[term].append((doc_idx, count))


        self.avg_doc_len = sum(self.doc_lens) / self.N if self.N > 0 else 1.0

        # Precompute Robertson-Spärck Jones IDF: ln(1 + (N - df + 0.5) / (df + 0.5))
        self.idf = {}
        for term, df in self.doc_freq.items():
            self.idf[term] = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def _matches_filter(self, chunk: CanonicalChunk, filters: Optional[RetrievalFilter]) -> bool:
        """Evaluates whether a chunk satisfies the specified metadata filter."""
        include_stale = filters.include_stale if filters else False
        if not include_stale and chunk.is_stale:
            return False

        if not filters:
            return True

        if filters.document_id and chunk.document_id != filters.document_id:
            return False

        if filters.version_id and chunk.version_id != filters.version_id:
            return False

        if filters.section_id and chunk.section_id != filters.section_id:
            return False

        if filters.section_title_contains and filters.section_title_contains.lower() not in chunk.section_title.lower():
            return False

        # Multi-page awareness: chunk matches page window if any page in chunk.physical_pages matches,
        # or if chunk.physical_page falls in [min_page, max_page]
        chunk_pages = getattr(chunk, "physical_pages", None) or [chunk.physical_page]
        if filters.min_physical_page is not None and max(chunk_pages) < filters.min_physical_page:
            return False

        if filters.max_physical_page is not None and min(chunk_pages) > filters.max_physical_page:
            return False

        if filters.has_table is not None and chunk.has_table != filters.has_table:
            return False

        chunk_fy = getattr(chunk, "fiscal_year", None)
        if filters.fiscal_year is not None and chunk_fy != filters.fiscal_year:
            return False

        if filters.fiscal_years is not None and chunk_fy not in filters.fiscal_years:
            return False

        return True


    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[RetrievalFilter] = None,
        score_threshold: Optional[float] = None,
        min_term_coverage: Optional[float] = None,
    ) -> RetrievalResponse:
        """
        Executes BM25 query against indexed chunks with metadata filtering.
        
        Returns:
            RetrievalResponse envelope with ranked candidates and abstention status.
        """
        if filters is not None:
            RetrievalFilter.validate_filter(filters)

        threshold = score_threshold if score_threshold is not None else self.abstention_threshold
        min_coverage = min_term_coverage if min_term_coverage is not None else self.min_term_coverage

        query_tokens = tokenize(query)

        # Handle empty query
        if not query_tokens or self.N == 0:
            return RetrievalResponse(
                query=query,
                total_candidates_scored=0,
                total_results=0,
                results=[],
                applied_filters=filters,
                is_abstention=True,
                abstention_threshold=threshold,
                abstention_reason="Empty query after normalization and stopword removal." if not query_tokens else "Index is empty.",
            )

        unique_query_terms = set(query_tokens)
        num_query_terms = len(unique_query_terms)

        # Gather candidate document indices via inverted index
        candidate_indices: Set[int] = set()
        for term in unique_query_terms:
            if term in self.inverted_index:
                for doc_idx, _ in self.inverted_index[term]:
                    candidate_indices.add(doc_idx)

        scored_candidates: List[Tuple[int, float, List[str], float, Dict[str, float]]] = []

        for doc_idx in candidate_indices:
            chunk = self.chunks[doc_idx]
            if not self._matches_filter(chunk, filters):
                continue

            doc_len = self.doc_lens[doc_idx]
            tf_map = self.doc_term_freqs[doc_idx]

            doc_score = 0.0
            matched_terms: List[str] = []
            term_contributions: Dict[str, float] = {}

            # BM25 document length normalization component
            len_norm = 1.0 - self.b + self.b * (doc_len / self.avg_doc_len)

            for q_term in unique_query_terms:
                if q_term in tf_map:
                    tf = tf_map[q_term]
                    idf_val = self.idf.get(q_term, 0.0)
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * len_norm
                    term_score = idf_val * (numerator / denominator)

                    doc_score += term_score
                    matched_terms.append(q_term)
                    term_contributions[q_term] = round(term_score, 3)

            coverage = len(matched_terms) / num_query_terms if num_query_terms > 0 else 0.0

            if doc_score > 0.0:
                scored_candidates.append((doc_idx, doc_score, matched_terms, coverage, term_contributions))

        # Sort candidates descending by score
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scored_candidates[:top_k]

        results: List[RetrievalResultItem] = []
        for rank_idx, (doc_idx, score, matched, coverage, contributions) in enumerate(top_candidates, start=1):
            chunk = self.chunks[doc_idx]

            # Linearize table metadata if present
            tbl_meta: Optional[List[TableMetadata]] = None
            if chunk.structured_tables:
                tbl_meta = [
                    TableMetadata(
                        table_id=st.table_id,
                        caption=st.caption,
                        unit_of_measure=st.unit_of_measure,
                        headers=st.headers,
                        row_count=st.row_count,
                        col_count=st.col_count,
                    )
                    for st in chunk.structured_tables
                ]

            contrib_str = ", ".join(f"{k}: {v}" for k, v in contributions.items())
            explanation = (
                f"Matched {len(matched)} of {num_query_terms} terms ({coverage:.1%}): "
                f"[{contrib_str}]"
            )

            # Compute accurate citation provenance for single and multi-page chunks
            all_phys_pages = getattr(chunk, "physical_pages", []) or [chunk.physical_page]
            if filters and (filters.min_physical_page is not None or filters.max_physical_page is not None):
                target_pages = [
                    p for p in all_phys_pages
                    if (filters.min_physical_page is None or p >= filters.min_physical_page)
                    and (filters.max_physical_page is None or p <= filters.max_physical_page)
                ]
                if target_pages:
                    cited_pages = target_pages
                    cited_page = target_pages[0]
                    c_label = f"Page {cited_page}" if len(target_pages) == 1 else f"Pages {min(target_pages)}-{max(target_pages)}"
                else:
                    cited_pages = all_phys_pages
                    cited_page = chunk.physical_page
                    c_label = chunk.get_citation_label() if hasattr(chunk, "get_citation_label") else f"Page {chunk.physical_page}"
            else:
                cited_pages = all_phys_pages
                cited_page = chunk.physical_page
                c_label = chunk.get_citation_label() if hasattr(chunk, "get_citation_label") else f"Page {chunk.physical_page}"

            results.append(
                RetrievalResultItem(
                    rank=rank_idx,
                    chunk_id=chunk.chunk_id,
                    score=round(score, 4),
                    matched_terms=matched,
                    term_coverage=round(coverage, 4),
                    explanation=explanation,
                    document_id=chunk.document_id,
                    version_id=chunk.version_id,
                    source_id=chunk.source_id,
                    source_filename=chunk.source_filename,
                    section_id=chunk.section_id,
                    section_title=chunk.section_title,
                    physical_page=chunk.physical_page,
                    physical_page_end=getattr(chunk, "physical_page_end", None),
                    physical_pages=all_phys_pages,
                    printed_page=chunk.printed_page,
                    printed_page_end=getattr(chunk, "printed_page_end", None),
                    printed_pages=getattr(chunk, "printed_pages", [chunk.printed_page] if chunk.printed_page else []),
                    has_table=chunk.has_table,
                    table_metadata=tbl_meta,
                    content=chunk.content,
                    content_sha256=chunk.content_sha256,
                    fiscal_year=getattr(chunk, "fiscal_year", None),
                    reporting_period=getattr(chunk, "reporting_period", None),
                    citation_page=cited_page,
                    citation_pages=cited_pages,
                    citation_label=c_label,
                    retrieval_method="bm25",
                    bm25_score=round(score, 4),
                    bm25_rank=rank_idx,
                )
            )

        # Calibrated abstention check:
        # Abstains if no results, top score < threshold, or query term coverage < min_coverage
        is_abstention = False
        abstention_reason: Optional[str] = None
        status = "evidence_available"

        if not results:
            is_abstention = True
            status = "no_results"
            abstention_reason = "No candidate chunks matched any query terms."
        elif results[0].score < threshold:
            is_abstention = True
            status = "abstained"
            abstention_reason = (
                f"Top candidate score ({results[0].score:.2f}) is below calibrated threshold ({threshold:.2f})."
            )
        elif results[0].term_coverage < min_coverage:
            is_abstention = True
            status = "abstained"
            abstention_reason = (
                f"Top candidate term coverage ({results[0].term_coverage:.1%}) is below calibrated threshold ({min_coverage:.1%})."
            )

        return RetrievalResponse(
            query=query,
            total_candidates_scored=len(scored_candidates),
            total_results=len(results),
            results=results,
            applied_filters=filters,
            is_abstention=is_abstention,
            abstention_threshold=threshold,
            abstention_reason=abstention_reason,
            retrieval_method="bm25",
            status=status,
        )

    # API compatibility alias
    search = retrieve


