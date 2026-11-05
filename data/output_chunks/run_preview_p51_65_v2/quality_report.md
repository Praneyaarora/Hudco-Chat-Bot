# Phase 2 Processing & Quality Audit Report: ar26.pdf

## 1. Executive Summary
- **Document ID**: `doc_ar26`
- **Source File**: `ar26.pdf`
- **Format**: `pdf`
- **Physical Pages**: `65`
- **Sections Inferred**: `31`
- **Total Chunks Produced**: `77` (Table Chunks: `4`)
- **Effective Chunk Configuration**: Target `1200` chars | Max `2000` chars | Overlap `150` chars
- **Oversized Chunks Preserved**: `1`
- **Total Audit Warnings**: `2`
- **Processing Status**: `success_with_warnings`

## 2. Structural Section Hierarchy
| Section ID | Title | Level | Page Range (Physical) | Printed Page Range | Method | Confidence | Blocks |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `sec_00` | Document Overview | 1 | 51–51 | None–None | `preamble_unclassified` | **medium** | 1 |
| `sec_01` | Consolidated Financial Statements | 2 | 51–51 | None–None | `html_heading_tree` | **high** | 11 |
| `sec_02` | Listing of securities and payment of listing fee | 2 | 51–52 | None–None | `html_heading_tree` | **high** | 3 |
| `sec_03` | Amounts transferred to IEPF | 2 | 52–52 | None–None | `html_heading_tree` | **high** | 3 |
| `sec_04` | Equity Shares transferred to IEPF | 2 | 52–52 | None–None | `html_heading_tree` | **high** | 4 |
| `sec_05` | Claim from IEPF Account | 2 | 52–52 | None–None | `html_heading_tree` | **high** | 5 |
| `sec_06` | MoU 2025 - 26: Achievement of Key Performance Parameters (as on 31.03.2026) | 2 | 53–53 | None–None | `html_heading_tree` | **high** | 7 |
| `sec_07` | Urban Infrastructure Lending | 2 | 53–53 | None–None | `html_heading_tree` | **high** | 2 |
| `sec_08` | Housing Operations | 2 | 53–53 | None–None | `html_heading_tree` | **high** | 3 |
| `sec_09` | Transport and Logistics | 2 | 53–54 | None–None | `html_heading_tree` | **high** | 8 |
| `sec_10` | Energy | 2 | 54–54 | None–None | `html_heading_tree` | **high** | 5 |
| `sec_11` | Water and Sanitation | 2 | 55–55 | None–None | `html_heading_tree` | **high** | 5 |
| `sec_12` | Social and Commercial Infrastructure | 2 | 55–55 | None–None | `html_heading_tree` | **high** | 4 |
| `sec_13` | Housing | 2 | 55–55 | None–None | `html_heading_tree` | **high** | 4 |
| `sec_14` | Sectorial overview and government initiative: | 2 | 56–56 | None–None | `html_heading_tree` | **high** | 1 |
| `sec_15` | Support to Economically Weaker Sections | 2 | 56–56 | None–None | `html_heading_tree` | **high** | 2 |
| `sec_16` | HUDCO’s Support for projects in the North-Eastern Region | 2 | 56–56 | None–None | `html_heading_tree` | **high** | 5 |
| `sec_17` | Property Development and Consultancy | 2 | 56–57 | None–None | `html_heading_tree` | **high** | 5 |
| `sec_18` | Cities in India.” | 2 | 57–60 | None–None | `html_heading_tree` | **high** | 22 |
| `sec_19` | Domestic and International Credit Ratings | 2 | 60–60 | None–None | `html_heading_tree` | **high** | 4 |
| `sec_20` | Issuance and Dematerialization of Bonds/Debentures | 2 | 60–61 | None–None | `html_heading_tree` | **high** | 4 |
| `sec_21` | Redemption of Debt Securities and Repayment of Loans | 2 | 61–61 | None–None | `html_heading_tree` | **high** | 8 |
| `sec_22` | Transfer to Investor Education and Protection Fund (IEPF) | 2 | 61–61 | None–None | `html_heading_tree` | **high** | 3 |
| `sec_23` | Investor Servicing and Commitment | 2 | 61–64 | None–None | `html_heading_tree` | **high** | 17 |
| `sec_24` | Internal Audit | 2 | 64–64 | None–None | `html_heading_tree` | **high** | 9 |
| `sec_25` | T raining Activities | 2 | 64–64 | None–None | `html_heading_tree` | **high** | 2 |
| `sec_26` | Capacity Building and Training conducted in Financial Year 2025-26: | 2 | 64–65 | None–None | `html_heading_tree` | **high** | 3 |
| `sec_27` | For HUDCO and other CPSEs officers | 2 | 65–65 | None–None | `html_heading_tree` | **high** | 2 |
| `sec_28` | Webinars | 2 | 65–65 | None–None | `html_heading_tree` | **high** | 2 |
| `sec_29` | Hybrid Training Programme | 2 | 65–65 | None–None | `html_heading_tree` | **high** | 5 |
| `sec_30` | For International Participants under ITEC | 2 | 65–65 | None–None | `html_heading_tree` | **high** | 3 |

## 3. Chunk Sizing and Distribution Analysis
- **Min Chunk Size**: 45 characters
- **Max Chunk Size**: 2751 characters
- **Average Chunk Size**: 778 characters

## 4. Quality Warnings & Anomaly Log
- **[structure_confidence]**: TOC detected on page 5, but 0/18 entries matched verified printed page numbers in current payload.
- **[chunk_too_long]** (Page 63): Table p063_tbl01 length (2751) exceeds max_chunk_size (2000); preserved intact.

## 5. Provenance & Reproducibility Statement
- All chunks carry deterministic IDs incorporating `document_id`, `version_number`, `processing_revision`, and `content_sha256`.
- Chunks strictly respect section boundaries; no cross-section chunks were permitted.
- Tabular data was preserved as indivisible structured units with GFM Markdown display projections.
