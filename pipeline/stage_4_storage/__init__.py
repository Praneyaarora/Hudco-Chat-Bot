"""
Stage 4: Dual Storage Architecture & Indexing.
Loads semantic vectors into ChromaDB and structured document registries into PostgreSQL/SQLAlchemy.
"""
from .chroma_loader import ChromaVectorLoader
from .db_registry import Base, DocumentRegistry, ChunkRegistry, OfficeDirectory

__all__ = [
    "ChromaVectorLoader",
    "Base",
    "DocumentRegistry",
    "ChunkRegistry",
    "OfficeDirectory",
]
