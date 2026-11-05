"""
Local Embedding Engine for HUDCO Financial Semantic Retrieval.
File: pipeline/retrieval/embedding.py

Provides a memory-bounded, locally executed embedding service using
SentenceTransformers with GPU acceleration and automatic CPU fallback.
L2-normalizes all output vectors so that dot product equals cosine similarity.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional, Union
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DEFAULT_DIMENSION = 384
DEFAULT_BATCH_SIZE = 64


class LocalEmbeddingEngine:
    """
    Manages loading, inference, and memory-bounded batching for local embeddings.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        model_revision: Optional[str] = DEFAULT_MODEL_REVISION,
        device: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        normalize_embeddings: bool = True,
    ):
        self.model_name = model_name
        self.model_revision = model_revision
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self._model = None
        self._device = device
        self._dimension = DEFAULT_DIMENSION

    @property
    def device(self) -> str:
        if self._device:
            return self._device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    @property
    def dimension(self) -> int:
        return self._dimension

    def get_embedding_dimension(self) -> int:
        """Compatibility accessor matching sentence-transformers and index contracts."""
        return self.dimension

    def _ensure_model(self):
        if self._model is None:
            t0 = time.perf_counter()
            dev = self.device
            logger.info(
                f"Loading embedding model '{self.model_name}' (rev={self.model_revision}) onto device '{dev}'..."
            )
            from sentence_transformers import SentenceTransformer
            kwargs = {"device": dev}
            if self.model_revision:
                kwargs["revision"] = self.model_revision
            self._model = SentenceTransformer(self.model_name, **kwargs)
            if hasattr(self._model, "get_embedding_dimension"):
                self._dimension = self._model.get_embedding_dimension() or DEFAULT_DIMENSION
            else:
                self._dimension = self._model.get_sentence_embedding_dimension() or DEFAULT_DIMENSION
            t_load = round(time.perf_counter() - t0, 3)
            logger.info(f"Embedding model loaded successfully in {t_load}s (dim={self._dimension}, device={dev}).")

    def encode_texts(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """
        Encodes a list of texts into L2-normalized float32 numpy arrays.
        Memory-bounded: batches inference without allocating full intermediate tensors in VRAM.
        """
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        self._ensure_model()
        bs = batch_size or self.batch_size

        embeddings = self._model.encode(
            texts,
            batch_size=bs,
            show_progress_bar=show_progress_bar,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32)

    def encode_query(self, query: str) -> np.ndarray:
        """
        Encodes a single query string into a 1D L2-normalized vector.
        """
        if not query or not query.strip():
            return np.zeros(self.dimension, dtype=np.float32)

        self._ensure_model()
        vec = self._model.encode(
            query.strip(),
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vec.astype(np.float32).flatten()
