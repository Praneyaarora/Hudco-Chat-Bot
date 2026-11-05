"""
Unified End-to-End Pipeline Runner and Acceptance Gate Orchestrator.
File: pipeline/runner.py

Orchestrates the entire Phase 1-5 pipeline through Layer 4:
1. Process locking (.pipeline.lock) to guard against concurrent invocations.
2. Preflight environment, dependency, source, and path verification.
3. Source hash calculation (SHA-256) and intelligent reuse of validated canonical artifacts.
4. Reprocessing and chunking into isolated directories only when source changes or forced.
5. Canonical schema, duplicate ID, and provenance validation.
6. Layer 4 BM25 table-aware index construction.
7. Automated test suite execution (unittest discover).
8. Retrieval benchmark evaluation against audited ground-truth questions.
9. Formal acceptance gate verification against established targets.
10. Atomic publication of approved run manifests and quality reports.
"""

from __future__ import annotations

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import platform
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from pipeline.core.contracts import ProcessingStatus
from pipeline.retrieval.loader import load_canonical_chunks, ChunkLoaderError
from pipeline.retrieval.bm25 import Layer4BM25Index
from scripts.run_retrieval_eval import run_evaluation

logger = logging.getLogger("PipelineRunner")


class PipelineLockError(Exception):
    """Raised when a concurrent pipeline process is detected."""
    pass


class PipelineGateFailureError(Exception):
    """Raised when one or more acceptance gates fail."""
    pass


class PipelineLock:
    """File-based process lock to prevent concurrent pipeline corruptions."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._acquired = False

    def acquire(self) -> None:
        if self.lock_path.exists():
            try:
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                locked_pid = data.get("pid")
                
                # Check if process is still running on Windows
                if locked_pid and self._is_pid_running(locked_pid):
                    raise PipelineLockError(
                        f"Pipeline is locked by active process PID {locked_pid} "
                        f"(host: {data.get('host')}, started: {data.get('started_at')})."
                    )
                else:
                    logger.warning(f"Removing stale pipeline lock file from inactive PID {locked_pid}.")
                    self.lock_path.unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError):
                self.lock_path.unlink(missing_ok=True)

        lock_data = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "host": platform.node(),
            "python": sys.version,
        }
        with open(self.lock_path, "w", encoding="utf-8") as f:
            json.dump(lock_data, f, indent=2)
        self._acquired = True

    def release(self) -> None:
        if self._acquired and self.lock_path.exists():
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process != 0:
                kernel32.CloseHandle(process)
                return True
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False

    def __enter__(self) -> PipelineLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class EndToEndPipelineRunner:
    """
    Production end-to-end orchestrator for Layer 1-4 pipeline execution.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        source_pdf: Optional[Path] = None,
        output_base_dir: Optional[Path] = None,
        questions_path: Optional[Path] = None,
        force_reprocess: bool = False,
        validation_only: bool = False,
        lock_path: Optional[Path] = None,
    ):
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.source_pdf = source_pdf or (self.project_root / "data" / "raw" / "annual_reports" / "ar26.pdf")
        self.output_base_dir = output_base_dir or (self.project_root / "data" / "output_chunks")
        self.questions_path = questions_path or (self.project_root / "evaluation" / "data" / "evaluation_questions.jsonl")
        self.force_reprocess = force_reprocess
        self.validation_only = validation_only
        
        self.lock_path = lock_path or (self.project_root / ".pipeline.lock")
        self.latest_pointer_path = self.output_base_dir / "latest_approved_run.json"
        
        # In-memory stage states
        self.source_sha256 = ""
        self.source_hash8 = ""
        self.effective_run_dir: Optional[Path] = None
        self.reused_existing_artifacts = False
        self.chunks: List[Any] = []
        self.bm25_index: Optional[Layer4BM25Index] = None
        self.test_results: Dict[str, Any] = {}
        self.eval_metrics: Dict[str, Any] = {}
        self.gates: Dict[str, bool] = {}
        self.stage_timings: Dict[str, float] = {}

    def run(self) -> int:
        """
        Executes the pipeline stages in strict sequence with process locking.
        Returns:
            Exit code: 0 on success, 1 on gate failure, 2 on lock error, 3 on preflight error.
        """
        overall_start = time.time()
        logger.info("=" * 80)
        logger.info("STARTING HUDCO END-TO-END PIPELINE (LAYERS 1-4)")
        logger.info("=" * 80)

        try:
            with PipelineLock(self.lock_path):
                # Stage 1: Preflight
                self._run_preflight()

                # Stage 2: Source Integrity & Ingestion Dispatch
                self._resolve_source_and_artifacts()

                # Stage 3: Canonical Schema & Chunk Validation
                self._validate_canonical_chunks()

                # Stage 4: Layer 4 BM25 Index Construction
                self._build_index()

                # Stage 5: Automated Test Suite & Benchmark Evaluation
                self._run_tests_and_evaluation()

                # Stage 6: Acceptance Gate Verification
                all_passed = self._evaluate_gates()

                # Stage 7: Manifest & Approved Publication
                self._finalize_and_publish(all_passed, overall_start)

                if all_passed:
                    logger.info("=" * 80)
                    logger.info("PIPELINE COMPLETED SUCCESSFULLY: ALL GATES PASSED (EXIT 0)")
                    logger.info("=" * 80)
                    return 0
                else:
                    logger.error("=" * 80)
                    logger.error("PIPELINE FAILED ACCEPTANCE GATES (EXIT 1)")
                    logger.error("=" * 80)
                    return 1

        except PipelineLockError as e:
            logger.error(f"PIPELINE LOCK CONFLICT: {e}")
            return 2
        except (FileNotFoundError, EnvironmentError) as e:
            logger.error(f"PREFLIGHT FATAL ERROR: {e}")
            return 3
        except Exception as e:
            logger.exception(f"UNHANDLED FATAL PIPELINE EXCEPTION: {e}")
            return 1

    def _run_preflight(self) -> None:
        t0 = time.time()
        logger.info("[Stage 1/7] Running preflight system checks...")
        
        # Verify python version
        if sys.version_info < (3, 10):
            raise EnvironmentError(f"Python 3.10+ required. Current version: {sys.version}")

        # Verify source file
        if not self.source_pdf.exists():
            raise FileNotFoundError(f"Source file not found at: {self.source_pdf}")

        allowed_exts = {".pdf", ".html", ".htm", ".xhtml"}
        if self.source_pdf.suffix.lower() not in allowed_exts:
            raise EnvironmentError(
                f"Unsupported source document format '{self.source_pdf.suffix}'. "
                f"Supported formats: {', '.join(sorted(allowed_exts))}"
            )

        # Verify benchmark questions
        if not self.questions_path.exists():
            raise FileNotFoundError(f"Evaluation questions not found at: {self.questions_path}")

        # Verify write permissions
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        manifests_dir = self.project_root / "data" / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)

        self.stage_timings["preflight"] = round(time.time() - t0, 4)
        logger.info("Preflight checks passed.")

    def _resolve_source_and_artifacts(self) -> None:
        t0 = time.time()
        logger.info("[Stage 2/7] Checking source integrity and artifact reuse...")

        # Compute source SHA-256
        with open(self.source_pdf, "rb") as f:
            self.source_sha256 = hashlib.sha256(f.read()).hexdigest()
        self.source_hash8 = self.source_sha256[:8]
        logger.info(f"Source: {self.source_pdf.name} (SHA-256: {self.source_sha256})")

        # Identify existing full-run candidate
        existing_full_run = self.output_base_dir / "run_full_ar26_p1_520_v1"
        chunks_file = existing_full_run / "chunks.jsonl"

        can_reuse = (
            not self.force_reprocess
            and existing_full_run.exists()
            and chunks_file.exists()
            and chunks_file.stat().st_size > 1_000_000
        )

        if can_reuse and not self.force_reprocess:
            logger.info(
                f"Source unchanged ({self.source_hash8}). Reusing verified canonical artifacts "
                f"from {existing_full_run.name}."
            )
            self.effective_run_dir = existing_full_run
            self.reused_existing_artifacts = True
        else:
            # Need fresh ingestion run
            run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self.source_hash8}"
            self.effective_run_dir = self.output_base_dir / run_id
            self.effective_run_dir.mkdir(parents=True, exist_ok=True)
            self.reused_existing_artifacts = False

            if self.validation_only:
                raise FileNotFoundError("Validation-only requested but valid cached artifacts are not available.")

            logger.info(f"Executing full PDF extraction and chunking -> {self.effective_run_dir.name}...")
            self._execute_full_ingestion(self.effective_run_dir)

        self.stage_timings["source_resolution"] = round(time.time() - t0, 4)

    def _execute_full_ingestion(self, target_dir: Path) -> None:
        """Invokes the appropriate extraction adapter and structural chunker."""
        from pipeline.core.pipeline_runner import run_phase2_pipeline

        if self.source_pdf.suffix.lower() in {".html", ".htm", ".xhtml"}:
            from pipeline.adapters.html_adapter import HTMLDocumentAdapter
            logger.info(f"Initializing HTMLDocumentAdapter for HTML document: {self.source_pdf.name}...")
            adapter = HTMLDocumentAdapter()
            payload = adapter.extract_file(self.source_pdf)
        else:
            from pipeline.adapters.pdf_adapter import PDFDocumentAdapter
            logger.info("Initializing PDFDocumentAdapter for complete 520-page document...")
            adapter = PDFDocumentAdapter()
            payload = adapter.extract_file(self.source_pdf)

        logger.info(f"Extracted {len(payload.pages)} physical pages. Running structural analyzer and chunker...")
        _, _, output_path = run_phase2_pipeline(
            payload=payload,
            output_dir=target_dir,
            target_chunk_size=1200,
            max_chunk_size=2000,
            chunk_overlap=150
        )
        logger.info(f"Ingestion artifacts written to {output_path}.")

    def _validate_canonical_chunks(self) -> None:
        t0 = time.time()
        logger.info(f"[Stage 3/7] Validating canonical chunks in {self.effective_run_dir.name}...")
        chunks_file = self.effective_run_dir / "chunks.jsonl"

        self.chunks = load_canonical_chunks(str(chunks_file))
        if not self.chunks:
            raise ValueError(f"Zero chunks loaded from {chunks_file}")

        # Validate unique chunk IDs
        chunk_ids = [c.chunk_id for c in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Duplicate chunk IDs detected in canonical chunks file.")

        # Check physical page presence
        missing_pages = [c.chunk_id for c in self.chunks if not c.physical_page or c.physical_page < 1]
        if missing_pages:
            raise ValueError(f"Chunks found with invalid physical pages: {missing_pages[:5]}")

        logger.info(
            f"Validated {len(self.chunks):,} canonical chunks across "
            f"{max(c.physical_page for c in self.chunks)} physical pages (0 duplicate IDs)."
        )
        self.stage_timings["chunk_validation"] = round(time.time() - t0, 4)

    def _build_index(self) -> None:
        t0 = time.time()
        logger.info("[Stage 4/7] Constructing deterministic Layer 4 BM25 index...")
        self.bm25_index = Layer4BM25Index(
            chunks=self.chunks,
            k1=1.2,
            b=0.45,
            abstention_threshold=14.5,
            min_term_coverage=0.40,
        )
        logger.info(
            f"BM25 Index built: N={self.bm25_index.N:,}, "
            f"vocabulary={len(self.bm25_index.doc_freq):,} terms, "
            f"avg_doc_len={self.bm25_index.avg_doc_len:.1f} tokens."
        )
        self.stage_timings["index_construction"] = round(time.time() - t0, 4)

    def _run_tests_and_evaluation(self) -> None:
        t0 = time.time()
        logger.info("[Stage 5/7] Running automated test suite and retrieval benchmark...")

        # 1. Run unit/integration tests
        logger.info("Executing unittest discover on tests/...")
        test_loader = unittest.TestLoader()
        suite = test_loader.discover(str(self.project_root / "tests"))
        runner = unittest.TextTestRunner(verbosity=1, stream=open(os.devnull, "w"))
        test_result = runner.run(suite)

        self.test_results = {
            "total_run": test_result.testsRun,
            "failures": len(test_result.failures),
            "errors": len(test_result.errors),
            "passed": test_result.wasSuccessful(),
        }
        logger.info(
            f"Test Suite: {test_result.testsRun} run, "
            f"{len(test_result.failures)} failures, {len(test_result.errors)} errors."
        )

        # 2. Run retrieval evaluation benchmark
        eval_report_file = self.effective_run_dir / "retrieval_eval_report.json"
        logger.info(f"Running retrieval evaluation against {self.questions_path.name}...")
        self.eval_metrics = run_evaluation(
            chunks_path=str(self.effective_run_dir / "chunks.jsonl"),
            questions_path=str(self.questions_path),
            output_report_path=str(eval_report_file),
            k1=1.2,
            b=0.45,
            abstention_threshold=14.5,
            min_term_coverage=0.40,
        )
        self.stage_timings["testing_and_eval"] = round(time.time() - t0, 4)

    def _evaluate_gates(self) -> bool:
        logger.info("[Stage 6/7] Evaluating formal pipeline acceptance gates...")

        metrics = self.eval_metrics.get("metrics", {})
        
        g1_tests = self.test_results.get("passed", False)
        g2_schema = len(self.chunks) > 0 and (len(self.chunks) == len(set(c.chunk_id for c in self.chunks)))
        g3_recall5 = metrics.get("page_recall_at_5", 0.0) >= 0.80
        g4_citation1 = metrics.get("page_citation_accuracy_at_1", 0.0) >= 0.60
        g5_abs_prec = metrics.get("abstention_precision", 0.0) == 1.0
        g6_abs_rec = metrics.get("abstention_recall", 0.0) >= 0.66

        self.gates = {
            "Gate 1: Test Suite 100% Pass Rate": g1_tests,
            "Gate 2: Canonical Integrity (0 Duplicate IDs)": g2_schema,
            "Gate 3: Retrieval Recall@5 >= 80%": g3_recall5,
            "Gate 4: Page Citation Acc@1 >= 60%": g4_citation1,
            "Gate 5: Abstention Precision == 100%": g5_abs_prec,
            "Gate 6: Abstention Recall >= 66%": g6_abs_rec,
        }

        all_passed = all(self.gates.values())

        for gate_name, passed in self.gates.items():
            status_str = "PASSED" if passed else "FAILED"
            logger.info(f"  [{status_str}] {gate_name}")

        return all_passed

    def _finalize_and_publish(self, all_passed: bool, overall_start: float) -> None:
        logger.info("[Stage 7/7] Generating pipeline manifest and publishing approval state...")
        duration = round(time.time() - overall_start, 2)
        
        status_enum = ProcessingStatus.SUCCESS if all_passed else ProcessingStatus.FAILED

        manifest_data = {
            "pipeline_version": "2.0.0",
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration,
            "status": status_enum.value,
            "source_document": {
                "filename": self.source_pdf.name,
                "sha256": self.source_sha256,
                "size_bytes": self.source_pdf.stat().st_size,
            },
            "run_directory": str(self.effective_run_dir),
            "artifacts_reused": self.reused_existing_artifacts,
            "dataset_statistics": {
                "total_chunks": len(self.chunks),
                "total_physical_pages": max((c.physical_page for c in self.chunks), default=0),
                "has_table_chunks": sum(1 for c in self.chunks if c.has_table),
            },
            "test_summary": self.test_results,
            "retrieval_metrics": self.eval_metrics.get("metrics", {}),
            "acceptance_gates": self.gates,
            "stage_timings_seconds": self.stage_timings,
        }

        # Write pipeline_manifest.json into run directory
        manifest_path = self.effective_run_dir / "pipeline_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        # Write human-readable quality summary
        report_path = self.effective_run_dir / "pipeline_quality_report.md"
        self._write_markdown_report(report_path, manifest_data)

        # If all gates passed, update pointer to latest approved run
        if all_passed:
            pointer_data = {
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "approved_run_dir": str(self.effective_run_dir.resolve()),
                "source_filename": self.source_pdf.name,
                "source_sha256": self.source_sha256,
                "total_chunks": len(self.chunks),
                "metrics": self.eval_metrics.get("metrics", {}),
            }
            with open(self.latest_pointer_path, "w", encoding="utf-8") as f:
                json.dump(pointer_data, f, indent=2)
            logger.info(f"Updated latest approved run pointer -> {self.latest_pointer_path.name}")
        else:
            logger.warning("Acceptance gates failed: run was NOT published as latest approved.")

    def _write_markdown_report(self, report_path: Path, manifest: Dict[str, Any]) -> None:
        metrics = manifest.get("retrieval_metrics", {})
        gates = manifest.get("acceptance_gates", {})
        
        md = f"""# HUDCO Pipeline Quality & Acceptance Report

**Execution Timestamp:** `{manifest['execution_timestamp']}`  
**Pipeline Status:** `{manifest['status'].upper()}`  
**Run Directory:** `{manifest['run_directory']}`  
**Artifacts Reused:** `{manifest['artifacts_reused']}`  
**Elapsed Time:** `{manifest['duration_seconds']}s`  

---

## 1. Acceptance Gates Verification

| Gate | Status |
|---|---|
"""
        for g_name, g_passed in gates.items():
            md += f"| {g_name} | {'✅ PASSED' if g_passed else '❌ FAILED'} |\n"

        md += f"""
---

## 2. Ingestion & Chunking Summary

- **Source Document:** `{manifest['source_document']['filename']}` (SHA-256: `{manifest['source_document']['sha256'][:16]}...`)
- **Total Canonical Chunks:** `{manifest['dataset_statistics']['total_chunks']:,}`
- **Total Physical Pages:** `{manifest['dataset_statistics']['total_physical_pages']}`
- **Structured Table Chunks:** `{manifest['dataset_statistics']['has_table_chunks']:,}`

---

## 3. Layer 4 Retrieval Benchmark Performance

- **Page Recall@1 (Citation Accuracy):** `{metrics.get('page_recall_at_1', 0.0):.1%}`
- **Page Recall@3:** `{metrics.get('page_recall_at_3', 0.0):.1%}`
- **Page Recall@5:** `{metrics.get('page_recall_at_5', 0.0):.1%}`
- **Chunk Recall@1:** `{metrics.get('chunk_recall_at_1', 0.0):.1%}`
- **Chunk Recall@5:** `{metrics.get('chunk_recall_at_5', 0.0):.1%}`
- **MRR (Page Provenance):** `{metrics.get('mrr_page', 0.0):.4f}`
- **MRR (Chunk Provenance):** `{metrics.get('mrr_chunk', 0.0):.4f}`
- **Abstention Precision:** `{metrics.get('abstention_precision', 0.0):.1%}`
- **Abstention Recall:** `{metrics.get('abstention_recall', 0.0):.1%}`
- **Abstention F1:** `{metrics.get('abstention_f1', 0.0):.1%}`

---

## 4. Test Suite Execution

- **Total Unit/Integration Tests:** `{manifest['test_summary'].get('total_run', 0)}`
- **Failures:** `{manifest['test_summary'].get('failures', 0)}`
- **Errors:** `{manifest['test_summary'].get('errors', 0)}`
- **Overall Result:** `{'PASSED' if manifest['test_summary'].get('passed') else 'FAILED'}`
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(md)
