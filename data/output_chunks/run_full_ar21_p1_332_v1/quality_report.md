# Phase 2 Processing & Quality Audit Report: ar21.pdf

## 1. Executive Summary
- **Document ID**: `doc_ar21`
- **Source File**: `ar21.pdf`
- **Format**: `pdf`
- **Physical Pages**: `332`
- **Sections Inferred**: `20`
- **Total Chunks Produced**: `1964` (Table Chunks: `411`)
- **Effective Chunk Configuration**: Target `1200` chars | Max `2000` chars | Overlap `150` chars
- **Oversized Chunks Preserved**: `53`
- **Total Audit Warnings**: `61`
- **Processing Status**: `success_with_warnings`

## 2. Structural Section Hierarchy
| Section ID | Title | Level | Page Range (Physical) | Printed Page Range | Method | Confidence | Blocks |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `sec_00` | Document Front Matter | 1 | 1–6 | None–None | `preamble_unclassified` | **medium** | 35 |
| `sec_01` | BOARD OF DIRECTORS | 1 | 7–7 | 05–None | `toc_page_discovery` | **medium** | 15 |
| `sec_02` | CHAIRMAN'S MESSAGE | 1 | 8–11 | 06–None | `toc_page_discovery` | **medium** | 47 |
| `sec_03` | NOTICE OF AGM | 1 | 12–23 | 10–None | `toc_page_discovery` | **medium** | 166 |
| `sec_04` | DIRECTORS' REPORT | 1 | 24–41 | 22–None | `toc_page_discovery` | **medium** | 240 |
| `sec_05` | MANAGEMENT DISCUSSION & ANALYSIS REPORT | 1 | 42–44 | 40–None | `toc_page_discovery` | **medium** | 32 |
| `sec_06` | CORPORATE GOVERNANCE REPORT | 1 | 45–64 | 43–None | `toc_page_discovery` | **medium** | 322 |
| `sec_07` | BUSINESS RESPONSIBILITY REPORT | 1 | 65–72 | 63–None | `toc_page_discovery` | **medium** | 139 |
| `sec_08` | SECRETARIAL AUDIT REPORT | 1 | 73–83 | 71–None | `toc_page_discovery` | **medium** | 114 |
| `sec_09` | EXTRACT OF ANNUAL RETURN | 1 | 84–94 | 82–7 | `toc_page_discovery` | **medium** | 54 |
| `sec_10` | MANAGEMENT REPLY TO INDEPENDENT AUDITOR'S REPORT | 1 | 95–95 | 93–None | `toc_page_discovery` | **medium** | 13 |
| `sec_11` | COMMENTS OF THE C&AG ON STANDALONE FINANCIAL STATEMENTS | 1 | 96–96 | 94–9 | `toc_page_discovery` | **medium** | 10 |
| `sec_12` | COMMENTS OF THE C&AG ON CONSOLIDATED FINANCIAL STATEMENTS | 1 | 97–97 | 95–None | `toc_page_discovery` | **medium** | 12 |
| `sec_13` | INDEPENDENT AUDITOR'S REPORT ON STANDALONE FINANCIAL STATEMENTS | 1 | 98–107 | 96–None | `toc_page_discovery` | **medium** | 103 |
| `sec_14` | STANDALONE FINANCIAL STATEMENTS | 1 | 108–207 | 106–None | `toc_page_discovery` | **medium** | 853 |
| `sec_15` | INDEPENDENT AUDITOR'S REPORT ON CONSOLIDATED FINANCIAL STATEMENTS | 1 | 208–213 | 206–None | `toc_page_discovery` | **medium** | 72 |
| `sec_16` | CONSOLIDATED FINANCIAL STATEMENTS | 1 | 214–325 | 212–None | `toc_page_discovery` | **medium** | 995 |
| `sec_17` | SENIOR EXECUTIVE | 1 | 326–326 | 324–None | `toc_page_discovery` | **medium** | 33 |
| `sec_18` | HUDCO OFFICES | 1 | 327–328 | 325–1 | `toc_page_discovery` | **medium** | 228 |
| `sec_19` | DETAILS OF THE AUDITORS AND BANKERS | 1 | 329–332 | 327–None | `toc_page_discovery` | **medium** | 41 |

## 3. Chunk Sizing and Distribution Analysis
- **Min Chunk Size**: 1 characters
- **Max Chunk Size**: 4365 characters
- **Average Chunk Size**: 495 characters

## 4. Quality Warnings & Anomaly Log
- **[blank_page]** (Page 1): Physical page 1 has zero extracted text.
- **[blank_page]** (Page 2): Physical page 2 has zero extracted text.
- **[scanned_page]** (Page 3): Physical page 3 appears to be a scanned image or raster chart.
- **[scanned_page]** (Page 4): Physical page 4 appears to be a scanned image or raster chart.
- **[scanned_page]** (Page 330): Physical page 330 appears to be a scanned image or raster chart.
- **[blank_page]** (Page 331): Physical page 331 has zero extracted text.
- **[blank_page]** (Page 332): Physical page 332 has zero extracted text.
- **[toc_uncertain_offset]** (Page 5): Calibrated TOC page offset: physical_page = printed_page + 2 (matched 19/20 sections with strict monotonic page ordering).
- **[chunk_too_long]** (Page 18): Table p018_tbl01 length (2726) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 42): Narrative block p042_blk04 length (2048) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 77): Table p077_tbl02 length (2070) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 78): Table p078_tbl01 length (2511) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 79): Table p079_tbl01 length (3215) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 80): Table p080_tbl01 length (2676) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 82): Table p082_tbl01 length (2809) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 85): Table p085_tbl02 length (2286) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 86): Table p086_tbl01 length (2659) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 88): Table p088_tbl01 length (2689) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 89): Table p089_tbl01 length (2694) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 90): Table p090_tbl01 length (2563) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 105): Table p105_tbl01 length (4000) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 108): Table p108_tbl01 length (2714) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 109): Table p109_tbl01 length (2769) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 110): Table p110_tbl01 length (2418) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 111): Table p111_tbl01 length (3039) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 112): Table p112_tbl01 length (3581) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 129): Table p129_tbl01 length (2616) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 137): Table p137_tbl01 length (2410) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 138): Table p138_tbl01 length (2443) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 141): Table p141_tbl01 length (3526) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 144): Table p144_tbl01 length (2525) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 145): Table p145_tbl01 length (2508) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 146): Table p146_tbl01 length (3657) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 147): Table p147_tbl01 length (2435) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 158): Table p158_tbl01 length (3557) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 185): Table p185_tbl01 length (3419) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 201): Table p201_tbl01 length (2180) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 202): Table p202_tbl01 length (3526) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 203): Table p203_tbl01 length (3701) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 214): Table p214_tbl01 length (2755) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 215): Table p215_tbl01 length (2961) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 216): Table p216_tbl01 length (2244) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 217): Table p217_tbl01 length (3087) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 218): Table p218_tbl01 length (3586) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 236): Table p236_tbl01 length (2616) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 245): Table p245_tbl01 length (2626) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 246): Table p246_tbl01 length (2122) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 249): Table p249_tbl01 length (3526) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 252): Table p252_tbl01 length (2525) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 253): Table p253_tbl01 length (2760) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 254): Table p254_tbl01 length (3705) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 255): Table p255_tbl01 length (2911) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 257): Table p257_tbl01 length (2030) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 265): Table p265_tbl01 length (3563) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 294): Table p294_tbl01 length (3160) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 295): Table p295_tbl01 length (2087) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 313): Table p313_tbl01 length (2672) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 314): Table p314_tbl01 length (4365) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 315): Table p315_tbl01 length (3378) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 322): Table p322_tbl01 length (2253) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 324): Table p324_tbl01 length (3874) exceeds max_chunk_size (2000); preserved intact.

## 5. Provenance & Reproducibility Statement
- All chunks carry deterministic IDs incorporating `document_id`, `version_number`, `processing_revision`, and `content_sha256`.
- Chunks strictly respect section boundaries; no cross-section chunks were permitted.
- Tabular data was preserved as indivisible structured units with GFM Markdown display projections.
