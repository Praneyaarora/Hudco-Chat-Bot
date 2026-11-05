# Stage 1: Ingestion, Deduplication, Structural Inspection & Document Segmentation

> [!NOTE]
> **Historical Archive Notice**:  
> This document describes the initial September 2026 Stage 1 prototype that performed physical PDF splitting. As documented in ADR-01 and ADR-05, physical PDF slicing was superseded in the clean production pipeline by virtual logical sections in `pipeline/core/` and `pipeline/adapters/`, which extract all 520 pages without boundary displacement or front-matter omission.

## 1. Overview & Architectural Role
Stage 1 is the entry point of the HUDCO Enterprise Conversational AI knowledge pipeline. Its sole mandate is to acquire raw HUDCO documents, validate their structural integrity, deduplicate content deterministically, discover logical chapter boundaries via Table of Contents (TOC) analysis, map printed page labels to physical PDF indices, and split monolithic reports (up to 300MB+ / 500+ pages) into non-overlapping section PDFs.

```
                    STAGE 1 EXECUTION ARCHITECTURE
──────────────────────────────────────────────────────────────────────────

                           SOURCE REQUEST
                       (Remote URL or Local File)
                                │
                                ▼
                       Source Acquisition
                     (Streamed in 64KB Chunks)
                                │
                                ▼
                    Temporary Download (.part)
                                │
                                ▼
                       Streaming Validation
           ┌────────────────────┼────────────────────┐
           │                    │                    │
       HTTP Status          PDF Magic           Content-Type
        (200 OK)             (%PDF-)          (application/pdf)
           │                    │                    │
           └────────────────────┼────────────────────┘
                                ▼
                    Single-Pass Incremental SHA-256
                                │
                                ▼
                      Content Deduplication
                     (Checked vs Local Registry)
                                │
             ┌──────────────────┴──────────────────┐
             ▼                                     ▼
        [ DUPLICATE ]                        [ NEW CONTENT ]
     - Mark Duplicate                     - Atomic Move (.part -> Raw)
     - Reuse Canonical Path               - Register SHA-256 & Name
             │                                     │
             └──────────────────┬──────────────────┘
                                ▼
                     Document Fingerprinting
                 (URL, Filename, PDF Meta, First N Pages)
              - Content-Derived Title & Fiscal Year
              - Filename vs Content Conflict Check
              - Canonical Document ID Generation
                                │
                                ▼
                    PDF Structural Inspection
                (Total Pages, Metadata, Outlines)
                                │
                                ▼
                      Outline Quality Gate
             ┌──────────────────┴──────────────────┐
             │                                     │
        Valid Outline                         Invalid / Weak
      (Sufficient entries,                  (Single digits, junk labels,
       monotonic pages)                      insufficient coverage)
             │                                     │
             │                                     ▼
             │                             TOC Page Discovery
             │                           (Scan First 35 Pages)
             │                                     │
             │                                     ▼
             │                                 TOC Parsing
             │                           (Regex Line Extractions)
             │                                     │
             └──────────────────┬──────────────────┘
                                ▼
                     Printed-to-Physical Page Mapping
                   (Calculates Offset & Verifies Headings)
                                │
                                ▼
                      Logical Section Planning
                   (Non-Overlapping Range Derivation)
                                │
                                ▼
                       PDF Section Splitting
                   (Writes Individual Sub-PDFs)
                                │
                                ▼
                      Post-Split Validation
                  (Bounds, Overlaps, File Checks)
                                │
                                ▼
                     Run Artifacts Generation
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
stage1_manifest.json   stage1_run_report.md   toc_analysis.json
```

---

## 2. Critical Design Principle: Filename Is Not Document Identity
A source filename must **never** be assumed to represent the authoritative document content.
- **Example**: A file named `ar26.pdf` internally identifies itself as `56th Annual Report 2025-26, Housing and Urban Development Corporation Limited`.
- **Identity Hierarchy**:
  - `sha256`: The immutable cryptographic content identity.
  - `received_filename`: The raw filename provided at ingress.
  - `content_title_hint`: Title extracted from PDF text / metadata (e.g. `Annual Report 2025-26`).
  - `fiscal_year_hint`: Fiscal year detected in text (e.g. `2025-26`).
  - `document_id`: Deterministic canonical identifier (e.g. `HUDCO_AR_2025_26_c412ce14`).
  - `identity_conflict`: Boolean flag raised when filename and content hints contradict each other.

---

## 3. Deduplication & Filename Collision Protection
1. **Single-Pass Streaming SHA-256**: Computed incrementally during the download loop (64 KB buffer); avoids a redundant second disk read pass.
2. **Content Deduplication**: Compares calculated SHA-256 against `data/document_registry.json`. If duplicate, the download `.part` is removed, and existing canonical file metadata is returned.
3. **Collision Protection**: If a file with the same destination name already exists on disk but has different content bytes, it is saved safely as `{stem}_{sha8}.pdf` to prevent silent overwriting.

---

## 4. Multi-Strategy TOC Discovery & Page Mapping

```
   ┌───────────────────────┬──────────────────────────────────────────────────────────┐
   │ Strategy Stage        │ Description & Logic                                      │
   ├───────────────────────┼──────────────────────────────────────────────────────────┤
   │ 1. Native Outline     │ Quality-checked for entry count, meaningful titles, and  │
   │    Quality Gate       │ monotonic destinations. Rejected if single-digit or junk.│
   ├───────────────────────┼──────────────────────────────────────────────────────────┤
   │ 2. TOC Page Discovery │ Scans initial 35 pages for 'CONTENTS' headings and regex │
   │    & Line Parsing     │ extracts section titles and printed page numbers.        │
   ├───────────────────────┼──────────────────────────────────────────────────────────┤
   │ 3. Page Mapping       │ Distinguishes physical PDF page index from printed page  │
   │    & Verification     │ label; calculates dominant offset and verifies headings. │
   ├───────────────────────┼──────────────────────────────────────────────────────────┤
   │ 4. Fixed-Window       │ Emergency fallback (25 pages/chunk) explicitly labeled as│
   │    Fallback           │ 'fixed_window_fallback' with LOW confidence.             │
   └───────────────────────┴──────────────────────────────────────────────────────────┘
```

---

## 5. Input & Output Contracts

### Input Contract
- Remote URL: `--url https://...`
- Local File: `--file path/to/document.pdf`
- Document Type: `annual_report`, `circular`, `notification`, etc.

### Output Artifacts
1. **Raw Document**: `data/raw/annual_reports/<filename>.pdf`
2. **Segmented PDFs**: `data/intermediate/sections/{doc_id}_sec{XX}_{title}.pdf`
3. **Machine Manifest**: `data/intermediate/ingestion_runs/<run_id>/stage1_manifest.json`
4. **Audit Report**: `data/intermediate/ingestion_runs/<run_id>/stage1_run_report.md`
5. **TOC Diagnostics**: `data/intermediate/ingestion_runs/<run_id>/toc_analysis.json`

---

## 6. Real-World Acceptance Test: HUDCO Annual Report 2025-26

- **Source URL**: `https://hudco.org.in/writereaddata/ar26.pdf`
- **Observed File Size**: 11.76 MB (520 physical pages)
- **SHA-256**: `c412ce14393a43ad741f30c8da90e9b9ed99da4b923fb6ac7c6656fa3a8d2f41`
- **Outline Quality Gate Result**: `WEAK` (5 entries, rejected due to placeholder / uninformative bookmark labels).
- **TOC Discovery Fallback Result**: Discovered valid TOC on physical page 5 with 19 distinct chapters.
- **Printed vs Physical Page Mapping**: Applied offset = `+2` (e.g. Printed page 18 -> Physical page 20) with **HIGH** confidence.
- **Sections Produced**: 19 discrete, non-overlapping section PDFs:
  1. `sec_01`: Reference Information (Physical 20-21 / Printed 18-19)
  2. `sec_02`: Board of Directors (Physical 22-23 / Printed 20-21)
  3. `sec_03`: Chairman’s Message (Physical 24-36 / Printed 22-34)
  4. `sec_04`: Notice of AGM (Physical 37-49 / Printed 35-47)
  5. `sec_05`: Directors’ Report (Physical 50-79 / Printed 48-77)
  6. `sec_06`: Management Discussion & Analysis Report (Physical 80-83 / Printed 78-81)
  7. `sec_07`: Corporate Governance Report (Physical 84-103 / Printed 82-101)
  8. `sec_08`: Business Responsibility & Sustainability Report (Physical 104-154 / Printed 102-152)
  9. `sec_09`: Independent Reasonable Assurance Report on BRSR Core (Physical 155-159 / Printed 153-157)
  10. `sec_10`: Secretarial Audit Report (Physical 160-163 / Printed 158-161)
  11. `sec_11`: Annual Report on CSR Activities (Physical 164-182 / Printed 162-180)
  12. `sec_12`: Management Reply to Auditor’s Report (Physical 183 / Printed 181)
  13. `sec_13`: CAG Comments on Standalone Statements (Physical 184 / Printed 182)
  14. `sec_14`: CAG Comments on Consolidated Statements (Physical 185-207 / Printed 183-205)
  15. `sec_15`: Standalone Financial Statements (Physical 208-361 / Printed 206-359)
  16. `sec_16`: Consolidated Financial Statements (Physical 362-511 / Printed 360-509)
  17. `sec_17`: Information on Sanctions/Releases (Physical 512-515 / Printed 510-513)
  18. `sec_18`: Management Team (Physical 516 / Printed 514)
  19. `sec_19`: HUDCO Offices (Physical 517-520 / Printed 515-516)

---

## 7. Execution CLI Commands

```powershell
# Ingest and segment remote annual report
python -m pipeline.stage_1_ingestion.run_stage1 --url https://hudco.org.in/writereaddata/ar26.pdf --document-type annual_report

# Ingest and segment local PDF file directly
python -m pipeline.stage_1_ingestion.run_stage1 --file data/raw/annual_reports/ar26.pdf --document-type annual_report

# Run full unit test suite (Tests A-L)
python -m unittest tests.test_stage1
```

---

## 8. Known Limitations & Handoff to Stage 2
1. **Scanned / Image-Only PDFs**: Current implementation relies on embedded text in PDF pages. For purely scanned image PDFs, OCR fallback will be handled in Stage 2 text cleaner.
2. **Handoff to Stage 2**: Stage 2 consumes the generated `stage1_manifest.json` and parses individual section PDFs from `data/intermediate/sections/` for tabular Markdown extraction and boilerplate filtering.
