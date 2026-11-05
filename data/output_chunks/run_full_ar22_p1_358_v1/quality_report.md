# Phase 2 Processing & Quality Audit Report: ar22.pdf

## 1. Executive Summary
- **Document ID**: `doc_ar22`
- **Source File**: `ar22.pdf`
- **Format**: `pdf`
- **Physical Pages**: `358`
- **Sections Inferred**: `18`
- **Total Chunks Produced**: `2211` (Table Chunks: `461`)
- **Effective Chunk Configuration**: Target `1200` chars | Max `2000` chars | Overlap `150` chars
- **Oversized Chunks Preserved**: `50`
- **Total Audit Warnings**: `58`
- **Processing Status**: `success_with_warnings`

## 2. Structural Section Hierarchy
| Section ID | Title | Level | Page Range (Physical) | Printed Page Range | Method | Confidence | Blocks |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `sec_00` | Document Front Matter | 1 | 1–6 | None–None | `preamble_unclassified` | **medium** | 52 |
| `sec_01` | BOARD OF DIRECTORS | 1 | 7–7 | 05–None | `toc_page_discovery` | **medium** | 2 |
| `sec_02` | CHAIRMAN’S MESSAGE | 1 | 8–11 | 06–None | `toc_page_discovery` | **medium** | 46 |
| `sec_03` | NOTICE OF AGM | 1 | 12–23 | 10–None | `toc_page_discovery` | **medium** | 168 |
| `sec_04` | DIRECTORS’ REPORT | 1 | 24–41 | 22–None | `toc_page_discovery` | **medium** | 236 |
| `sec_05` | MANAGEMENT DISCUSSION & ANALYSIS REPORT | 1 | 42–44 | 40–None | `toc_page_discovery` | **medium** | 37 |
| `sec_06` | CORPORATE GOVERNANCE REPORT | 1 | 45–66 | 43–None | `toc_page_discovery` | **medium** | 330 |
| `sec_07` | BUSINESS RESPONSIBILITY REPORT | 1 | 67–75 | 65–None | `toc_page_discovery` | **medium** | 154 |
| `sec_08` | SECRETARIAL AUDIT REPORT | 1 | 76–89 | 74–None | `toc_page_discovery` | **medium** | 147 |
| `sec_09` | MANAGEMENT REPLY TO INDEPENDENT AUDITOR’S REPORT | 1 | 90–90 | 88–6 | `toc_page_discovery` | **medium** | 21 |
| `sec_10` | COMMENTS OF THE C&AG ON STANDALONE FINANCIAL STATEMENTS | 1 | 91–91 | 89–8 | `toc_page_discovery` | **medium** | 12 |
| `sec_11` | COMMENTS OF THE C&AG ON CONSOLIDATED FINANCIAL STATEMENTS | 1 | 92–92 | 90–None | `toc_page_discovery` | **medium** | 11 |
| `sec_12` | INDEPENDENT AUDITOR’S REPORT ON STANDALONE FINANCIAL STATEMENTS | 1 | 93–103 | 91–None | `toc_page_discovery` | **medium** | 102 |
| `sec_13` | STANDALONE FINANCIAL STATEMENTS | 1 | 104–225 | 102–None | `toc_page_discovery` | **medium** | 1089 |
| `sec_14` | CONSOLIDATED FINANCIAL STATEMENTS | 1 | 226–352 | 224–2022 | `toc_page_discovery` | **medium** | 1109 |
| `sec_15` | SENIOR EXECUTIVES | 1 | 353–353 | 351–None | `toc_page_discovery` | **medium** | 2 |
| `sec_16` | HUDCO OFFICES | 1 | 354–355 | 352–1 | `toc_page_discovery` | **medium** | 203 |
| `sec_17` | DETAILS OF THE AUDITORS AND BANKERS | 1 | 356–358 | 354–None | `toc_page_discovery` | **medium** | 36 |

## 3. Chunk Sizing and Distribution Analysis
- **Min Chunk Size**: 1 characters
- **Max Chunk Size**: 4819 characters
- **Average Chunk Size**: 466 characters

## 4. Quality Warnings & Anomaly Log
- **[blank_page]** (Page 1): Physical page 1 has zero extracted text.
- **[blank_page]** (Page 2): Physical page 2 has zero extracted text.
- **[scanned_page]** (Page 7): Physical page 7 appears to be a scanned image or raster chart.
- **[scanned_page]** (Page 353): Physical page 353 appears to be a scanned image or raster chart.
- **[blank_page]** (Page 357): Physical page 357 has zero extracted text.
- **[blank_page]** (Page 358): Physical page 358 has zero extracted text.
- **[structure_confidence]**: PDF native outline rejected: 44.4% of outline entries (4/9) are generic export artifacts or pure numeric digits (e.g. ['1', '2', '3']). Falling back to secondary structural evidence.
- **[toc_uncertain_offset]** (Page 5): Calibrated TOC page offset: physical_page = printed_page + 2 (matched 17/19 sections with strict monotonic page ordering).
- **[chunk_too_long]** (Page 8): Narrative block p008_blk03 length (2052) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 12): Narrative block p012_blk13 length (2476) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 19): Table p019_tbl01 length (4469) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 64): Table p064_tbl01 length (2730) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 81): Table p081_tbl01 length (2608) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 82): Table p082_tbl01 length (2136) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 88): Table p088_tbl01 length (2179) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 89): Table p089_tbl01 length (3598) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 101): Table p101_tbl01 length (3000) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 104): Table p104_tbl01 length (3241) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 105): Table p105_tbl01 length (2616) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 106): Table p106_tbl03 length (2261) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 107): Table p107_tbl01 length (4032) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 108): Table p108_tbl01 length (3984) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 122): Table p122_tbl01 length (2007) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 125): Table p125_tbl01 length (3141) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 134): Table p134_tbl01 length (3045) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 135): Table p135_tbl01 length (3322) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 138): Table p138_tbl01 length (4776) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 143): Table p143_tbl01 length (2772) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 144): Table p144_tbl01 length (3443) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 145): Table p145_tbl01 length (3762) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 146): Table p146_tbl01 length (2890) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 147): Table p147_tbl01 length (2699) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 149): Table p149_tbl01 length (3154) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 159): Table p159_tbl01 length (4819) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 173): Table p173_tbl01 length (2306) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 185): Table p185_tbl01 length (2093) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 186): Table p186_tbl01 length (2788) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 226): Table p226_tbl01 length (2787) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 227): Table p227_tbl01 length (3308) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 228): Table p228_tbl01 length (2310) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 229): Table p229_tbl01 length (3829) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 230): Table p230_tbl01 length (3981) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 248): Table p248_tbl01 length (3020) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 257): Table p257_tbl01 length (3047) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 258): Table p258_tbl01 length (3392) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 261): Table p261_tbl01 length (4776) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 267): Table p267_tbl01 length (2792) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 268): Table p268_tbl01 length (2972) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 269): Table p269_tbl01 length (3591) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 270): Table p270_tbl01 length (3004) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 271): Table p271_tbl01 length (3265) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 273): Table p273_tbl01 length (3170) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 283): Table p283_tbl01 length (3129) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 284): Table p284_tbl01 length (2285) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 298): Table p298_tbl01 length (2059) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 313): Table p313_tbl01 length (2705) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 340): Table p340_tbl01 length (2135) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 351): Table p351_tbl01 length (3871) exceeds max_chunk_size (2000); preserved intact.

## 5. Provenance & Reproducibility Statement
- All chunks carry deterministic IDs incorporating `document_id`, `version_number`, `processing_revision`, and `content_sha256`.
- Chunks strictly respect section boundaries; no cross-section chunks were permitted.
- Tabular data was preserved as indivisible structured units with GFM Markdown display projections.
