# Phase 2 Processing & Quality Audit Report: ar26.pdf

## 1. Executive Summary
- **Document ID**: `doc_ar26`
- **Source File**: `ar26.pdf`
- **Format**: `pdf`
- **Physical Pages**: `50`
- **Sections Inferred**: `5`
- **Total Chunks Produced**: `145` (Table Chunks: `13`)
- **Effective Chunk Configuration**: Target `1200` chars | Max `2000` chars | Overlap `150` chars
- **Oversized Chunks Preserved**: `6`
- **Total Audit Warnings**: `7`
- **Processing Status**: `success_with_warnings`

## 2. Structural Section Hierarchy
| Section ID | Title | Level | Page Range (Physical) | Printed Page Range | Method | Confidence | Blocks |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `sec_01` | Reference Information | 1 | 20–21 | 18–19 | `toc_page_discovery` | **medium** | 12 |
| `sec_02` | Board of Directors | 1 | 22–23 | 20–21 | `toc_page_discovery` | **medium** | 35 |
| `sec_03` | Chairman’s Message | 1 | 24–36 | 22–34 | `toc_page_discovery` | **medium** | 91 |
| `sec_04` | Notice of AGM | 1 | 37–49 | 35–47 | `toc_page_discovery` | **medium** | 130 |
| `sec_05` | Directors’ Report | 1 | 50–50 | 48–48 | `toc_page_discovery` | **medium** | 6 |

## 3. Chunk Sizing and Distribution Analysis
- **Min Chunk Size**: 4 characters
- **Max Chunk Size**: 4132 characters
- **Average Chunk Size**: 796 characters

## 4. Quality Warnings & Anomaly Log
- **[scanned_page]** (Page 24): Physical page 24 appears to be a scanned image or raster chart.
- **[chunk_too_long]** (Page 27): Table p027_tbl01 length (2544) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 35): Table p035_tbl01 length (2202) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 41): Table p041_tbl01 length (2934) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 42): Table p042_tbl01 length (2728) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 44): Table p044_tbl01 length (4132) exceeds max_chunk_size (2000); preserved intact.
- **[chunk_too_long]** (Page 46): Table p046_tbl01 length (3739) exceeds max_chunk_size (2000); preserved intact.

## 5. Provenance & Reproducibility Statement
- All chunks carry deterministic IDs incorporating `document_id`, `version_number`, `processing_revision`, and `content_sha256`.
- Chunks strictly respect section boundaries; no cross-section chunks were permitted.
- Tabular data was preserved as indivisible structured units with GFM Markdown display projections.
