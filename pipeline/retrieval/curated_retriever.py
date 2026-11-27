"""
Curated Official HUDCO Links Retriever.
File: pipeline/retrieval/curated_retriever.py

Provides in-memory BM25 lexical and keyword matching over official HUDCO web pages
and documents (Board Leadership, Management Team, Corporate Office, Contacts, AGM,
Organogram, Web Directory, FAQs).
Grants top recency weighting (1.02 to 1.20) so verified live portal information
takes precedence over older historical reports.
"""

import os
import re
import math
import json
import logging
from typing import List, Dict, Any, Optional

from pipeline.retrieval.contracts import RetrievalResultItem, TableMetadata

logger = logging.getLogger("QwenWorker")


class CuratedLinksRetriever:
    """
    Retrieves and ranks chunks from official HUDCO live website sources.
    Loads data from data/curated_links/official_hudco_links.json.
    """

    def __init__(self, json_path: Optional[str] = None):
        if json_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            json_path = os.path.join(base_dir, "data", "curated_links", "official_hudco_links.json")
        self.json_path = os.path.abspath(json_path)
        self.chunks: List[Dict[str, Any]] = []
        self._doc_tokens: List[List[str]] = []
        self._idf: Dict[str, float] = {}
        self._avg_dl: float = 0.0
        self._is_loaded: bool = False
        self._load_and_index()

    def _tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        tokens = re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())
        return tokens

    def _load_and_index(self) -> None:
        if not os.path.exists(self.json_path):
            logger.warning(f"Curated links JSON not found at {self.json_path}. CuratedLinksRetriever is empty.")
            return

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.chunks = data.get("chunks", [])
            if not self.chunks:
                logger.warning(f"No chunks found in {self.json_path}")
                return

            # Build in-memory BM25 index over title + category + content
            total_docs = len(self.chunks)
            total_len = 0
            df: Dict[str, int] = {}
            self._doc_tokens = []

            for chunk in self.chunks:
                text_corpus = f"{chunk.get('title', '')} {chunk.get('category', '')} {chunk.get('content', '')}"
                tokens = self._tokenize(text_corpus)
                self._doc_tokens.append(tokens)
                total_len += len(tokens)
                unique_terms = set(tokens)
                for t in unique_terms:
                    df[t] = df.get(t, 0) + 1

            self._avg_dl = (total_len / total_docs) if total_docs > 0 else 1.0

            # Compute IDF: ln(1 + (N - df + 0.5) / (df + 0.5))
            self._idf = {}
            for term, count in df.items():
                self._idf[term] = math.log(1.0 + (total_docs - count + 0.5) / (count + 0.5))

            self._is_loaded = True
            logger.info(f"Loaded and indexed {total_docs} curated official HUDCO chunks from {self.json_path}.")
        except Exception as exc:
            logger.error(f"Failed to load curated links from {self.json_path}: {exc}", exc_info=True)

    def retrieve(self, query: str, top_k: int = 5) -> List[RetrievalResultItem]:
        """
        Retrieves top relevant items from the official HUDCO links store.
        Scores items with BM25 + keyword coverage + recency weighting (1.02 to 1.20).
        """
        if not self._is_loaded or not self.chunks:
            return []

        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        # BM25 parameters
        k1 = 1.2
        b = 0.50

        scored_candidates = []

        for idx, (chunk, doc_toks) in enumerate(zip(self.chunks, self._doc_tokens)):
            doc_len = len(doc_toks)
            term_freqs: Dict[str, int] = {}
            for t in doc_toks:
                term_freqs[t] = term_freqs.get(t, 0) + 1

            bm25_raw = 0.0
            matched_terms = []
            for qt in q_tokens:
                if qt in term_freqs:
                    matched_terms.append(qt)
                    freq = term_freqs[qt]
                    numerator = freq * (k1 + 1.0)
                    denominator = freq + k1 * (1.0 - b + b * (doc_len / self._avg_dl))
                    bm25_raw += self._idf.get(qt, 0.5) * (numerator / denominator)

            # Keyword bonus if title explicitly matches query concepts
            title_lower = chunk.get("title", "").lower()
            category = chunk.get("category", "").lower()
            url = chunk.get("url", "").lower()

            bonus_score = 0.0
            # Leadership match
            if any(k in query.lower() for k in ["cmd", "chairman", "managing director", "director", "leadership", "board", "kulshrestha"]):
                if "leadership_board" in category or "board" in url:
                    bonus_score += 4.0
                elif "leadership_management" in category:
                    bonus_score += 2.5
            # Management match
            if any(k in query.lower() for k in ["cvo", "vigilance", "executive director", "company secretary", "management"]):
                if "leadership_management" in category:
                    bonus_score += 4.0
            # Corporate office / Head office match
            if any(k in query.lower() for k in ["corporate office", "head office", "headquarter", "address", "lodhi road", "registered office"]):
                if "corporate_office" in category or "contact_directory" in category:
                    bonus_score += 4.0
            # Contact / Grievance match
            if any(k in query.lower() for k in ["contact", "helpline", "phone", "email", "grievance", "complaint", "toll free"]):
                if "contact_directory" in category:
                    bonus_score += 4.0
            # AGM / Shareholder match
            if any(k in query.lower() for k in ["agm", "egm", "shareholder", "meeting", "dividend"]):
                if "shareholder_meetings" in category:
                    bonus_score += 4.0

            total_lexical = bm25_raw + bonus_score

            term_cov = len(set(matched_terms)) / len(set(q_tokens)) if q_tokens else 0.0

            # Only consider candidates that actually matched or had category affinity
            if total_lexical <= 0.5 and term_cov <= 0.0 and bonus_score <= 0.0:
                continue

            # Normalize relevance to [0.0, 1.0]
            norm_rel = min(1.0, max(0.0, (total_lexical / 18.0)))
            if term_cov > 0.0:
                norm_rel = (0.7 * norm_rel) + (0.3 * term_cov)
            norm_rel = round(norm_rel, 4)

            # Minimum relevance gate: if query is completely irrelevant to this link
            if norm_rel < 0.18:
                continue

            recency_score = float(chunk.get("recency_score", 1.15))
            priority_tier = chunk.get("priority_tier", "Tier 1A - Official Live Web Page")

            # Composite scoring formula: 0.60 * relevance + 0.40 * recency
            composite_score = round(min(1.0, (0.60 * norm_rel) + (0.40 * recency_score)), 4)

            scored_candidates.append({
                "chunk": chunk,
                "composite_score": composite_score,
                "relevance_score": norm_rel,
                "recency_score": recency_score,
                "recency_tier": priority_tier,
                "matched_terms": matched_terms,
                "term_coverage": term_cov,
                "bonus_score": bonus_score,
            })

        # Sort by composite_score desc, then relevance_score desc
        scored_candidates.sort(key=lambda x: (-x["composite_score"], -x["relevance_score"]))

        results: List[RetrievalResultItem] = []
        for rank, item in enumerate(scored_candidates[:top_k], start=1):
            chunk = item["chunk"]
            url = chunk.get("url", "https://hudco.org.in")
            title = chunk.get("title", "Official HUDCO Web Page")

            res_item = RetrievalResultItem(
                rank=rank,
                evidence_index=rank,
                chunk_id=chunk["chunk_id"],
                score=item["composite_score"],
                matched_terms=item["matched_terms"],
                term_coverage=item["term_coverage"],
                explanation=f"Official Live Link Match: rel={item['relevance_score']:.2f}, recency={item['recency_score']:.2f}",
                document_id="doc_hudco_official_portal",
                version_id="live",
                source_id="hudco_live_website",
                source_filename=f"HUDCO Official Portal ({url})",
                section_id=chunk.get("category", "general"),
                section_title=title,
                ancestor_headings=["HUDCO Official Portal", chunk.get("category", "")],
                physical_page=chunk.get("page", 1),
                has_table=False,
                content=chunk.get("content", ""),
                content_sha256=chunk.get("content_sha256", ""),
                fiscal_year="Live 2026",
                citation_label=f"Official Portal ({url})",
                retrieval_method="official_live_link",
                composite_score=item["composite_score"],
                relevance_score=item["relevance_score"],
                recency_score=item["recency_score"],
                recency_tier=item["recency_tier"],
                url=url,
                source_type="official_link",
                scoring_breakdown={
                    "composite_score": item["composite_score"],
                    "relevance_score": item["relevance_score"],
                    "recency_score": item["recency_score"],
                    "recency_tier": item["recency_tier"],
                    "source_type": "official_link",
                    "url": url,
                    "bonus_applied": item["bonus_score"],
                    "formula": f"0.60 * {item['relevance_score']:.2f} (rel) + 0.40 * {item['recency_score']:.2f} (rec) [Official Link Boost]",
                }
            )
            results.append(res_item)

        return results
