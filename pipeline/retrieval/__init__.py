"""
Layer 4 Retrieval Package for HUDCO Document Processing.
File: pipeline/retrieval/__init__.py

Exports:
- Layer4BM25Index: Primary in-memory lexical retrieval engine
- load_canonical_chunks: Robust chunk loader with validation and deduplication
- linearize_table, build_searchable_chunk_text: Table-aware lexical serialization
- RetrievalFilter, RetrievalResultItem, RetrievalResponse: Response data contracts
"""

from pipeline.retrieval.contracts import (
    RetrievalFilter,
    TableMetadata,
    RetrievalResultItem,
    RetrievalResponse,
)
from pipeline.retrieval.loader import (
    load_canonical_chunks,
    ChunkLoaderError,
)
from pipeline.retrieval.table_linearizer import (
    linearize_table,
    build_searchable_chunk_text,
)
from pipeline.retrieval.tokenizer import tokenize
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.semantic_search import PersistentVectorIndex
from pipeline.retrieval.hybrid_search import HybridRetriever

__all__ = [
    "Layer4BM25Index",
    "PersistentVectorIndex",
    "HybridRetriever",
    "load_canonical_chunks",
    "ChunkLoaderError",
    "linearize_table",
    "build_searchable_chunk_text",
    "tokenize",
    "RetrievalFilter",
    "TableMetadata",
    "RetrievalResultItem",
    "RetrievalResponse",
]
