"""
ChromaDB Vector Loader & Hybrid BM25 Indexer for HUDCO Knowledge Chunks.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from config.settings import settings
from pipeline.stage_3_structuring.schemas import UnifiedChunk

logger = logging.getLogger(__name__)

class ChromaVectorLoader:
    """Manages dense vector storage and metadata retrieval in ChromaDB."""

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        collection_name: str = "hudco_knowledge_chunks",
        embedding_model_name: Optional[str] = None
    ):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.collection_name = collection_name
        self.model_name = embedding_model_name or settings.EMBEDDING_MODEL_NAME

        # Initialize local persistent client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "HUDCO Enterprise Knowledge Repository"}
        )

        # Embedding model
        logger.info(f"Loading embedding model: {self.model_name}")
        self.embedder = SentenceTransformer(self.model_name)

    def load_chunks(self, chunks: List[UnifiedChunk]) -> int:
        """
        Embed and persist a list of UnifiedChunk instances.
        """
        if not chunks:
            return 0

        ids = []
        documents = []
        metadatas = []

        for chunk in chunks:
            # Combine summary, content, and tables for dense embedding
            tbl_text = "\n".join([f"Table {t.title or ''}:\n{t.markdown}" for t in chunk.content.tables])
            combined_doc = (
                f"Document: {chunk.source.title} (FY {chunk.source.fiscal_year or 'N/A'})\n"
                f"Section: {chunk.classification.section_title}\n"
                f"Intent: {chunk.classification.primary_intent}\n"
                f"Summary: {chunk.content.summary}\n"
                f"Content: {chunk.content.text_content}\n"
                f"{tbl_text}"
            )

            ids.append(chunk.chunk_id)
            documents.append(combined_doc)
            metadatas.append({
                "document_id": chunk.document_id,
                "title": chunk.source.title,
                "doc_type": chunk.source.document_type,
                "primary_intent": chunk.classification.primary_intent,
                "fiscal_year": chunk.source.fiscal_year or "",
                "page_start": chunk.source.page_start or 0,
                "page_end": chunk.source.page_end or 0,
                "authority_tier": chunk.source.authority_tier,
                "sha256": chunk.metadata.sha256
            })

        logger.info(f"Generating embeddings for {len(documents)} chunks...")
        embeddings = self.embedder.encode(documents, show_progress_bar=False).tolist()

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

        logger.info(f"Successfully upserted {len(ids)} chunks to ChromaDB collection: {self.collection_name}")
        return len(ids)

    def query_semantic(
        self,
        query: str,
        n_results: int = 5,
        filter_intent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query the vector database with optional intent filtering.
        """
        query_embedding = self.embedder.encode([query]).tolist()
        where_clause = {"primary_intent": filter_intent} if filter_intent else None

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_results,
            where=where_clause
        )
        return results
