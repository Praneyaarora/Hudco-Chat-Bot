# Testing and Retrieval Evaluation Methodology

**Document Identifier**: `HUDCO-TEST-EVAL-2026-V1`  
**Target Path**: `docs/TESTING_AND_EVALUATION.md`  
**Status**: Formal Phase 7.1 / Phase 8 Verification Report  
**Corpus Tested**: 520-page HUDCO Annual Report 2025–26 (`data/output_chunks/run_full_ar26_p1_520_v1/chunks.jsonl`, 2,682 chunks, 662 tables)

---

## 1. Automated Test Suite

The repository maintains an automated unit and regression test suite spanning Layers 1 through 4:

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests
```

### 1.1 Test Suite Breakdown

| Test Module | Scope / Coverage | Test Count | Status |
|---|---|---|---|
| `tests/test_phase1.py` | Layer 1 Source Connectors, HTTP fetcher, SSRF guards, deduplication | 16 | ✅ PASSED |
| `tests/test_stage1.py` | Stage 1 Segmenter, downloader, and checksum verification | 12 | ✅ PASSED |
| `tests/test_phase2.py` | Format adapters, section hierarchy, page/block accounting | 25 | ✅ PASSED |
| `tests/test_phase3_hardening.py` | `pdfplumber` coordinate tables, vertical interleaving, TOC discovery | 32 | ✅ PASSED |
| `tests/test_evaluation.py` | Synthetic metrics, ground truth regression, and chunk integrity checks | 14 | ✅ PASSED |
| `tests/test_retrieval.py` | Layer 4 Loader, Table Linearizer, Tokenizer, BM25 Index, PipelineLock, Ranking | 26 | ✅ PASSED |
| **Total** | **Full End-to-End Test Suite** | **125** | **✅ 100% PASS** |

*Execution Duration:* ~8.2 seconds on local workstation.  
*Exit Code:* `0`.

---

## 2. Retrieval Evaluation Methodology

### 2.1 Benchmark Construction & Ground Truth Audit
The retrieval benchmark in `evaluation/data/evaluation_questions.jsonl` contains **20 independently audited questions**:
- **10 Direct Fact Queries**: Personnel appointments, registered office, statutory auditors, management team, regional office contacts, CSR legal provisions.
- **5 Numeric & Financial Table Queries**: Profit After Tax, Revenue from Operations, Paid-up Capital, Cash Flow Profit Before Tax, Affordable Housing loan book.
- **2 Macro Numeric Facts**: Capital Adequacy Ratio, Record Annual Loan Sanctions.
- **1 Ambiguous / Underspecified Query**: Total dividend per equity share across multiple disclosures.
- **3 Unanswerable Queries**: Cryptocurrency/Bitcoin policy, Frankfurt branch opening, European venture capital equity investments.

> [!NOTE]
> Ground-truth labels were audited directly against source document text and tables, **never** generated circularly from retrieval outputs. Where facts appear in multiple disclosures (e.g. registered office appearing on pp. 20, 215, 517 or Statutory Auditors on pp. 71, 208), all valid physical pages and canonical chunk IDs were annotated as ground truth.

### 2.2 Mathematical Metric Definitions & Denominators

1. **Chunk-Level Recall@K**:
   $$\text{Recall@K}_{\text{chunk}} = \frac{1}{|Q_{\text{ans}}|} \sum_{q \in Q_{\text{ans}}} \mathbb{I}\left(\text{Top-}K_{\text{chunks}}(q) \cap C_{\text{expected}}(q) \neq \emptyset\right)$$
   *Denominator:* $|Q_{\text{ans}}| = 17$ (Total answerable questions).

2. **Page-Level Recall@K (Citation-Page Accuracy@K)**:
   $$\text{Recall@K}_{\text{page}} = \frac{1}{|Q_{\text{ans}}|} \sum_{q \in Q_{\text{ans}}} \mathbb{I}\left(\text{Top-}K_{\text{pages}}(q) \cap P_{\text{expected}}(q) \neq \emptyset\right)$$
   *Denominator:* $|Q_{\text{ans}}| = 17$. (When $K=1$, this represents Citation-Page Accuracy@1 under exact page matching).

3. **Top-5 Citation Precision**:
   $$\text{Precision@5}_{\text{citation}} = \frac{\sum_{q \in Q_{\text{ans}}} |\{p \in \text{Top-}5_{\text{pages}}(q) : p \in P_{\text{expected}}(q)\}|}{5 \times |Q_{\text{ans}}|}$$
   *Denominator:* Total emitted citation slots across Top-5 ($17 \times 5 = 85$ candidate slots). Measures the ratio of supported emitted citations to total emitted candidate slots.

4. **Mean Reciprocal Rank (MRR)**:
   $$\text{MRR} = \frac{1}{|Q_{\text{ans}}|} \sum_{q \in Q_{\text{ans}}} \frac{1}{\text{rank}_{\text{first}}(q)}$$
   *Denominator:* $|Q_{\text{ans}}| = 17$. If no relevant candidate is within top 5, reciprocal rank is $0$.

5. **Abstention Precision**:
   $$\text{Precision}_{\text{abstain}} = \frac{\text{True Abstentions}}{\text{True Abstentions} + \text{False Abstentions}}$$
   *Denominator:* Total queries where the system triggered abstention ($3$).

6. **Abstention Recall**:
   $$\text{Recall}_{\text{abstain}} = \frac{\text{True Abstentions}}{|Q_{\text{unans}}|}$$
   *Denominator:* $|Q_{\text{unans}}| = 3$ (Total unanswerable questions).

7. **Abstention F1 Score**:
   $$\text{F1}_{\text{abstain}} = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$$

---

## 3. Benchmark Results & Gate Verification

Evaluated against the full 520-page canonical chunk dataset (2,682 chunks, 662 tables):

```powershell
.\.venv\Scripts\python.exe scripts/run_retrieval_eval.py
```

### 3.1 Aggregate Performance vs. Acceptance Targets

| Metric | Historical Proposed Target | ADR-21 Approved Gate | Achieved Measurement | Verdict |
|---|---|---|---|---|
| **Indexed Canonical Chunks** | 2,682 chunks | 2,682 chunks | **2,682 chunks** | Full 520-page run |
| **Page Recall@1 (Citation Acc@1)** | $\ge 75.0\%$ | Gate 4: $\ge 60.0\%$ | **88.2%** (15/17) | **PASSED GATE 4 (+28.2%)** |
| **Page Recall@3** | $\ge 90.0\%$ | Monitored | **100.0%** (17/17) | **EXCEEDED PROPOSED** |
| **Page Recall@5** | $\ge 95.0\%$ | Gate 3: $\ge 80.0\%$ | **100.0%** (17/17) | **PASSED GATE 3 (+20.0%)** |
| **Chunk Recall@1** | Monitored | Monitored | **70.6%** (12/17) | Baseline Established |
| **Chunk Recall@3** | Monitored | Monitored | **76.5%** (13/17) | Baseline Established |
| **Chunk Recall@5** | Monitored | Monitored | **88.2%** (15/17) | Baseline Established |
| **Top-5 Citation Precision** | Monitored | Monitored | **30.6%** (26/85) | Baseline Established |
| **MRR (Page Provenance)** | $\ge 0.8000$ | Monitored | **0.9412** | **EXCEEDED PROPOSED** |
| **MRR (Chunk Provenance)** | Monitored | Monitored | **0.7588** | Baseline Established |
| **Abstention Precision** | $100.0\%$ | Gate 5: $100.0\%$ | **100.0%** (3/3) | **PASSED GATE 5** |
| **Abstention Recall** | $\ge 66.7\%$ | Gate 6: $\ge 66.7\%$ | **100.0%** (3/3) | **PASSED GATE 6 (+33.3%)** |
| **Abstention F1 Score** | $\ge 80.0\%$ | Monitored | **100.0%** | **EXCEEDED PROPOSED** |

---

## 4. Per-Question Results & Detailed Diagnostic Analysis

| QID | Category | Top-1 Score | Top Page | Ground Truth Page(s) | Hit@1 | Hit@5 | Analysis & Diagnostic |
|---|---|---|---|---|---|---|---|
| **Q01** | direct_fact | 25.26 | 22 | [22] | **YES** | **YES** | CMD Sanjay Kulshrestha profile retrieved at Rank 1. |
| **Q02** | direct_fact | 15.58 | 44 | [22, 23, 44] | **YES** | **YES** | Statutory AGM Notice Table (p. 44) retrieved at Rank 1 via appoint lemmatization (Score 15.58 >= 14.50). |
| **Q03** | direct_fact | 28.56 | 215 | [20, 215, 517] | **YES** | **YES** | Registered Office in Note 1 Standalone Statements retrieved at Rank 1. |
| **Q04** | direct_fact | 38.87 | 95 | [37, 95] | **YES** | **YES** | 56th AGM details in Corporate Governance Report retrieved at Rank 1. |
| **Q05** | numeric_table | 38.84 | 21 | [21] | **YES** | **YES** | Profit After Tax table in Financial Highlights retrieved at Rank 1. |
| **Q06** | numeric_table | 24.16 | 138 | [21, 50, 209] | NO | **YES** | BRSR GHG table on p. 138 ranked 1; standalone audited P&L on p. 209 at Rank 2. |
| **Q07** | definition | 24.45 | 56 | [56] | **YES** | **YES** | PMAY(U)-2.0 objective in Directors' Report retrieved at Rank 1. |
| **Q08** | numeric_table | 42.82 | 116 | [116] | **YES** | **YES** | Affordable Housing outstanding loan balance retrieved at Rank 1. |
| **Q09** | direct_fact | 42.64 | 164 | [164] | **YES** | **YES** | Section 135 Companies Act in CSR Report retrieved at Rank 1. |
| **Q10** | numeric_table | 27.82 | 51 | [21, 51, 208] | **YES** | **YES** | Paid-up equity share capital in Directors' Report retrieved at Rank 1. |
| **Q11** | unanswerable | 12.01 | 113 | [] | — | — | **CORRECT ABSTENTION**: Score 12.01 < 14.5; term coverage 33.3% < 40%. |
| **Q12** | unanswerable | 15.08 | 104 | [] | — | — | **CORRECT ABSTENTION**: Term coverage 33.3% < 40%. |
| **Q13** | numeric_fact | 30.88 | 29 | [29] | **YES** | **YES** | Capital Adequacy Ratio (39.93%) in Chairman's Message retrieved at Rank 1. |
| **Q14** | direct_fact | 26.84 | 516 | [516] | **YES** | **YES** | Chief Vigilance Officer & Company Secretary on Management Team page retrieved at Rank 1. |
| **Q15** | direct_fact | 24.77 | 71 | [71, 208] | **YES** | **YES** | Statutory Auditors (SARC & Associates) in Directors' Report Item 23 retrieved at Rank 1. |
| **Q16** | numeric_table | 41.65 | 210 | [210] | **YES** | **YES** | Cash Flow Statement Profit Before Tax (Rs. 3,221.44 Cr) retrieved at Rank 1. |
| **Q17** | direct_fact | 31.33 | 518 | [518] | **YES** | **YES** | Bengaluru regional office contact details retrieved at Rank 1 via contact binding and section inheritance. |
| **Q18** | numeric_fact | 24.09 | 72 | [29] | NO | **YES** | Management Discussion sanctions narrative on p. 72 ranked 1; Chairman's summary table on p. 29 at Rank 2. |
| **Q19** | ambiguous | 40.73 | 37 | [29, 37, 50, 51, 95] | **YES** | **YES** | Total dividend per equity share in Notice of AGM retrieved at Rank 1. |
| **Q20** | unanswerable | 14.12 | 116 | [] | — | — | **CORRECT ABSTENTION**: Score 14.12 < 14.50 and term coverage 28.6% < 40%. |

---

## 5. Known Limitations & Residual Risks

1. **Rank-1 Ambiguity on Multi-Section Disclosures (Q06, Q18)**:
   - For broad queries where information appears in both narrative discussions and primary financial tables (e.g. Q06 Revenue/PAT or Q18 Loan Sanctions), lexical retrieval may rank narrative disclosure paragraphs (pp. 72, 138) ahead of primary financial statements (pp. 29, 209). However, both reference pages are captured within the Top 3 (Page Recall@3: 100.0%).
   - *Downstream Mitigation*: Downstream context assemblers can supply the top 3 candidates or filter by `has_table=True` when answering quantitative prompts.
2. **Benchmark Sizing**:
   - The current benchmark of 20 questions provides a representative, high-confidence evaluation across all 19 major sections. For subsequent operational phases, expanding to 50–100 questions covering granular notes to accounts is recommended.
3. **Lexical BM25 Domain**:
   - BM25 evaluates lexical token overlap with term coverage gating. It does not perform semantic embedding comparisons; questions phrasing concepts without shared roots rely on the tokenizer's financial normalization rules.es to accounts is recommended.
