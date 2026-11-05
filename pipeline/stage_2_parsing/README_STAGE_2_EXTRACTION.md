# Stage 2: Hybrid Parsing & Extraction

> [!NOTE]
> **Historical Archive Notice**:  
> This document describes the initial prototype design for Stage 2 parsing scripts. As established in ADR-01 and ADR-18, coordinate-aware table extraction and narrative segmentation are implemented in production by `PDFDocumentAdapter` in `pipeline/adapters/pdf_adapter.py`.

## Overview
Stage 2 extracts readable text, metadata, and structured tables from segmented sub-documents and web pages, eliminating non-essential boilerplate.

## Key Components

1. **`text_cleaner.py` (`TextCleaner`)**:
   - Regex-based removal of headers, footers, repeated company names, and page counters.
   - Filters out non-content sections (Proxy Voting Forms, AGM Venue Maps, Attendance Slips).

2. **`table_extractor.py` (`TableExtractor`)**:
   - Extracts multi-column financial statements and KPI matrices.
   - Normalizes rows and columns into valid GitHub-Flavored Markdown tables to preserve relational alignments for LLM reasoning.

3. **`html_crawler.py` (`HTMLCrawler`)**:
   - Uses `trafilatura` and `BeautifulSoup4` to scrape official website pages and accordion FAQs.
   - Cleans navigation bars, footers, and scripts.

## Deliverables
- Clean markdown sections with embedded tables in `data/intermediate/sections/`.
