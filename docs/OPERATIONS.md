# Operations & Maintenance Guide

**Document Identifier**: `HUDCO-OPS-GUIDE-2026-V1`  
**Target Path**: `docs/OPERATIONS.md`  
**Audience**: DevOps, Pipeline Operators, and Integration Engineers  
**System Scope**: Layers 1 through 4 (Document Ingestion, Chunking, Indexing, and Retrieval)

---

## 1. Environment & Setup

### 1.1 System Requirements
- **OS**: Windows 10/11 / Windows Server 2019+ or Linux (Ubuntu 20.04+).
- **Python**: Version 3.10 to 3.12 64-bit.
- **Memory**: Minimum 4 GB RAM (8 GB recommended for coordinate table extraction on 500+ page PDFs).
- **Disk**: 1 GB free space for canonical chunk JSONL files and manifests.

### 1.2 Virtual Environment Activation
```powershell
# Navigate to workspace
cd "c:\Users\Praneya Arora\Desktop\Hudco"

# Activate Python virtual environment
.\.venv\Scripts\Activate.ps1
```

---

## 2. Execution Modes & Workflows

All operational workflows are managed via the unified orchestrator:

```powershell
python scripts/run_pipeline.py [OPTIONS]
```

### 2.1 Normal Automated Run (Artifact Reuse Mode)
```powershell
python scripts/run_pipeline.py
```
- **Behavior**:
  1. Checks `.pipeline.lock` to ensure no concurrent job is running.
  2. Runs preflight checks on Python environment and source files.
  3. Computes SHA-256 of `data/raw/annual_reports/ar26.pdf`.
  4. Checks `data/output_chunks/run_full_ar26_p1_520_v1/`. If the source SHA-256 matches existing validated artifacts, **safely reuses** the canonical chunks without re-parsing the 520-page PDF.
  5. Validates canonical schemas and checks for 0 duplicate chunk IDs.
  6. Constructs the Layer 4 BM25 table-aware index.
  7. Runs full 125-test suite and 20-question retrieval benchmark.
  8. Verifies all 6 acceptance gates.
  9. Emits `pipeline_manifest.json`, `pipeline_quality_report.md`, and updates `latest_approved_run.json`.
- **Runtime**: ~8 to 10 seconds.
- **Exit Code**: `0` on success.

### 2.2 Validation-Only Mode (Fast Verification)
```powershell
python scripts/run_pipeline.py --validation-only
```
- **Behavior**: Skips ingestion entirely. Asserts that approved canonical artifacts exist, builds the in-memory index, runs all tests and retrieval benchmarks, and confirms acceptance gates.
- **Use Case**: Continuous Integration (CI) health checks, deployment readiness smoke tests, or post-configuration validation.
- **Runtime**: ~8 seconds.

### 2.3 Forced Reprocessing Mode (Full PDF Extraction)
```powershell
python scripts/run_pipeline.py --force-reprocess
```
- **Behavior**: Ignores cached canonical chunks. Invokes `PDFDocumentAdapter` to extract all 520 pages, runs `StructuralAnalyzer` (TOC discovery), invokes `HierarchicalChunker`, and writes fresh outputs to a newly created timestamped directory:
  `data/output_chunks/run_YYYYMMDD_HHMMSS_<hash8>/`
- **Use Case**: After updating coordinate extraction logic, table heuristics, or chunk size parameters.
- **Runtime**: ~45 to 90 seconds.

---

## 3. Concurrency Control & Process Locking

To prevent race conditions, corrupted JSONL files, or partial index states during automated sweeps:
- **Lock File**: `.pipeline.lock` in the workspace root.
- **Lock Payload**: JSON dictionary containing PID, ISO timestamp, hostname, and Python version:
  ```json
  {
    "pid": 14280,
    "started_at": "2026-10-21T03:55:18.123456+00:00",
    "host": "WORKSTATION-01",
    "python": "3.12.2 (tags/v3.12.2:473dc4d, Feb  6 2024, 17:53:58)"
  }
  ```
- **Conflict Handling**: If another instance attempts to execute while `.pipeline.lock` is held by an active OS process, it immediately halts with **Exit Code `2`** and logs:
  `PIPELINE LOCK CONFLICT: Pipeline is locked by active process PID 14280.`
- **Stale Lock Recovery**: If an earlier run was terminated unexpectedly (e.g. system reboot or SIGKILL), the runner automatically detects that the recorded PID is not running, logs a warning, cleans up the dead lock, and acquires a fresh lock cleanly.

---

## 4. Acceptance Gates & Publication Safety

The orchestrator enforces a zero-defect publication gate before marking a run as approved:

| Gate | Acceptance Condition | Action on Breach |
|---|---|---|
| **Gate 1: Test Suite** | 100% pass rate (0 failures, 0 errors across 125 tests) | Abort publication, Exit Code 1 |
| **Gate 2: Canonical Schema** | 0 duplicate chunk IDs, valid physical page indices | Abort publication, Exit Code 1 |
| **Gate 3: Retrieval Recall@5** | $\ge 80.0\%$ (Current: 100.0%) | Abort publication, Exit Code 1 |
| **Gate 4: Page Citation Acc@1** | $\ge 60.0\%$ (Current: 88.2%) | Abort publication, Exit Code 1 |
| **Gate 5: Abstention Precision** | $100.0\%$ (0 false abstentions on valid queries) | Abort publication, Exit Code 1 |
| **Gate 6: Abstention Recall** | $\ge 66.7\%$ (Current: 100.0%) | Abort publication, Exit Code 1 |

> [!CAUTION]
> If any gate fails, `latest_approved_run.json` is **NOT updated**. The previous approved run remains authoritative, ensuring downstream services never consume degraded or unverified chunks.

---

## 5. Automated Scheduling via Windows Task Scheduler

To execute unattended daily or weekly pipeline sweeps, configure a Windows Scheduled Task.

### 5.1 Step-by-Step Task Scheduler Configuration

1. **Open Task Scheduler**:
   Press `Win + R`, type `taskschd.msc`, and press `Enter`.
2. **Create Basic Task**:
   - Name: `HUDCO_Document_Pipeline_Daily_Sweep`
   - Description: `Daily validation and retrieval audit for HUDCO Annual Report pipeline.`
3. **Trigger**:
   - Select **Daily** (e.g., 03:00 AM).
4. **Action**:
   - Select **Start a program**.
5. **Program / Script**:
   ```
   C:\Users\Praneya Arora\Desktop\Hudco\.venv\Scripts\python.exe
   ```
6. **Add Arguments**:
   ```
   scripts\run_pipeline.py --validation-only
   ```
7. **Start in (Working Directory)**:
   ```
   C:\Users\Praneya Arora\Desktop\Hudco
   ```
8. **Settings**:
   - Check *"Do not start a new instance if an instance is already running"*.
   - Check *"Run whether user is logged on or not"*.

### 5.2 Command-Line Creation via PowerShell (Admin)
Alternatively, create the scheduled task automatically using `schtasks`:

```powershell
$action = "C:\Users\Praneya Arora\Desktop\Hudco\.venv\Scripts\python.exe scripts\run_pipeline.py --validation-only"
$cwd = "C:\Users\Praneya Arora\Desktop\Hudco"

schtasks /create /tn "HUDCO_Pipeline_Sweep" `
  /tr "$action" `
  /sc daily `
  /st 03:00 `
  /ru SYSTEM `
  /f
```

---

## 6. Failure Recovery & Troubleshooting

### Problem 1: Exit Code 2 (Process Locked)
- **Cause**: A previous process terminated abruptly leaving `.pipeline.lock`.
- **Diagnosis**: Inspect `.pipeline.lock` in project root. Check if the PID is active in Windows Task Manager.
- **Resolution**:
  ```powershell
  # If process is definitely not running, manually remove lock:
  Remove-Item .pipeline.lock -Force
  ```

### Problem 2: Exit Code 3 (Preflight Error)
- **Cause**: Input PDF `data/raw/annual_reports/ar26.pdf` or evaluation questions file is missing.
- **Resolution**: Verify file paths and ensure the raw document asset is located in `data/raw/annual_reports/`.

### Problem 3: Exit Code 1 (Gate Failure)
- **Cause**: One or more unit tests failed or retrieval recall fell below the calibrated gate.
- **Diagnosis**: Inspect `retrieval_eval_report.json` and `pipeline_quality_report.md` in the effective run directory.
- **Resolution**: Fix the failing test or investigate query term degradation before attempting publication.

---

## 7. Source Registry and Multi-Report Operations

### 7.1 Source Registry Overview
The multi-report inventory is managed via `pipeline/core/source_registry.py` and persisted atomically to `data/source_registry.json`.
- **Atomic Writes**: Writes to `.tmp` first, then replaces the target file using OS-level atomic replace to protect against process interruptions.
- **Inventory File**: `data/annual_reports_inventory.json` tracks the verified status of all candidate reports (`ar15.pdf` through `ar26.pdf`).
- **Version Lineage**: When an upstream document's content hash changes, the previous hash and file path are preserved under `version_lineage[source_id]`.
- **Historical Evidence Retention**: A failed HTTP request or temporary upstream unavailability logs warnings and errors under `warnings` without deleting previously ingested evidence or raw files.

### 7.2 Running Multi-Report Pilots
To execute a controlled extraction on an individual historical report (e.g., `ar24.pdf`):
```powershell
python scripts/run_ar24_pilot.py
```
This isolates the run into `data/output_chunks/run_pilot_ar24_p1_426_v1/`, verifies 100% unique chunk IDs and fiscal-year tagging (`2023-24`), updates `SourceRegistry`, and preserves `latest_approved_run.json` locked to `ar26.pdf`.

### 7.3 Large Report Guard (`ar25.pdf`)
`ar25.pdf` is approximately 132.5 MB. Do not attempt direct extraction without configuring memory bounds and a streaming worker plan. It is marked as `OFFICIALLY_VERIFIED` but `NOT_DOWNLOADED` pending a dedicated memory and extraction plan.

### 7.4 Controlled Stage C Multi-Report Pilot Runner
The Stage C pipeline orchestrates bounded, sequential ingestion of historical reports (`ar21.pdf`, `ar22.pdf`, `ar23.pdf`) via:
```powershell
python scripts/run_stage_c_pilot.py [--reports ar21,ar22,ar23] [--force-reprocess]
```
- **Validation**: Performs preflight hash checks, `%PDF-` header verification, streaming download with atomic `.part` promotion, and checks chunk-level invariant contracts.
- **TOC Calibration**: Employs automated TOC offset calibration against physical page boundaries ($0 \le \text{offset} \le 12$) to achieve fine-grained section segmentation.
- **Outputs**: Writes distinct run directories (`data/output_chunks/run_full_arNN_p1_XXX_v1/`) and generates `data/stage_c_pilot_summary.json`. The approved baseline `latest_approved_run.json` remains unaltered.

### 7.5 Multi-Report Evaluation
To benchmark lexical BM25 retrieval across multiple historical reports:
```powershell
python scripts/run_multi_report_eval.py
```
- Evaluates 32 independently verified cross-year queries (historical facts, multi-page provenance, tables, comparative financial metrics, and unanswerable questions) defined in `evaluation/data/multi_report_evaluation_questions.jsonl`.
- Compares dual-report (`ar24` + `ar26`, 5,042 chunks) versus full five-report Stage C corpus (11,518 chunks), outputting precision, recall@K, MRR, and abstention metrics to `data/multi_report_retrieval_evaluation_report.json`.

### 7.6 Source & Document Registry Reconciliation
To synchronize `data/annual_reports_inventory.json`, `data/source_registry.json`, and `data/document_registry.json` idempotently without overwriting lineage:
```powershell
python scripts/reconcile_registry_ids.py
```
- Enforces canonical identifier standards: `source_id = "hudco_annual_report_arNN"` and `document_id = "doc_arNN"`.
- Preserves version lineage, historical timestamps, and prevents regression of existing verified statuses.

### 7.7 Artifact Reuse Guard
Managed via `pipeline/core/artifact_guard.py`:
- Rejects reuse of cached runs if source SHA-256 changes, chunk schema is violated, chunk count does not match manifest, duplicate chunk IDs exist, or required artifacts (`chunks.jsonl`, `manifest.json`, `sections.json`, `tables.json`) are missing.
- Prevents silent re-use of corrupted runs and enforces `--force-reprocess` on configuration drift.

### 7.8 Full-Corpus Annual Report Ingestion & Verification Runner
Orchestrates end-to-end ingestion across all accessible annual reports (`ar15.pdf` through `ar26.pdf`) with strict integrity gates:
```powershell
python scripts/run_full_corpus_ingestion.py [--reports ar15,ar16,ar17...] [--force-reprocess]
```
- **Sequential Ingestion**: Runs reports sequentially to constrain memory footprint.
- **Genuine Content Identity Verification**: `DocumentIdentityVerifier` inspects title, fiscal year, report number, company name, and minimum page count before admitting reports to the corpus.
- **Deterministic Artifact Reuse**: Safely reuses verified completed runs without reprocessing, reporting historical execution metrics accurately as `None` rather than fabricated numbers.
- **Baseline Protection**: Asserts `latest_approved_run.json` and `run_full_ar26_p1_520_v1` remain completely unchanged before and after execution.
- **Audit Summary**: Produces `data/full_corpus_ingestion_summary.json` with per-report page counts, chunk counts, peak memory usage, artifact directories, and verification status.



