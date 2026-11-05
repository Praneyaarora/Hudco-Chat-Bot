# Source Discovery, Safe Acquisition, and Automated Ingestion Specification

**Document Identifier**: `HUDCO-DOCPROC-CONNECTORS-2026-V1`  
**Target Path**: `docs/SOURCE_CONNECTORS_AND_AUTOMATION.md`  
**Status**: Approved Phase 0B Ingestion & Automation Blueprint  
**Author**: Senior RAG Architect & Data Systems Engineer  
**Scope**: Source discovery, safe network acquisition, SSRF mitigation, change detection, incremental versioning, scheduling, and acceptance scenarios.

---

## 1. System Mission & Ingestion Entry Points

The document processing system is designed as an automated, continuous ingestion engine capable of acquiring documents from heterogeneous origins, verifying content authenticity, tracking source evolution, and feeding downstream canonical extraction and chunking.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              SOURCE DISCOVERY & ACQUISITION                            │
│                                                                                        │
│   [Local Filesystem]          [Direct URL]            [Configured Website]             │
│   Incoming watch dirs         Single PDF/HTML         Listing pages, sitemaps, RSS     │
│           │                         │                               │                  │
│           ▼                         ▼                               ▼                  │
│   [Filesystem Scanner]        [Safe HTTP Fetcher]         [Web Crawler / Spider]       │
│           │                         │                               │                  │
│           └─────────────────────────┼───────────────────────────────┘                  │
│                                     ▼                                                  │
│                    [Source Registry & Change Detection]                                │
│                     ETag • Last-Modified • SHA-256                                     │
│                     Detect New / Unchanged / Updated / Stale                           │
│                                     │                                                  │
│                                     ▼                                                  │
│                    [Format Sniffer & Magic Byte Gate]                                  │
│                                     │                                                  │
│                                     ▼                                                  │
│               [Common Format Adapters: PDF / HTML / Future]                            │
│                                     │                                                  │
│                                     ▼                                                  │
│               [Downstream Canonical Processing & Chunking]                             │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

The system provides three primary entry points:

### 1.1 Entry Point A: Local Filesystem Intake
- **Target**: Batch drops, internal network shares, and local archives.
- **Mechanism**: Scans configured directories (e.g. `data/incoming/`) recursively or at top-level.
- **Workflow**:
  1. Identifies files matching supported extensions (`.pdf`, `.html`, `.htm`, and future `.docx`, `.md`).
  2. Computes streaming SHA-256 without loading entire files into RAM.
  3. Checks `SourceRegistry` for previous ingestion.
  4. Preserves local file path, creation/modification timestamps, and file permissions.
  5. Moves or copies processed files to managed raw storage (`data/raw/{doc_type}/`) based on configuration (`move_on_ingest: bool`).

### 1.2 Entry Point B: Direct URL Intake
- **Target**: Explicit URLs pointing directly to downloadable assets (e.g. `https://hudco.org.in/writereaddata/ar26.pdf` or circular URLs).
- **Mechanism**: The Safe HTTP Fetcher executes a guarded network request, validates HTTP status and headers, sniffs content type via magic bytes, and downloads content to a temporary spool file before hashing and registration.
- **Workflow**:
  1. Validates URL against security rules (domain allowlist, scheme enforcement).
  2. Issues conditional HTTP `GET` with `If-None-Match` (ETag) or `If-Modified-Since` if previously seen.
  3. If HTTP 304 (Not Modified), skips download and updates `last_checked_at`.
  4. If HTTP 200, streams body through a streaming SHA-256 hasher with hard size caps.
  5. Verifies magic bytes (`%PDF-`, `<!DOCTYPE html>`, etc.).
  6. Registers new `DocumentVersion` in `SourceRegistry` and routes payload to adapter.

### 1.3 Entry Point C: Configured Website Crawling & Discovery
- **Target**: Official portals (e.g. `https://hudco.org.in`), investor relations portals, regulatory notice boards, and circular directories.
- **Mechanism**: A controlled, bounded crawler operating over an approved domain allowlist. It traverses sitemaps, RSS/Atom feeds, and HTML index/listing pages, extracts outbound links to target documents and content pages, and delegates actual document fetching to the Safe HTTP Fetcher.
- **Workflow**:
  1. Reads `robots.txt` and sitemaps (`/sitemap.xml`) if available.
  2. Fetches approved starting URLs (e.g. `/circulars.html`, `/annual-reports.html`).
  3. Parses HTML DOM to discover document download links (`<a href="...pdf">`) and child article pages.
  4. Follows pagination links (`Next`, `Page 2`, `?page=X`) up to a configured max depth.
  5. Queues discovered URLs into the discovery ledger with priority rankings.

---

## 2. Website Discovery Architecture

Website discovery is strictly decoupled from document extraction. The crawler's sole responsibility is **resource discovery and URL resolution**.

```
   [Seed URL / Config] ──► [Robots & Sitemap Parser] ──► [Page Queue]
                                                               │
                                                               ▼
   [Document Registry] ◄── [Safe HTTP Fetcher] ◄── [DOM Link Extractor]
                                                           │
                                                           ▼
                                               [Pagination / Next Links]
```

### 2.1 Discovery Mechanisms

1. **Sitemap XML**:
   - Queries `https://{domain}/sitemap.xml` and `robots.txt` sitemap references.
   - Parses `<loc>`, `<lastmod>`, and `<changefreq>`.
   - Filters URLs against configured path patterns (e.g. `/circulars/*`, `/reports/*`).
2. **RSS / Atom Feeds**:
   - Scans syndication feeds (e.g. `/feed.xml`, `/rss/notices`) for recently posted press releases and circulars.
   - Captures publication dates (`<pubDate>`, `<updated>`) to establish document release timelines.
3. **HTML Index & Listing Pages**:
   - Parses listing tables (e.g. `<table class="circular-list">`) and unordered lists.
   - Extracts anchor elements: `<a href="..." title="...">`.
   - Normalizes relative URLs (e.g. `../../writereaddata/foo.pdf`) against base URLs using RFC 3986 resolution.
4. **Pagination & Next-Page Heuristics**:
   - Identifies pagination structures:
     - Anchor text matching: `Next`, `Older`, `Next Page`, `»`, `>`.
     - Rel attributes: `<a rel="next" href="...">`.
     - URL patterns: `?page=\d+`, `/page/\d+/`, `?start=\d+`, `?offset=\d+`.
   - Enforces a strict `max_pagination_depth` (default: 10 pages) to prevent infinite loops on circular pagination.
5. **Downloadable Document Link Extraction**:
   - Matches href links targeting supported extensions (`.pdf`, `.html`, `.docx`).
   - Inspects anchor text, surrounding table cells, and row headers to extract human-readable titles, publication dates, and circular numbers before download.

### 2.2 Content Filtering: Discard vs. Retain Rules

The crawler separates substantive documents from administrative website noise using strict filtering rules:

| Category | Filter Rule / Pattern | Action |
|---|---|---|
| **Allowed Extensions** | `.pdf`, `.html`, `.htm`, `.xhtml` | Retain for download queue |
| **Ignored Static Assets** | `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.css`, `.js`, `.woff`, `.ico` | Discard immediately |
| **Ignored Admin Paths** | `/admin`, `/login`, `/logout`, `/wp-admin`, `/cart`, `/search` | Discard immediately |
| **Disallowed Auth / Forms** | Forms containing `method="post"`, password inputs, CSRF tokens | Discard; never submit |
| **External Domains** | Any URL whose host does not match `domain_allowlist` | Discard; never follow |
| **Tracking / Query Bloat** | `utm_*`, `fbclid`, `gclid`, `session_id`, `jsessionid` | Strip query parameters |
| **Calendar / Date Bloat** | Repetitive dynamic calendars (e.g. `?month=X&year=Y`) | Discard |

### 2.3 Limits on Website Compatibility (Explicit Boundaries)
- **JavaScript Single-Page Apps (SPAs)**: The crawler operates via fast, safe HTTP requests (`requests` / `httpx`). It **does not** execute client-side JavaScript or run a headless browser (Puppeteer, Playwright, Selenium). Sites requiring client-side JavaScript rendering to reveal download links will log a `SPA_RENDERING_UNSUPPORTED` warning.
- **Anti-Bot / CAPTCHA Protections**: The crawler does not solve CAPTCHAs, spoof browser fingerprints, or bypass Cloudflare/Akamai bot detection. If an HTTP 403 or Cloudflare challenge is encountered, the crawler logs `ACCESS_DENIED_BOT_BLOCKED` and gracefully aborts.
- **Authenticated Intranets**: Basic HTTP Authentication or Bearer tokens can be passed via secure configuration headers, but session-based multi-factor authentication (MFA) is out of scope.

---

## 3. Safe and Controlled HTTP Acquisition

Acquiring content over public networks presents severe security and stability risks. The system mandates multi-layered security controls.

```
Incoming URL ──► [1. Scheme & Syntax Check]
                      │ (Must be https://)
                      ▼
                 [2. SSRF Guard: DNS & IP Validation]
                      │ (Rejects 127.0.0.1, 10.0.0.0/8, 169.254.0.0/16, etc.)
                      ▼
                 [3. Domain Allowlist Check]
                      │ (Must match configured domain)
                      ▼
                 [4. Robots.txt Compliance]
                      │
                      ▼
                 [5. Rate Limiter (Token Bucket)]
                      │
                      ▼
                 [6. Guarded Streaming Download]
                      │ (Max size cap: 250 MB, streaming SHA-256)
                      ▼
                 [7. Content-Type & Magic Byte Sniffer]
                      │
                      ▼
                 Validated Raw Asset Spool
```

### 3.1 Security & Reliability Controls

1. **HTTPS Enforcement**:
   - All external network requests must use `https://`. Plain `http://` requests are automatically upgraded or rejected based on configuration.
   - Strict SSL/TLS certificate verification is enabled (`verify=True`). Insecure certificate bypassing is forbidden.
2. **Server-Side Request Forgery (SSRF) Protection**:
   - Before executing any network call, the hostname is resolved via DNS.
   - The resolved IP address is verified against a strict private/internal IP blacklist:
     - Loopback addresses (`127.0.0.0/8`, `::1`).
     - RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
     - Carrier-grade NAT (`100.64.0.0/10`).
     - Link-local addresses (`169.254.0.0/16`, `fe80::/10`).
     - Cloud metadata services (`169.254.169.254`, `metadata.google.internal`).
     - Broadcast and multicast (`224.0.0.0/4`, `240.0.0.0/4`).
   - If an IP resolves to any restricted range, the request is aborted immediately with `SSRF_BLOCKED_ERROR`.
3. **Redirect Validation**:
   - HTTP 301, 302, 307, and 308 redirects are not followed blindly.
   - Max redirects capped at 5.
   - Every redirect target URL is re-evaluated through the SSRF guard and domain allowlist. Redirecting from an allowed public domain to an internal IP or disallowed third-party domain is blocked.
4. **Domain and Path Allowlists**:
   - Crawler only contacts domains explicitly listed in `SourceConfiguration.allowed_domains` (e.g. `["hudco.org.in", "www.hudco.org.in"]`).
   - Subdomains are excluded unless wildcard subdomain matching is explicitly enabled.
   - Specific paths can be restricted via `allowed_path_prefixes` (e.g. `["/writereaddata/", "/circulars/"]`).
5. **Streaming Size Caps & Decompression Bomb Protection**:
   - Maximum response body size is enforced during streaming download (`max_download_bytes`, default: 250 MB for annual reports, 25 MB for web pages).
   - The fetcher reads chunks into memory and counts total bytes. If the count exceeds the threshold, the download is immediately terminated and the temporary file is deleted to prevent disk exhaustion.
   - Compressed HTTP streams (`gzip`, `br`, `deflate`) are monitored during decompression; if decompression ratio exceeds 10:1 or uncompressed size exceeds limit, download is killed (`DECOMPRESSION_BOMB_ERROR`).
6. **Timeouts and Retry Backoff**:
   - Connect timeout: 10 seconds.
   - Read timeout: 30 seconds.
   - Maximum retries: 3 attempts.
   - Exponential backoff with jitter: $T_{\text{sleep}} = \min(60, 2^{\text{attempt}} + \text{uniform}(0, 1))$.
7. **Rate Limiting & Politeness**:
   - Configurable per-domain request delay (default: minimum 1.5 seconds between successive requests to the same host).
   - Concurrent connections per host capped at 2.
   - Respects standard `robots.txt` crawl delays.
8. **HTTP Error Handling**:
   - `HTTP 404 (Not Found)`: Marked as missing; source status updated to `RESOURCE_NOT_FOUND`.
   - `HTTP 403 (Forbidden)`: Access denied; logged as `ACCESS_FORBIDDEN`; retries halted.
   - `HTTP 429 (Too Many Requests)`: Rate limited; reads `Retry-After` header and backs off.
   - `HTTP 5xx (Server Error)`: Transient server failure; retried up to maximum retries.
9. **Credential and Cookie Sanitization**:
   - Logs never record `Authorization` headers, `Cookie` headers, API tokens, or basic auth credentials.
   - Query strings containing token-like keys (`token`, `key`, `secret`, `auth`) are masked in logs as `[REDACTED]`.
10. **Format Detection via Magic Bytes**:
    - The fetcher does not trust the `Content-Type` header or file extension blindly.
    - Inspects the first 16 bytes of the downloaded payload:
      - PDF: `%PDF-` (`b"%PDF-"`)
      - HTML: `<!DOCTYPE`, `<html`, `<HTML`, `<?xml`
      - Zip/DOCX: `PK\x03\x04`
    - If `Content-Type: application/pdf` is declared but content is `<!DOCTYPE html>` (e.g. a 404 page returned with HTTP 200), the file is identified as HTML or rejected as mismatched format.

---

## 4. Source Registry, Change Detection, and Incremental Ingestion

To prevent wasteful reprocessing and maintain full historical auditability, the system maintains a persistent `SourceRegistry`.

### 4.1 Master Entity Relationships

```
┌────────────────────────────────────────────────────────┐
│                      SourceRecord                      │
│  source_id (e.g. src_hudco_ar26)                       │
│  canonical_url: https://hudco.org.in/.../ar26.pdf      │
│  first_seen_at • last_checked_at                       │
│  current_version_id • current_status                   │
└───────────────────────────┬────────────────────────────┘
                            │ 1
                            ▼ *
┌────────────────────────────────────────────────────────┐
│                    DocumentVersion                     │
│  version_id (e.g. doc_ar26_v1_c412ce14)                │
│  source_id • version_number (1, 2, ...)                │
│  content_sha256 • size_bytes                           │
│  http_etag • http_last_modified                        │
│  fetched_at • raw_artifact_path                        │
│  is_current (bool)                                     │
└───────────────────────────┬────────────────────────────┘
                            │ 1
                            ▼ *
┌────────────────────────────────────────────────────────┐
│                     CanonicalChunk                     │
│  chunk_id: doc_ar26_v1_c412ce14_sec_05_p052_c00        │
│  version_id • document_id • section_id                 │
│  is_stale (bool)                                       │
└────────────────────────────────────────────────────────┘
```

### 4.2 Handling the Seven Lifecycle Scenarios

#### Scenario 1: A Completely New Document
- **Trigger**: Discovered URL or local file path does not exist in `SourceRegistry`.
- **Action**:
  1. Creates new `SourceRecord` (`version_count = 1`).
  2. Creates `DocumentVersion` (`version_number = 1`, `is_current = True`).
  3. Executes full extraction, structural analysis, and chunking.
  4. Persists chunks with versioned IDs: `{doc_id}_v1_{hash8}_sec_{sec}_p{page}_c{idx}`.
  5. Status: `INGESTION_SUCCESS`.

#### Scenario 2: Unchanged URL, But Content Has Changed
- **Trigger**: URL matches existing `SourceRecord`, but incoming HTTP fetch returns new ETag/Last-Modified, or streaming SHA-256 does not match `current_version.content_sha256`.
- **Action**:
  1. The existing version is retained intact, but marked `is_current = False`.
  2. Chunks belonging to the old version in downstream indices are tagged `is_stale = True` (or superseded).
  3. A new `DocumentVersion` is recorded (`version_number = current + 1`, `is_current = True`).
  4. Executes full pipeline on the new raw payload.
  5. Emits new versioned chunks with distinct IDs.
  6. Historical evidence is fully preserved; both versions are auditable.

#### Scenario 3: Same Content Discovered at Multiple URLs
- **Trigger**: A newly discovered URL downloads a payload whose SHA-256 matches an existing `DocumentVersion` under a different URL.
- **Action**:
  1. System detects identical content hash via the hash index in `SourceRegistry`.
  2. Binds the secondary URL as an alias/alternate location to the existing `SourceRecord`.
  3. Bypasses redundant parsing and chunking.
  4. Records `DUPLICATE_CONTENT_ALIASED` in the run manifest.

#### Scenario 4: Temporarily Unavailable Website
- **Trigger**: Scheduled check encounters HTTP 500, 502, 503, 504, connection reset, or timeout.
- **Action**:
  1. Retries with exponential backoff up to max attempts.
  2. If still failing, does **not** assume the source is deleted or obsolete.
  3. Existing `DocumentVersion` and downstream chunks remain `is_current = True`.
  4. Updates `SourceRecord.last_error = "HTTP 503 Service Unavailable"`.
  5. Schedules next retry according to backoff policy.

#### Scenario 5: Removed or Replaced Circular / Document (HTTP 404/410)
- **Trigger**: An existing document URL returns HTTP 404 (Not Found) or HTTP 410 (Gone).
- **Action**:
  1. Verifies the 404 across 2 retry intervals to prevent reacting to transient CDN glitches.
  2. Once confirmed, updates `SourceRecord.status = "UPSTREAM_REMOVED"`.
  3. Does **not** delete historical raw files, manifests, or chunks from disk.
  4. Marks current chunks as `upstream_removed = True`, allowing retrieval systems to filter out or apply tombstones according to policy.

#### Scenario 6: A Failed Extraction That Must Be Retried
- **Trigger**: Document download succeeded, but Stage 2 adapter extraction or Stage 3 structure crashed or threw `PARTIAL_FAILURE`.
- **Action**:
  1. `DocumentVersion` is saved with `processing_status = "EXTRACTION_FAILED"`.
  2. Raw asset file remains safely on disk in raw storage.
  3. Chunks are not emitted (preventing corrupt chunks from reaching consumers).
  4. Run manifest records the error stack trace.
  5. A subsequent run with `--retry-failed` targets only documents in `EXTRACTION_FAILED` state without re-downloading.

#### Scenario 7: Pipeline / Parser Upgrade Requiring Reprocessing
- **Trigger**: Developer updates PDF parsing logic, table extraction heuristics, or target chunk sizes.
- **Action**:
  1. Pipeline tracks `PIPELINE_CODE_VERSION` and `CONFIG_HASH`.
  2. Running with `--reprocess-all` or `--pipeline-version v2` reads raw files directly from managed raw storage.
  3. Computes new canonical documents and chunks without re-hitting the upstream website.
  4. Updates chunk outputs cleanly.

---

## 5. Automation, Scheduling, and Operational Model

The pipeline must support scheduled, unattended execution as well as manual invocation.

```
       [External Cron / CLI Trigger]
                     │
                     ▼
            [Scheduler Runner]
                     │
         [Process File Mutex Lock] ──► Active? Abort to prevent overlap
                     │
                     ▼
          [Iterate Configured Sources]
          ├─ Check last_checked_at vs interval
          ├─ Evaluate change detection (ETag/SHA)
          └─ Ingest if changed
                     │
                     ▼
            [Release Lock & Log]
```

### 5.1 Scheduling Architecture

1. **Local Interval Runner (`pipeline/scheduler.py`)**:
   - A lightweight, in-process scheduler using standard Python (or standard OS cron / Task Scheduler).
   - Reads `config/sources.json`, iterating over configured sources.
   - Evaluates `recheck_interval_hours` (e.g. check circulars every 6 hours; check annual reports once every 7 days).
2. **Process Mutex Lock**:
   - To prevent overlapping crawls or concurrent writes to `SourceRegistry`, the scheduler acquires a file lock (`data/.pipeline.lock`).
   - If a previous run is still active, the new run logs `PROCESS_LOCKED_SKIPPING` and exits gracefully.
3. **Resuming Interrupted Crawls**:
   - Crawler writes discovered URLs and fetch states to a durable SQLite or JSON ledger (`crawl_state.json`).
   - If interrupted (e.g. system shutdown), the crawler checks the ledger on reboot and resumes from the unvisited queue without restarting from seed URLs.
4. **Decoupled Architecture (Deployment Extensibility)**:
   - The core engine exposes clean, self-contained Python functions:
     - `ingest_file(path, ...)`
     - `ingest_url(url, ...)`
     - `crawl_source(source_config, ...)`
   - While Phase 0B specifies a local CLI and scheduler, future production deployments can trigger these exact functions via Celery, Airflow, AWS Lambda, or FastAPI without altering any adapter or chunking code.

---

## 6. Comprehensive Acceptance Scenarios

To validate compliance before production deployment, the pipeline must pass 16 formal acceptance test scenarios using local fixtures and controlled mock HTTP responses:

| Scenario ID | Test Name | Description & Expected Outcome |
|---|---|---|
| **SC-01** | Local Digital PDF | Process a local digital PDF (`ar26.pdf`). Verifies 100% page extraction, outline parsing, canonical document generation, and valid JSONL chunks. |
| **SC-02** | Local HTML Page | Process a local HTML file. Verifies heading hierarchy (`h1`-`h6`), paragraph extraction, and locator breadcrumbs. |
| **SC-03** | Direct URL to PDF | Supply direct URL. Mock HTTP returns 200 with PDF payload. Verifies safe fetch, streaming hash, registration, and clean chunks. |
| **SC-04** | Direct URL to HTML | Supply direct URL to HTML article. Verifies DOM extraction and Markdown formatting. |
| **SC-05** | Listing Page PDF Discovery | Provide mock listing HTML with 5 PDF links. Verifies crawler discovers all 5 URLs, filters invalid extensions, and queues documents. |
| **SC-06** | Bounded Pagination | Provide paginated listing (`?page=1` to `?page=3`). Verifies crawler follows `Next` links and terminates cleanly at max depth. |
| **SC-07** | Deduplicate Unchanged Content | Re-fetch unchanged URL returning HTTP 304 (or identical SHA-256). Verifies download is skipped, zero duplicate chunks emitted. |
| **SC-08** | Detect Changed Content | Re-fetch URL returning modified content. Verifies new `DocumentVersion` created, old version marked superseded, new chunks emitted. |
| **SC-09** | Version Lineage Retention | Audit storage after document update. Verifies both old and new raw assets, manifests, and chunks remain inspectable. |
| **SC-10** | HTTP Error & Backoff Handling | Mock server returns HTTP 500 followed by 200. Verifies exponential retry succeeds and logs transient warning. |
| **SC-11** | SSRF & Disallowed Domain Rejection | Provide URL pointing to `169.254.169.254` or unauthorized domain. Verifies fetcher aborts immediately with security error. |
| **SC-12** | PDF with No TOC / Bookmarks | Ingest PDF lacking bookmarks and printed TOC. Verifies fallback windowing engages with `LOW_CONFIDENCE` warning. |
| **SC-13** | Dual Page Number Discrepancy | Ingest PDF where physical page 20 corresponds to printed page 1. Verifies `physical_page` and `printed_page` are tracked separately. |
| **SC-14** | Malformed Financial Table | Ingest page with jagged tabular cells. Verifies `TABLE_MALFORMED` warning logged, markdown padded, raw text preserved. |
| **SC-15** | Resume Interrupted Crawl | Kill crawler midway through 10 URLs. Restart crawler. Verifies crawler resumes from queue without duplicate downloads. |
| **SC-16** | Unified Canonical Convergence | Process identical content via local file, direct URL, and website crawler. Verifies all three produce byte-identical canonical chunks. |
