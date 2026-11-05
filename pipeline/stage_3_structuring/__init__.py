"""
Stage 3: Structuring & Intent Classification Pipeline.
Enforces the Unified Knowledge Schema via Pydantic and applies Gemini structured outputs.
"""
from .schemas import UnifiedChunk, SourceMetadata, ClassificationMetadata, ContentPayload, ChunkMetadata
from .intent_classifier import IntentClassifier

__all__ = [
    "UnifiedChunk",
    "SourceMetadata",
    "ClassificationMetadata",
    "ContentPayload",
    "ChunkMetadata",
    "IntentClassifier",
]
