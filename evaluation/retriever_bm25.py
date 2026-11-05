"""
BM25 Lexical Retrieval Module for HUDCO Evaluation Harness.
Self-contained, deterministic BM25Okapi implementation with query term inspection.
"""

import math
import re
from collections import Counter
from typing import List, Dict, Any, Tuple
from evaluation.config import BM25_K1, BM25_B, DEFAULT_TOP_K
from evaluation.schemas import EvaluationChunk, RetrievalResultItem

# Tokenizer pattern matching alphanumeric words of length >= 2
WORD_TOKEN_REGEX = re.compile(r"\b[A-Za-z0-9_]{2,}\b")

# Optional common English stopwords
STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "through", "after", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "this", "that", "these", "those", "it", "its", "as", "if"
}


def tokenize(text: str) -> List[str]:
    """
    Deterministic tokenizer: lowercases, extracts alphanumeric words (>= 2 chars),
    and filters common syntactic stopwords.
    """
    if not text:
        return []
    words = WORD_TOKEN_REGEX.findall(text.lower())
    return [w for w in words if w not in STOPWORDS]


class BM25Retriever:
    """
    In-memory BM25Okapi index over a collection of EvaluationChunk objects.
    Provides transparent scoring and per-term explanations.
    """

    def __init__(
        self,
        chunks: List[EvaluationChunk],
        k1: float = BM25_K1,
        b: float = BM25_B,
    ):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.N = len(chunks)

        # Precompute document lengths, average length, and term statistics
        self.doc_lens: List[int] = []
        self.doc_term_freqs: List[Counter] = []
        self.doc_freq: Counter = Counter()

        for chunk in chunks:
            tokens = tokenize(chunk.content)
            self.doc_lens.append(len(tokens))
            tf = Counter(tokens)
            self.doc_term_freqs.append(tf)
            for term in tf:
                self.doc_freq[term] += 1

        self.avg_doc_len = sum(self.doc_lens) / self.N if self.N > 0 else 1.0

        # Precompute IDF for each term: ln(1 + (N - df + 0.5) / (df + 0.5))
        self.idf: Dict[str, float] = {}
        for term, df in self.doc_freq.items():
            self.idf[term] = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[RetrievalResultItem]:
        """
        Retrieves top_k ranked chunks for the given query with transparent score explanations.
        """
        query_tokens = tokenize(query)
        if not query_tokens or self.N == 0:
            return []

        scores: List[Tuple[int, float, List[str], Dict[str, float]]] = []

        for idx in range(self.N):
            doc_len = self.doc_lens[idx]
            tf_map = self.doc_term_freqs[idx]

            doc_score = 0.0
            matched_terms = []
            term_contributions: Dict[str, float] = {}

            # Calculate BM25 score
            len_norm = 1.0 - self.b + self.b * (doc_len / self.avg_doc_len)

            for q_term in set(query_tokens):
                if q_term in tf_map:
                    tf = tf_map[q_term]
                    idf_val = self.idf.get(q_term, 0.0)
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * len_norm
                    term_score = idf_val * (numerator / denominator)

                    doc_score += term_score
                    matched_terms.append(q_term)
                    term_contributions[q_term] = round(term_score, 3)

            if doc_score > 0.0:
                scores.append((idx, doc_score, matched_terms, term_contributions))

        # Sort descending by score
        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        results: List[RetrievalResultItem] = []
        for rank_idx, (doc_idx, score, matched, contributions) in enumerate(top_results):
            chunk = self.chunks[doc_idx]

            # Build human-readable explanation
            contrib_str = ", ".join([f"{k}: {v}" for k, v in contributions.items()])
            explanation = f"Matched {len(matched)} query terms ({matched}) with term scores: [{contrib_str}]"

            results.append(
                RetrievalResultItem(
                    rank=rank_idx + 1,
                    chunk_id=chunk.chunk_id,
                    score=round(score, 4),
                    matched_terms=matched,
                    explanation=explanation,
                    document_id=chunk.document_id,
                    section_id=chunk.section_id,
                    section_title=chunk.section_title,
                    physical_page=chunk.physical_page,
                    printed_page=chunk.printed_page,
                    has_table=chunk.has_table,
                    text=chunk.content,
                )
            )

        return results
