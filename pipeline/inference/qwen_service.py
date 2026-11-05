"""
Local Qwen Model Inference Service.
File: pipeline/inference/qwen_service.py

Manages lifecycle and queries to the local Qwen model (Qwen3-4B-Instruct 4-bit)
running in the CUDA-enabled Python environment on the RTX 5060 Laptop GPU.
Provides hardened subprocess lifecycle:
- Re-entrant RLock to prevent self-deadlocks on timeouts or error handling
- Dedicated background thread continuously draining stderr into bounded circular buffer
- Queue-based non-blocking line reading on stdout with adaptive timeouts (cold load vs warm inference)
- Graceful subprocess termination and cleanup (terminate -> wait -> kill)
- Provenance attribution and strict citation validation
"""

from __future__ import annotations

import collections
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from pipeline.inference.gpu_telemetry import get_gpu_telemetry
from pipeline.retrieval.contracts import RetrievalResultItem

logger = logging.getLogger(__name__)

# Default discovery paths (Configurable via environment variables)
DEFAULT_QWEN_MODEL_PATH = os.environ.get("DEFAULT_QWEN_MODEL_PATH", r"C:\Users\Praneya Arora\Desktop\qwen 4B")
DEFAULT_GPU_PYTHON_PATH = os.environ.get("DEFAULT_GPU_PYTHON_PATH", r"C:\Users\Praneya Arora\Desktop\Bajaj (sample)\.venv\Scripts\python.exe")

STARTUP_TIMEOUT_SEC = 180.0  # 3 minutes for cold-start weight loading
INFERENCE_TIMEOUT_SEC = 90.0  # 1.5 minutes for text generation
STDERR_BUFFER_SIZE = 500


def validate_citations(
    cited_chunk_ids: List[str],
    retrieved_items: List[RetrievalResultItem],
    raw_answer: str,
) -> Dict[str, Any]:
    """
    Validates generated citation markers against supplied evidence chunks.
    Ensures that every cited chunk ID actually exists in the retrieved evidence,
    and checks for invalid or out-of-range bracket citations in the raw text.
    Handles individual markers like [1], [2] as well as compound markers like [1, 2, 3].
    """
    valid_chunk_ids_set = {item.chunk_id for item in retrieved_items}
    
    # Check for bracket references like [1], [2], [1, 2, 3, 4, 5] in answer text
    bracket_blocks = re.findall(
        r"\[\s*(?:Citation:\s*|Evidence\s*(?:Item\s*)?)?(\d+(?:\s*[,–-]\s*\d+)*)\s*\]",
        raw_answer,
        re.IGNORECASE
    )
    bracket_matches = []
    for block in bracket_blocks:
        for num in re.findall(r"\d+", block):
            bracket_matches.append(int(num))

    evidence_count = len(retrieved_items)
    
    out_of_bounds_markers = [m for m in bracket_matches if m < 1 or m > evidence_count]
    grounded_cids = [cid for cid in cited_chunk_ids if cid in valid_chunk_ids_set]
    unverified_cids = [cid for cid in cited_chunk_ids if cid not in valid_chunk_ids_set]
    
    is_valid = (len(unverified_cids) == 0) and (len(out_of_bounds_markers) == 0)
    has_citations = len(bracket_matches) > 0 or len(cited_chunk_ids) > 0

    return {
        "is_valid": is_valid,
        "has_citations": has_citations,
        "total_citations_found": len(bracket_matches),
        "grounded_chunk_ids": grounded_cids,
        "unverified_chunk_ids": unverified_cids,
        "out_of_bounds_markers": out_of_bounds_markers,
        "verification_status": "VERIFIED_GROUNDED" if (is_valid and has_citations) else (
            "NO_CITATIONS" if not has_citations else "HALLUCINATED_OR_INVALID_CITATIONS"
        )
    }


def strip_citation_markers(text: str) -> str:
    """
    Robust multi-pass sanitizer that eliminates internal retrieval evidence labels,
    bracketed citation artifacts, meta-notes, dangling punctuation, and repetitive claims
    while preserving legitimate factual numbers, financial tables, and currency data.
    """
    if not text:
        return ""

    cleaned = text

    # 1. Strip raw internal evidence markers with arbitrary descriptive text inside brackets:
    # e.g. [Citation: Evidence Item – Headquarters: New Delhi, Delhi, India]
    # e.g. [Citation: Evidence Item – Key people: Sanjay Kulshrestha (Chairman & MD)]
    # e.g. [Citation: Evidence Item 1]
    # e.g. [Evidence Item [1]]
    # e.g. [Source: Wikipedia]
    cleaned = re.sub(
        r"\[\s*(?:Citation:\s*|Evidence\s*(?:Item\s*)?|Source:\s*|Ref:\s*)[^\]\n]*\]",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    # 2. Strip bracketed numeric citations: [1], [2], [1, 2, 3], [1-3], [[1]]
    cleaned = re.sub(
        r"\[\s*\[?\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]?\s*\]",
        "",
        cleaned
    )

    # 3. Strip standalone evidence item header lines if leaked into text:
    # e.g. "--- EVIDENCE ITEM [1] ---" or "Chunk ID: chunk_123"
    cleaned = re.sub(
        r"---+\s*(?:START|END)?\s*EVIDENCE\s*ITEM\s*\[?\d*\]?[^-\n]*---+",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"^(?:Chunk ID|Fiscal Year|Location|Section|Document):\s*.*$",
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE
    )

    # 4. Remove prompt echo / prefix phrases and dangling Evidence Item references:
    # e.g. "Answer: ...", "Based on the provided evidence, ...", "According to Evidence Item 1, ...", "and Evidence Item"
    cleaned = re.sub(r"^\*?\*?(?:Evidence|Answer|Response):\*?\*?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Based on (?:the )?(?:provided )?(?:evidence|annual reports?|documents?|sources?)[,\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[,\s]*(?:and\s+)?(?:in\s+|as\s+per\s+|according\s+to\s+)?Evidence\s*(?:Item\s*)?(?:\[?\d*\]?)?.*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"(?:,\s*)?(?:and\s+)?(?:in\s+|as\s+per\s+|according\s+to\s+)?Evidence\s*(?:Item\s*)?(?:\[?\d*\]?)?[:\s,]*", "", cleaned, flags=re.IGNORECASE)

    # 5. Remove trailing citation/sources blocks:
    # e.g. "Citations: [1], [2]" or "Sources: HUDCO Annual Report"
    cleaned = re.sub(
        r"\n*\s*(?:Citations?|Sources?|References?):\s*(?:\[?[^\]\n]+\]?|\d+|https?://\S+)(?:[,\s]+(?:\[?[^\]\n]+\]?|\d+|https?://\S+))*\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    # 6. Remove internal meta-notes and prompt leakage like "\n\nNote: The question asks..." or "Explanation: ..."
    cleaned = re.sub(
        r"\n+\s*(?:\*\*)?(?:Note|Explanation|Internal Note|Meta-Note|Context)(?:\*\*)?\s*:\s*.*$",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL
    )

    # 7. Clean up dangling commas and messy punctuation created by removed citation tags:
    # e.g. "Managing Director. , , ," -> "Managing Director."
    # e.g. "New Delhi, India. ," -> "New Delhi, India."
    cleaned = re.sub(r"([.!?])\s*[,;]+", r"\1", cleaned)
    cleaned = re.sub(r"(?:\s*,\s*)+(?=[.!?])", "", cleaned)
    cleaned = re.sub(r"(?:\s*,\s*)+$", ".", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\.{2,}(?!\.)", ".", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    # 8. Deduplicate identical or near-identical consecutive sentences:
    paragraphs = cleaned.split("\n\n")
    cleaned_paras = []
    for para in paragraphs:
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        unique_lines = []
        seen_line_keys = set()
        for l in lines:
            key = re.sub(r"[^\w\s]", "", l.lower()).strip()
            if key and key in seen_line_keys:
                continue
            if key:
                seen_line_keys.add(key)
            unique_lines.append(l)
        if unique_lines:
            cleaned_paras.append("\n".join(unique_lines))

    result = "\n\n".join(cleaned_paras).strip()
    return result
class QwenInferenceService:
    """
    Manages a persistent Qwen worker subprocess running on GPU with lazy startup,
    automatic restarts on fault, prompt bounding, citation verification, and telemetry.
    """

    def __init__(
        self,
        model_path: str = DEFAULT_QWEN_MODEL_PATH,
        gpu_python_path: str = DEFAULT_GPU_PYTHON_PATH,
        enabled: bool = True,
        startup_timeout: float = STARTUP_TIMEOUT_SEC,
        inference_timeout: float = INFERENCE_TIMEOUT_SEC,
    ):
        self.model_path = model_path
        self.gpu_python_path = gpu_python_path
        self.enabled = enabled
        self.startup_timeout = startup_timeout
        self.inference_timeout = inference_timeout

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()  # Must be RLock to avoid self-deadlock on timeout
        self._is_loaded = False
        self._load_error: Optional[str] = None
        self._device: str = "unknown"
        self._last_generation_metrics: Dict[str, Any] = {}

        # Worker I/O queues and buffers
        self._stdout_queue: queue.Queue = queue.Queue()
        self._stderr_buffer: collections.deque = collections.deque(maxlen=STDERR_BUFFER_SIZE)
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

    def _drain_stderr(self, pipe) -> None:
        """Background thread worker to continuously drain stderr pipe."""
        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    break
                stripped = line.strip()
                if stripped:
                    self._stderr_buffer.append(stripped)
                    if "error" in stripped.lower() or "exception" in stripped.lower():
                        logger.warning(f"[QwenWorker-stderr] {stripped}")
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _drain_stdout(self, pipe) -> None:
        """Background thread worker to read JSON responses from stdout."""
        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    break
                stripped = line.strip()
                if stripped:
                    self._stdout_queue.put(stripped)
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _ensure_worker(self) -> None:
        """Starts worker subprocess if not currently alive."""
        if not self.enabled:
            raise RuntimeError("Qwen inference service is disabled.")

        if self._process is not None and self._process.poll() is None:
            return

        python_exe = self.gpu_python_path if os.path.exists(self.gpu_python_path) else sys.executable
        worker_script = Path(__file__).parent / "qwen_worker.py"

        if not os.path.exists(self.model_path):
            self._load_error = f"Qwen model directory not found at: {self.model_path}"
            logger.error(self._load_error)
            raise FileNotFoundError(self._load_error)

        cmd = [python_exe, "-u", str(worker_script)]

        try:
            # Clear old queues
            while not self._stdout_queue.empty():
                try:
                    self._stdout_queue.get_nowait()
                except queue.Empty:
                    break

            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )

            # Start stderr draining thread
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(self._process.stderr,),
                daemon=True,
                name="qwen-worker-stderr-drainer",
            )
            self._stderr_thread.start()

            # Start stdout reading thread
            self._stdout_thread = threading.Thread(
                target=self._drain_stdout,
                args=(self._process.stdout,),
                daemon=True,
                name="qwen-worker-stdout-reader",
            )
            self._stdout_thread.start()

            self._load_error = None
            logger.info(f"Spawned Qwen worker subprocess (PID: {self._process.pid}) using {python_exe}")
        except Exception as e:
            self._load_error = f"Failed to spawn Qwen worker: {e}"
            logger.error(self._load_error)
            raise

    def preload(self) -> Dict[str, Any]:
        """Preloads model weights into GPU VRAM lazily."""
        with self._lock:
            try:
                self._ensure_worker()
                # Clear stale messages
                while not self._stdout_queue.empty():
                    try:
                        self._stdout_queue.get_nowait()
                    except queue.Empty:
                        break

                req = {"action": "preload", "model_path": self.model_path}
                assert self._process and self._process.stdin
                self._process.stdin.write(json.dumps(req) + "\n")
                self._process.stdin.flush()

                try:
                    line = self._stdout_queue.get(timeout=self.startup_timeout)
                except queue.Empty:
                    recent_stderr = list(self._stderr_buffer)[-10:]
                    self.close()
                    raise TimeoutError(
                        f"Qwen model preload timed out after {self.startup_timeout}s. Stderr: {recent_stderr}"
                    )

                res = json.loads(line)
                if res.get("status") == "ok":
                    self._is_loaded = True
                    detail = res.get("detail", {})
                    self._device = detail.get("device", "cuda:0")
                    return detail
                else:
                    raise RuntimeError(res.get("message", "Model load failed"))
            except Exception as e:
                self._load_error = str(e)
                self._is_loaded = False
                return {"status": "error", "message": str(e)}

    def generate(
        self,
        query: str,
        retrieved_items: List[RetrievalResultItem],
        max_new_tokens: int = 192,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Executes grounded QA inference using retrieved canonical chunks.
        Never throws unhandled exceptions; returns clean failure state on fault.
        """
        if not self.enabled:
            return {
                "status": "disabled",
                "answer": "Local Qwen model inference is disabled by configuration.",
                "is_refusal": True,
                "cited_chunk_ids": [],
                "error": None,
            }

        # Format evidence payloads from canonical chunks
        evidence_payload = [
            {
                "chunk_id": item.chunk_id,
                "source_filename": item.source_filename,
                "document_id": item.document_id,
                "fiscal_year": item.fiscal_year,
                "citation_label": item.citation_label,
                "physical_page": item.physical_page,
                "section_title": item.section_title,
                "content": item.content,
            }
            for item in retrieved_items
        ]

        t0 = time.perf_counter()

        with self._lock:
            # If model is not loaded yet, query timeout includes startup time
            query_timeout = (self.startup_timeout + self.inference_timeout) if not self._is_loaded else self.inference_timeout

            try:
                self._ensure_worker()

                # Clear stale messages
                while not self._stdout_queue.empty():
                    try:
                        self._stdout_queue.get_nowait()
                    except queue.Empty:
                        break

                req = {
                    "action": "generate",
                    "query": query,
                    "evidence": evidence_payload,
                    "model_path": self.model_path,
                    "max_new_tokens": max_new_tokens,
                    "temperature": temperature,
                }

                assert self._process and self._process.stdin
                self._process.stdin.write(json.dumps(req) + "\n")
                self._process.stdin.flush()

                try:
                    line = self._stdout_queue.get(timeout=query_timeout)
                except queue.Empty:
                    recent_stderr = list(self._stderr_buffer)[-10:]
                    self.close()
                    total_time_ms = (time.perf_counter() - t0) * 1000.0
                    return {
                        "status": "inference_timeout",
                        "answer": f"Inference engine timed out after {query_timeout:.0f}s. Stderr: {recent_stderr}",
                        "is_refusal": True,
                        "cited_chunk_ids": [],
                        "evidence_truncated": False,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "generation_time_ms": 0.0,
                        "total_service_latency_ms": round(total_time_ms, 2),
                        "device": self._device,
                        "citation_validation": {
                            "is_valid": False,
                            "has_citations": False,
                            "verification_status": "TIMEOUT",
                        },
                        "error": f"Inference engine timed out after {query_timeout:.0f}s",
                    }

                res = json.loads(line)
                if res.get("status") == "error":
                    raise RuntimeError(res.get("message", "Worker inference error"))

                total_time_ms = (time.perf_counter() - t0) * 1000.0
                res["total_service_latency_ms"] = round(total_time_ms, 2)
                self._is_loaded = True
                self._device = res.get("device", "cuda:0")

                # Perform citation validation
                citation_val = validate_citations(
                    cited_chunk_ids=res.get("cited_chunk_ids", []),
                    retrieved_items=retrieved_items,
                    raw_answer=res.get("answer", ""),
                )
                res["citation_validation"] = citation_val
                res["clean_answer"] = strip_citation_markers(res.get("answer", ""))
                res["answer"] = res["clean_answer"]

                self._last_generation_metrics = res
                return res

            except Exception as e:
                logger.error(f"Qwen inference error: {e}")
                total_time_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "status": "inference_error",
                    "answer": f"Inference engine failure: {str(e)}",
                    "is_refusal": True,
                    "cited_chunk_ids": [],
                    "evidence_truncated": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "generation_time_ms": 0.0,
                    "total_service_latency_ms": round(total_time_ms, 2),
                    "device": self._device,
                    "citation_validation": {
                        "is_valid": False,
                        "has_citations": False,
                        "verification_status": "INFERENCE_ERROR",
                    },
                    "error": str(e),
                }

    def get_status(self) -> Dict[str, Any]:
        """Returns live runtime observability metrics for Qwen and hardware."""
        gpu_metrics = get_gpu_telemetry()
        worker_alive = self._process is not None and self._process.poll() is None

        if not worker_alive:
            self._is_loaded = False

        return {
            "model_path": self.model_path,
            "model_identifier": "unsloth/Qwen3-4B-Instruct-2507-unsloth-bnb-4bit",
            "model_quantization": "4-bit NF4 (bitsandbytes)",
            "worker_alive": worker_alive,
            "is_loaded": self._is_loaded,
            "device": self._device if self._is_loaded else ("standby" if worker_alive else "offline"),
            "gpu_telemetry": gpu_metrics,
            "last_generation_metrics": self._last_generation_metrics,
            "load_error": self._load_error,
            "recent_stderr_lines": list(self._stderr_buffer)[-5:],
        }

    def close(self) -> None:
        """Terminates worker subprocess cleanly."""
        with self._lock:
            if self._process is not None:
                try:
                    if self._process.stdin and self._process.poll() is None:
                        self._process.stdin.write(json.dumps({"action": "unload"}) + "\n")
                        self._process.stdin.flush()
                except Exception:
                    pass

                try:
                    self._process.terminate()
                    self._process.wait(timeout=3.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass

                self._process = None
                self._is_loaded = False
                logger.info("Closed Qwen worker subprocess.")


# Global singleton instance
_GLOBAL_QWEN_SERVICE: Optional[QwenInferenceService] = None


def get_qwen_service() -> QwenInferenceService:
    global _GLOBAL_QWEN_SERVICE
    if _GLOBAL_QWEN_SERVICE is None:
        # On Render or cloud environments without local GPU worker, disable Qwen automatically
        is_render = bool(os.environ.get("RENDER"))
        has_paths = os.path.exists(DEFAULT_QWEN_MODEL_PATH) or os.path.exists(DEFAULT_GPU_PYTHON_PATH)
        enabled = (not is_render) and has_paths
        _GLOBAL_QWEN_SERVICE = QwenInferenceService(enabled=enabled)
    return _GLOBAL_QWEN_SERVICE
