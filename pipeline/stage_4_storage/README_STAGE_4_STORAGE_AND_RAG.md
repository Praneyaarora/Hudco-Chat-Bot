# Stage 4: Dual Storage Architecture & RAG Indexing

> [!NOTE]
> **Historical Archive Notice**:  
> This document describes the initial prototype design proposing ChromaDB and PostgreSQL storage. As established in ADR-09 and ADR-20, our team's scope terminates at Layer 4 (indexing and retrieval), implemented as a deterministic in-memory Okapi BM25 index over canonical chunks in `pipeline/retrieval/`. Dense vector embeddings, ChromaDB, and conversational generation remain options for downstream Layer 5 teams.

## Overview
Stage 4 implements a hybrid dual-storage architecture combining dense vector embeddings in **ChromaDB** with relational cataloging in **PostgreSQL / SQLAlchemy**.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                 DUAL STORAGE ARCHITECTURE                   │
  ├──────────────────────────────┬──────────────────────────────┤
  │ ChromaDB (Dense Vector Store)│ PostgreSQL (Relational Store)│
  ├──────────────────────────────┼──────────────────────────────┤
  │ - Sentence-Transformer Vecs  │ - Document Master Registry   │
  │ - Multi-intent Semantic Match│ - SHA-256 Deduplication Table│
  │ - BM25 Keyword Hybrid Search │ - Structured Office Contacts │
  │ - Page Provenance Metadata   │ - Exact Financial KPI Facts  │
  └──────────────────────────────┴──────────────────────────────┘
```

## Key Components

1. **`chroma_loader.py` (`ChromaVectorLoader`)**:
   - Embeds structured chunks using `sentence-transformers/all-MiniLM-L6-v2`.
   - Stores rich queryable metadata (fiscal year, authority tier, primary intent, page range).
   - Supports filtered vector search by intent taxonomy.

2. **`db_registry.py` (`DocumentRegistry`, `ChunkRegistry`, `OfficeDirectory`)**:
   - Tracks document lifecycle states (`PENDING`, `INGESTED`, `INDEXED`).
   - Maintains exact relational lookups for office contact details and official forms.

## Usage Example
```python
from pipeline.stage_4_storage.chroma_loader import ChromaVectorLoader

loader = ChromaVectorLoader()
results = loader.query_semantic(
    query="What is HUDCO's loan disbursement growth in FY 2024-25?",
    n_results=3,
    filter_intent="FINANCIAL_RESULTS"
)
```
