# HUDCO Pipeline Quality & Acceptance Report

**Execution Timestamp:** `2026-10-21T06:40:20.302519+00:00`  
**Pipeline Status:** `SUCCESS`  
**Run Directory:** `C:\Users\Praneya Arora\Desktop\Hudco\data\output_chunks\run_full_ar26_p1_520_v1`  
**Artifacts Reused:** `True`  
**Elapsed Time:** `12.5s`  

---

## 1. Acceptance Gates Verification

| Gate | Status |
|---|---|
| Gate 1: Test Suite 100% Pass Rate | ✅ PASSED |
| Gate 2: Canonical Integrity (0 Duplicate IDs) | ✅ PASSED |
| Gate 3: Retrieval Recall@5 >= 80% | ✅ PASSED |
| Gate 4: Page Citation Acc@1 >= 60% | ✅ PASSED |
| Gate 5: Abstention Precision == 100% | ✅ PASSED |
| Gate 6: Abstention Recall >= 66% | ✅ PASSED |

---

## 2. Ingestion & Chunking Summary

- **Source Document:** `ar26.pdf` (SHA-256: `c412ce14393a43ad...`)
- **Total Canonical Chunks:** `2,682`
- **Total Physical Pages:** `518`
- **Structured Table Chunks:** `662`

---

## 3. Layer 4 Retrieval Benchmark Performance

- **Page Recall@1 (Citation Accuracy):** `88.2%`
- **Page Recall@3:** `100.0%`
- **Page Recall@5:** `100.0%`
- **Chunk Recall@1:** `70.6%`
- **Chunk Recall@5:** `88.2%`
- **MRR (Page Provenance):** `0.9412`
- **MRR (Chunk Provenance):** `0.7588`
- **Abstention Precision:** `100.0%`
- **Abstention Recall:** `100.0%`
- **Abstention F1:** `100.0%`

---

## 4. Test Suite Execution

- **Total Unit/Integration Tests:** `125`
- **Failures:** `0`
- **Errors:** `0`
- **Overall Result:** `PASSED`
