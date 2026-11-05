# Downstream Integration Contract & Team Handoff

**Document Identifier**: `HUDCO-HANDOFF-LAYER4-2026-V1`  
**Target Path**: `docs/INTEGRATION_HANDOFF.md`  
**From**: Ingestion & Retrieval Team (Layers 1–4)  
**To**: Chatbot & Generation Team (Layer 5)  
**Scope**: Python API, Data Contracts, Metadata Filters, Provenance Rules, and Abstention Handling

---

## 1. Division of Responsibilities

| Responsibility Area | Owned by Our Team (Layers 1–4) | Owned by Downstream Team (Layer 5) |
|---|---|---|
| **Raw PDF Ingestion & OCR** | ✅ Owned (`pipeline/adapters/`) | ❌ Out of scope |
| **Structural Analysis & TOC Discovery** | ✅ Owned (`pipeline/core/structural_analyzer.py`) | ❌ Out of scope |
| **Coordinate Table Extraction** | ✅ Owned (`pipeline/adapters/pdf_adapter.py`) | ❌ Out of scope |
| **Hierarchical Chunking** | ✅ Owned (`pipeline/core/chunker.py`) | ❌ Out of scope |
| **Lexical Indexing (Okapi BM25)** | ✅ Owned (`pipeline/retrieval/bm25.py`) | ❌ Out of scope |
| **Metadata Filtering & Dual-Threshold Abstention** | ✅ Owned (`pipeline/retrieval/contracts.py`) | ❌ Out of scope |
| **Prompt Template Synthesis & Context Windowing** | ❌ Strictly downstream | ✅ Owned by Generation Team |
| **LLM Generation & Temperature Tuning** | ❌ Strictly downstream | ✅ Owned by Generation Team |
| **Conversational Memory & Multi-Turn History** | ❌ Strictly downstream | ✅ Owned by Generation Team |
| **Chatbot Web/REST Interface & Streaming** | ❌ Strictly downstream | ✅ Owned by Generation Team |
| **Stage 5 Intent Routing (e.g. Chat vs Form)** | ❌ Strictly downstream (ADR-19) | ✅ Owned by Generation Team |

---

## 2. Python Integration API

### 2.1 Basic Usage

```python
from pathlib import Path
from pipeline.retrieval.loader import load_canonical_chunks
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.contracts import RetrievalFilter, RetrievalResponse, RetrievalResultItem

# Step 1: Initialize index from approved canonical chunks (typically at application startup)
APPROVED_CHUNKS_PATH = "data/output_chunks/run_full_ar26_p1_520_v1/chunks.jsonl"
chunks = load_canonical_chunks(APPROVED_CHUNKS_PATH)
retriever = Layer4BM25Index(chunks)

# Step 2: Query retrieval
response: RetrievalResponse = retriever.retrieve(
    query="What was HUDCO's Revenue from Operations for FY 2025-26?",
    top_k=5
)

# Step 3: Check abstention
if response.is_abstention:
    print(f"Abstention triggered: {response.abstention_reason}")
else:
    for item in response.results:
        print(f"Rank {item.rank}: Page {item.physical_page} (Score: {item.score})")
        print(f"Content:\n{item.content}\n")
```

---

## 3. Querying with Metadata Filters

The `RetrievalFilter` contract allows downstream dialog managers or intent routers to narrow candidate search:

```python
filters = RetrievalFilter(
    section_id="sec_14",              # Restrict to Standalone Financial Statements
    min_physical_page=200,            # Page lower bound (inclusive)
    max_physical_page=250,            # Page upper bound (inclusive)
    has_table=True,                   # Only return chunks containing structured tables
    include_stale=False               # Exclude superseded chunks (default: False)
)

response = retriever.retrieve(
    query="Cash and Cash Equivalents at end of year",
    top_k=3,
    filters=filters
)
```

### Supported Filter Fields

| Field | Type | Description |
|---|---|---|
| `document_id` | `Optional[str]` | Exact document identifier (e.g. `doc_ar26`). |
| `version_id` | `Optional[str]` | Exact document version snapshot (e.g. `v1`). |
| `section_id` | `Optional[str]` | Exact section ID (e.g. `sec_01` to `sec_18`). |
| `section_title_contains` | `Optional[str]` | Case-insensitive substring match on section title. |
| `min_physical_page` | `Optional[int]` | Minimum physical PDF page index ($\ge 1$). |
| `max_physical_page` | `Optional[int]` | Maximum physical PDF page index ($\ge 1$). |
| `has_table` | `Optional[bool]` | `True` for table chunks only; `False` for narrative chunks only. |
| `include_stale` | `bool` | Set `True` to include superseded chunks (default: `False`). |

---

## 4. Response Contract & Provenance Handling

Every candidate in `RetrievalResponse.results` is a strongly-typed `RetrievalResultItem`:

```python
class RetrievalResultItem(BaseModel):
    rank: int                          # 1-based candidate rank (1 to top_k)
    chunk_id: str                      # Canonical chunk ID: doc_ar26_v1_c412ce14_sec_01_p021_c01
    score: float                       # Okapi BM25 relevance score
    matched_terms: List[str]           # Specific query terms that matched
    term_coverage: float               # Percentage of unique query terms matched (0.0 to 1.0)
    explanation: str                   # Diagnostic breakdown of term contributions
    document_id: str                   # E.g. "doc_ar26"
    version_id: str                    # E.g. "v1"
    source_filename: str               # "ar26.pdf"
    section_id: str                    # E.g. "sec_01"
    section_title: str                 # E.g. "Financial Highlights"
    physical_page: int                 # Absolute PDF page (MANDATORY for citations)
    printed_page: Optional[str]        # Printed report page (e.g. "19" or "iv")
    has_table: bool                    # True if chunk contains structured table
    table_metadata: Optional[List[TableMetadata]] # Structured table properties
    content: str                       # Markdown/text content ready for LLM prompt context
    content_sha256: str                # Content integrity hash
```

### Table Metadata Access
If `item.has_table is True`, inspect `item.table_metadata`:
```python
if item.table_metadata:
    for tbl in item.table_metadata:
        print(f"Table Caption: {tbl.caption}")
        print(f"Unit of Measure: {tbl.unit_of_measure}")  # E.g. '₹ in Crore'
        print(f"Dimensions: {tbl.row_count} rows x {tbl.col_count} cols")
```

---

## 5. Abstention & Hallucination Prevention

To prevent generative models from hallucinating on out-of-domain questions (e.g. cryptocurrency, foreign branches, unanswerable queries):
1. **Always check `response.is_abstention` first**:
   ```python
   if response.is_abstention:
       return "I apologize, but this information is not disclosed in the HUDCO Annual Report 2025–26."
   ```
2. **Abstention Signals**:
   - `response.is_abstention` is set to `True` if:
     - Top candidate score $< 14.5$, **OR**
     - Top candidate query term coverage $< 40.0\%$, **OR**
     - Query was empty / contained zero indexed terms.
   - The diagnostic reason is available in `response.abstention_reason`.

---

## 6. Citation Grounding Rules for LLM Prompts

When engineering prompt templates for response generation, adhere to these grounding invariants:
1. **Cite Physical Page**: Always instruct the LLM to cite `item.physical_page` (e.g. `[Page 21]`).
2. **Preserve Units of Measure**: When generating figures from tabular chunks, explicitly cite `tbl.unit_of_measure` (e.g. `₹ in Crore` or `Rs. Crore`). Do not assume default currencies.
3. **No Inference Across Section Boundaries**: Chunks are section-bounded. Never merge assumptions across disparate section hierarchies without explicit attribution.
