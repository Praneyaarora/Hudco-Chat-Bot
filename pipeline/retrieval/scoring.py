"""
Scoring, Recency Weighting, and Grounding Sufficiency Engine for HUDCO Enterprise AI.
File: pipeline/retrieval/scoring.py

Provides:
1. Dynamic Recency Scoring: Always prioritizes the latest annual reports (FY 2025-26 > 2024-25 > ...)
   unless the user explicitly requests historical data for a specific year.
2. Normalized Relevance Assessment: Unifies BM25, semantic cosine similarity, and RRF scores.
3. Composite Relatability Metric: Computes a transparent, reproducible score in [0.0, 1.0].
4. Grounding Sufficiency Evaluator: Enforces strict chunk-first priority; prevents unnecessary
   Tavily / web search fallback when local reports contain high-confidence, verified evidence.
5. Diagnostic Telemetry: Exposes full score breakdowns for developer inspection and auditability.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Any, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Known reference timeline for HUDCO annual reports corpus
LATEST_CORPUS_YEAR: int = 2026  # ar26.pdf corresponds to FY 2025-26 (56th Annual Report)
OLDEST_CORPUS_YEAR: int = 2015  # ar15.pdf corresponds to FY 2014-15

# Recency decay weights for non-targeted (current/general) queries
# Maps end fiscal year (e.g. 2026 for FY 2025-26) to base recency score [0.0, 1.0]
YEAR_RECENCY_WEIGHTS: Dict[int, Tuple[float, str]] = {
    2026: (1.00, "Latest Verified (FY 2025-26)"),
    2025: (0.88, "Recent (FY 2024-25)"),
    2024: (0.76, "Recent (FY 2023-24)"),
    2023: (0.64, "Prior (FY 2022-23)"),
    2022: (0.52, "Prior (FY 2021-22)"),
    2021: (0.40, "Historical (FY 2020-21)"),
    2020: (0.30, "Historical (FY 2019-20)"),
    2019: (0.22, "Archive (FY 2018-19)"),
    2018: (0.15, "Archive (FY 2017-18)"),
    2017: (0.10, "Archive (FY 2016-17)"),
    2016: (0.06, "Archive (FY 2015-16)"),
    2015: (0.03, "Archive (FY 2014-15)"),
}

# Thresholds for Grounding Sufficiency & Web Fallback Gating
DEFAULT_SUFFICIENCY_THRESHOLD: float = 0.40   # Minimum composite score for a chunk to be considered reliable
MIN_RELEVANCE_GATE: float = 0.28              # Minimum semantic/BM25 relevance to qualify
LATEST_YEAR_BONUS: float = 0.05               # Boost bonus awarded to latest report (FY 2025-26)


def parse_fiscal_year(item_or_meta: Any) -> Optional[int]:
    """
    Extracts the four-digit ending fiscal year from an item, metadata dict, or string.
    Examples:
        '2025-26' -> 2026
        '2024-2025' -> 2025
        'FY 2023-24' -> 2024
        'ar26.pdf' / 'doc_ar26' -> 2026
        'ar18.pdf' / 'doc_ar18' -> 2018
    """
    if item_or_meta is None:
        return None

    # If passed a string directly
    if isinstance(item_or_meta, str):
        raw_str = item_or_meta
    elif isinstance(item_or_meta, dict):
        raw_str = (
            item_or_meta.get("fiscal_year")
            or item_or_meta.get("document_id")
            or item_or_meta.get("source_filename")
            or ""
        )
    else:
        # Object attribute lookup
        raw_str = (
            getattr(item_or_meta, "fiscal_year", None)
            or getattr(item_or_meta, "document_id", None)
            or getattr(item_or_meta, "source_filename", None)
            or ""
        )

    if not raw_str:
        return None

    raw_str = str(raw_str).strip()

    # Pattern 1: e.g. 2025-26, 2023-24, 2024-2025
    m_span = re.search(r"(?:19|20)(\d{2})\s*[-–/]\s*(?:(?:19|20)?(\d{2}))", raw_str)
    if m_span:
        start_yy = int(m_span.group(1))
        end_yy = int(m_span.group(2))
        century = 2000 if end_yy < 70 else 1900
        return century + end_yy

    # Pattern 2: Single 4-digit year like 2026, 2025
    m_single = re.search(r"\b(20\d{2})\b", raw_str)
    if m_single:
        return int(m_single.group(1))

    # Pattern 3: ar26, doc_ar26, ar26.pdf
    m_ar = re.search(r"(?:^|[\W_])ar(\d{2})(?:[\W_]|$)", raw_str.lower())
    if m_ar:
        yy = int(m_ar.group(1))
        return 2000 + yy

    return None


def detect_query_target_year(query: str) -> Optional[int]:
    """
    Detects if the user is explicitly requesting historical data for a specific year.
    Examples:
        'What was the profit in 2018?' -> 2018
        'Tell me about FY 2021-22 loan sanctions' -> 2022
        '2016 balance sheet highlights' -> 2016
        'Who is the CMD of HUDCO?' -> None (wants current / latest)
        'HUDCO contact number' -> None (wants current / latest)
    """
    if not query:
        return None

    q = query.lower()

    # Match FY 2021-22 or 2021-2022
    m_fy = re.search(r"(?:fy|financial\s+year|year)\s*(?:19|20)?(\d{2})\s*[-–/]\s*(?:(?:19|20)?(\d{2}))", q)
    if m_fy:
        end_yy = int(m_fy.group(2))
        return 2000 + end_yy

    # Match explicit "in 2019", "for 2020", "during 2017", "2018 annual report"
    m_explicit = re.search(r"\b(?:in|for|during|of|dated|year)\s+(20\d{2})\b", q)
    if m_explicit:
        return int(m_explicit.group(1))

    # Match standalone historical 4-digit year <= 2024 (past reference)
    m_standalone = re.findall(r"\b(201\d|202[0-4])\b", q)
    if m_standalone:
        return int(m_standalone[0])

    return None


def calculate_recency_score(
    item_year: Optional[int],
    target_year: Optional[int] = None,
) -> Tuple[float, str]:
    """
    Calculates the recency score in [0.0, 1.0] and an explainable tier label.
    If target_year is provided, scores closeness to the targeted historical year.
    If target_year is None, awards highest value to latest information (FY 2025-26).
    """
    if target_year is not None:
        if item_year is None:
            return 0.40, f"Undated (Target: FY {target_year})"
        diff = abs(item_year - target_year)
        if diff == 0:
            return 1.00, f"Exact Target Year Match (FY {target_year})"
        elif diff == 1:
            return 0.75, f"Adjacent Year (FY {item_year} vs Target {target_year})"
        elif diff == 2:
            return 0.50, f"Near Year (FY {item_year} vs Target {target_year})"
        else:
            return max(0.05, 0.35 - (diff - 2) * 0.08), f"Distant Year (FY {item_year} vs Target {target_year})"

    # Default Mode: Prioritize latest verified data always
    if item_year is None:
        return 0.45, "Undated / General"

    if item_year in YEAR_RECENCY_WEIGHTS:
        return YEAR_RECENCY_WEIGHTS[item_year]

    if item_year >= LATEST_CORPUS_YEAR:
        return 1.00, f"Latest Data (FY {item_year})"
    elif item_year < OLDEST_CORPUS_YEAR:
        return 0.02, f"Historical Archive (FY {item_year})"

    # Linear fallback interpolation
    span = LATEST_CORPUS_YEAR - OLDEST_CORPUS_YEAR
    normalized = max(0.05, min(1.0, (item_year - OLDEST_CORPUS_YEAR) / span))
    return round(normalized, 4), f"Report (FY {item_year})"


def calculate_relevance_score(item: Any) -> float:
    """
    Extracts and normalizes the raw retrieval relevance score from an item.
    Handles BM25 scores, semantic cosine similarity, and RRF fused scores.
    Returns float in [0.0, 1.0].
    """
    # 1. Semantic score is already bounded [-1.0, 1.0], typically [0.3, 0.9]
    sem_score = getattr(item, "semantic_score", None) if not isinstance(item, dict) else item.get("semantic_score")
    if sem_score is not None:
        try:
            s_val = float(sem_score)
            if s_val > 0.0:
                # Map [0.25, 0.85] -> [0.0, 1.0]
                norm_sem = min(1.0, max(0.0, (s_val - 0.25) / 0.60))
            else:
                norm_sem = 0.0
        except (ValueError, TypeError):
            norm_sem = 0.0
    else:
        norm_sem = None

    # 2. BM25 score normalization (typical range: 10 - 45)
    bm25_score = getattr(item, "bm25_score", None) if not isinstance(item, dict) else item.get("bm25_score")
    term_cov = getattr(item, "term_coverage", 0.5) if not isinstance(item, dict) else item.get("term_coverage", 0.5)
    if bm25_score is not None:
        try:
            b_val = float(bm25_score)
            # Map BM25 0-35 to 0.0 - 1.0, weighted by term coverage
            cov_factor = 0.6 + 0.4 * min(1.0, max(0.0, float(term_cov or 0.5)))
            norm_bm25 = min(1.0, max(0.0, (b_val / 32.0))) * cov_factor
        except (ValueError, TypeError):
            norm_bm25 = 0.0
    else:
        norm_bm25 = None

    # 3. RRF fused score (typical range 0.015 - 0.0328)
    rrf_score = getattr(item, "rrf_score", None) if not isinstance(item, dict) else item.get("rrf_score")
    if rrf_score is not None:
        try:
            r_val = float(rrf_score)
            # Max possible RRF with k=60 across 2 branches is 2 * (1/61) = 0.03278
            norm_rrf = min(1.0, max(0.0, r_val / 0.0328))
        except (ValueError, TypeError):
            norm_rrf = 0.0
    else:
        norm_rrf = None

    # Generic score fallback
    raw_score = getattr(item, "score", 0.5) if not isinstance(item, dict) else item.get("score", 0.5)
    try:
        gen_score = float(raw_score or 0.5)
        # If score is already in [0, 1]
        if 0.0 <= gen_score <= 1.0:
            norm_gen = gen_score
        else:
            norm_gen = min(1.0, max(0.0, gen_score / 35.0))
    except (ValueError, TypeError):
        norm_gen = 0.5

    # Fuse available branch metrics
    components = []
    if norm_rrf is not None:
        components.append(norm_rrf * 1.0)
    if norm_sem is not None:
        components.append(norm_sem * 1.1)  # Semantic gets slight boost for intent alignment
    if norm_bm25 is not None:
        components.append(norm_bm25 * 0.9)

    if components:
        # Weighted mean of top components
        rel_val = sum(components) / len(components)
    else:
        rel_val = norm_gen

    return round(min(1.0, max(0.0, rel_val)), 4)


def compute_composite_score(
    item: Any,
    query: str = "",
    target_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Computes a comprehensive, explainable score combining relevance and recency:
    - S_composite = 0.60 * S_relevance + 0.40 * S_recency (+ bonus for latest verified data).
    - If relevance is very low (< 0.25), recency cannot artificially promote off-topic chunks.
    - If user did not specify a historical year, latest information always outscores older information.
    """
    effective_target_year = target_year if target_year is not None else detect_query_target_year(query)
    item_year = parse_fiscal_year(item)

    relevance_score = calculate_relevance_score(item)
    recency_score, recency_tier = calculate_recency_score(item_year, effective_target_year)

    # Base weighted combination: 60% relevance + 40% recency
    raw_composite = (0.60 * relevance_score) + (0.40 * recency_score)

    # Award latest-year bonus only if chunk has credible relevance
    bonus = 0.0
    if effective_target_year is None and item_year == LATEST_CORPUS_YEAR and relevance_score >= 0.30:
        bonus = LATEST_YEAR_BONUS
        raw_composite += bonus

    # Relevance gate: do not let an irrelevant chunk rank high solely due to recency
    if relevance_score < MIN_RELEVANCE_GATE:
        composite_score = min(relevance_score * 1.2, raw_composite * 0.6)
    else:
        composite_score = min(1.0, raw_composite)

    composite_score = round(composite_score, 4)

    return {
        "composite_score": composite_score,
        "relevance_score": relevance_score,
        "recency_score": recency_score,
        "recency_tier": recency_tier,
        "fiscal_year_num": item_year,
        "bonus_applied": bonus,
        "target_year": effective_target_year,
        "formula": f"0.60 * {relevance_score:.2f} (rel) + 0.40 * {recency_score:.2f} (rec) + {bonus:.2f} (bonus)",
    }


def rerank_chunks_with_recency(
    results: List[Any],
    query: str = "",
    top_k: int = 5,
) -> List[Any]:
    """
    Scores and re-ranks candidate chunks, giving highest priority to latest data
    and relevant information. Attaches score breakdown telemetry to every item.
    """
    if not results:
        return []

    target_year = detect_query_target_year(query)
    scored_items = []

    for idx, item in enumerate(results):
        score_info = compute_composite_score(item, query, target_year=target_year)

        # Mutate or wrap item with transparent scoring telemetry
        if isinstance(item, dict):
            item["composite_score"] = score_info["composite_score"]
            item["relevance_score"] = score_info["relevance_score"]
            item["recency_score"] = score_info["recency_score"]
            item["recency_tier"] = score_info["recency_tier"]
            item["scoring_breakdown"] = score_info
            item["score"] = score_info["composite_score"]
        else:
            setattr(item, "composite_score", score_info["composite_score"])
            setattr(item, "relevance_score", score_info["relevance_score"])
            setattr(item, "recency_score", score_info["recency_score"])
            setattr(item, "recency_tier", score_info["recency_tier"])
            setattr(item, "scoring_breakdown", score_info)
            setattr(item, "score", score_info["composite_score"])

        scored_items.append((score_info["composite_score"], score_info["relevance_score"], idx, item))

    # Deterministic sorting: (-composite_score, -relevance_score, original_rank)
    scored_items.sort(key=lambda t: (-t[0], -t[1], t[2]))

    reranked = []
    for new_rank, (_, _, _, item) in enumerate(scored_items, start=1):
        if isinstance(item, dict):
            item["rank"] = new_rank
            item["evidence_index"] = new_rank
        else:
            setattr(item, "rank", new_rank)
            if hasattr(item, "evidence_index"):
                setattr(item, "evidence_index", new_rank)
        reranked.append(item)

    return reranked[:top_k]


def evaluate_local_sufficiency(
    results: List[Any],
    min_threshold: float = DEFAULT_SUFFICIENCY_THRESHOLD,
) -> Dict[str, Any]:
    """
    Evaluates whether the retrieved local annual report chunks provide sufficient,
    high-confidence grounding for answer synthesis without needing Tavily/web search.

    Criteria for Local Sufficiency (Tavily Bypassed):
    1. Top candidate composite score >= min_threshold (default 0.40).
    2. Top candidate relevance score >= MIN_RELEVANCE_GATE (0.28).
    3. At least 1 relatable chunk found.

    If criteria are met, the local reports have high priority and Tavily is NOT called.
    """
    if not results:
        return {
            "is_sufficient": False,
            "top_composite_score": 0.0,
            "top_relevance_score": 0.0,
            "relatable_count": 0,
            "decision": "web_search_required",
            "reason": "Local retrieval yielded 0 candidates.",
        }

    top_item = results[0]
    if isinstance(top_item, dict):
        top_comp = float(top_item.get("composite_score", top_item.get("score", 0.0)))
        top_rel = float(top_item.get("relevance_score", 0.0))
        top_tier = top_item.get("recency_tier", "Unknown")
        top_doc = top_item.get("source_filename") or top_item.get("document_id") or "report"
    else:
        top_comp = float(getattr(top_item, "composite_score", getattr(top_item, "score", 0.0)))
        top_rel = float(getattr(top_item, "relevance_score", 0.0))
        top_tier = getattr(top_item, "recency_tier", "Unknown")
        top_doc = getattr(top_item, "source_filename", getattr(top_item, "document_id", "report"))

    relatable_items = []
    for it in results:
        c_score = float(it.get("composite_score", 0.0) if isinstance(it, dict) else getattr(it, "composite_score", 0.0))
        r_score = float(it.get("relevance_score", 0.0) if isinstance(it, dict) else getattr(it, "relevance_score", 0.0))
        if c_score >= min_threshold and r_score >= MIN_RELEVANCE_GATE:
            relatable_items.append(it)

    rel_count = len(relatable_items)
    is_sufficient = (top_comp >= min_threshold) and (top_rel >= MIN_RELEVANCE_GATE) and (rel_count >= 1)

    if is_sufficient:
        reason = (
            f"Local chunks provide verified groundable evidence from {top_doc} "
            f"({top_tier}, Composite Score: {top_comp:.3f} >= {min_threshold:.2f}, Relatable Chunks: {rel_count}). "
            f"Tavily web search bypassed; local reports prioritized."
        )
        decision = "use_local_chunks"
    else:
        reason = (
            f"Local chunks insufficient (Top Score: {top_comp:.3f} < {min_threshold:.2f} threshold, "
            f"Relevance: {top_rel:.3f}, Relatable Count: {rel_count}). Web search fallback permitted."
        )
        decision = "web_search_fallback"

    return {
        "is_sufficient": is_sufficient,
        "top_composite_score": top_comp,
        "top_relevance_score": top_rel,
        "relatable_count": rel_count,
        "top_recency_tier": top_tier,
        "decision": decision,
        "reason": reason,
    }
