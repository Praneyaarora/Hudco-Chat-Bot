# Phase 2 Processing & Quality Audit Report: ar15.pdf

## 1. Executive Summary
- **Document ID**: `doc_ar15`
- **Source File**: `ar15.pdf`
- **Format**: `pdf`
- **Physical Pages**: `138`
- **Sections Inferred**: `13`
- **Total Chunks Produced**: `1034` (Table Chunks: `124`)
- **Effective Chunk Configuration**: Target `1200` chars | Max `2000` chars | Overlap `150` chars
- **Oversized Chunks Preserved**: `21`
- **Total Audit Warnings**: `27`
- **Processing Status**: `success_with_warnings`

## 2. Structural Section Hierarchy
| Section ID | Title | Level | Page Range (Physical) | Printed Page Range | Method | Confidence | Blocks |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `sec_00` | Document Front Matter | 1 | 1–5 | None–None | `preamble_unclassified` | **medium** | 34 |
| `sec_01` | Board of Directors | 1 | 6–7 | 5–None | `toc_page_discovery` | **medium** | 17 |
| `sec_02` | Chairman’s Speech | 1 | 8–12 | 7–None | `toc_page_discovery` | **medium** | 37 |
| `sec_03` | Notice of AGM | 1 | 13–13 | 12–None | `toc_page_discovery` | **medium** | 18 |
| `sec_04` | Directors’ Report | 1 | 14–33 | 13–None | `toc_page_discovery` | **medium** | 257 |
| `sec_05` | Corporate Governance Report | 1 | 34–52 | 33–None | `toc_page_discovery` | **medium** | 243 |
| `sec_06` | Extract of Annual Return | 1 | 53–56 | 52–None | `toc_page_discovery` | **medium** | 38 |
| `sec_07` | Secretarial Audit Report | 1 | 57–59 | 56–None | `toc_page_discovery` | **medium** | 70 |
| `sec_08` | Independent Auditor’s Report | 1 | 60–70 | 59–None | `toc_page_discovery` | **medium** | 123 |
| `sec_09` | Comments of The C&AG | 1 | 71–130 | 70–None | `toc_page_discovery` | **medium** | 492 |
| `sec_10` | Senior Executives | 1 | 131–132 | 130–None | `toc_page_discovery` | **medium** | 41 |
| `sec_11` | HUDCO Offices | 1 | 133–134 | 132–1 | `toc_page_discovery` | **medium** | 207 |
| `sec_12` | Details of the Auditors & Bankers | 1 | 135–138 | 134–None | `toc_page_discovery` | **medium** | 96 |

## 3. Chunk Sizing and Distribution Analysis
- **Min Chunk Size**: 3 characters
- **Max Chunk Size**: 4373 characters
- **Average Chunk Size**: 313 characters

## 4. Quality Warnings & Anomaly Log
- **[blank_page]** (Page 1): Physical page 1 has zero extracted text.
- **[scanned_page]** (Page 8): Physical page 8 appears to be a scanned image or raster chart.
- **[scanned_page]** (Page 136): Physical page 136 appears to be a scanned image or raster chart.
- **[scanned_page]** (Page 137): Physical page 137 appears to be a scanned image or raster chart.
- **[blank_page]** (Page 138): Physical page 138 has zero extracted text.
- **[toc_uncertain_offset]** (Page 4): Calibrated TOC page offset: physical_page = printed_page + 1 (matched 12/13 sections with strict monotonic page ordering).
- **[chunk_too_long]** (Page 29): Narrative block p029_blk04 length (2123) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 48): Table p048_tbl01 length (2358) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 51): Table p051_tbl01 length (2032) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 67): Table p067_tbl01 length (2133) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 69): Table p069_tbl01 length (2617) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 81): Table p081_tbl01 length (2690) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 83): Narrative block p083_blk06 length (2535) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 84): Table p084_tbl01 length (3642) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 85): Table p085_tbl01 length (2875) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 87): Table p087_tbl01 length (2493) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 88): Table p088_tbl01 length (2861) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 90): Table p090_tbl01 length (3463) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 94): Table p094_tbl01 length (4373) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 97): Table p097_tbl01 length (2419) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 100): Table p100_tbl01 length (2811) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 101): Table p101_tbl01 length (2462) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 106): Table p106_tbl01 length (2077) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 114): Table p114_tbl01 length (2434) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 126): Table p126_tbl01 length (2442) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 129): Table p129_tbl01 length (2877) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 130): Table p130_tbl01 length (2940) exceeds max_chunk_size (2000); preserved intact.

## 5. Provenance & Reproducibility Statement
- All chunks carry deterministic IDs incorporating `document_id`, `version_number`, `processing_revision`, and `content_sha256`.
- Chunks strictly respect section boundaries; no cross-section chunks were permitted.
- Tabular data was preserved as indivisible structured units with GFM Markdown display projections.
