# Stage 3: Structuring & Intent Tagging

> [!NOTE]
> **Historical Archive Notice**:  
> This document describes the initial prototype design for keyword intent tagging. As established in ADR-01 and ADR-19, intent classification is decoupled from core ingestion: runtime query intent classification belongs to downstream Layer 5 conversational orchestration, while document chunking is handled cleanly by `pipeline/core/chunker.py` producing `CanonicalChunk` models.

## Overview
Stage 3 takes parsed text and tabular extractions and structures them into atomic, typed `UnifiedChunk` JSON objects. This stage ensures strict Pydantic compliance and assigns intent taxonomies for fast and accurate RAG routing.

## Key Components

1. **`schemas.py` (`UnifiedChunk`)**:
   - Master data contract ensuring all source documents have strict fields: `chunk_id`, `document_id`, `source`, `classification`, `content`, and `metadata`.
   - Supports embedded Markdown tables and citation provenance (page ranges, URL, authority tier).

2. **`intent_classifier.py` (`IntentClassifier`)**:
   - Maps extracted chunks to the 5 core HUDCO domain categories (Housing Finance, Urban Infrastructure, Investor Disclosures, Navigation, and Governance).
   - Generates deterministic SHA-256 hashes for chunk tracking and deduplication.

## Output
- Validated atomic chunk JSON files stored in `data/output_chunks/`.
