"""
HUDCO Evaluation Harness Package.
Provides page-grounded extraction, section-aware chunking, BM25 retrieval, and benchmark runners.
"""

from .schemas import (
    PageExtractionRecord,
    EvaluationChunk,
    EvaluationQuestion,
    RetrievalResultItem,
    QuestionRetrievalEvaluation,
    EvaluationRunReport,
)
from .retriever_bm25 import BM25Retriever
from .extractor import EvaluationDocumentExtractor
from .chunker import EvaluationChunker

__all__ = [
    "PageExtractionRecord",
    "EvaluationChunk",
    "EvaluationQuestion",
    "RetrievalResultItem",
    "QuestionRetrievalEvaluation",
    "EvaluationRunReport",
    "BM25Retriever",
    "EvaluationDocumentExtractor",
    "EvaluationChunker",
]
