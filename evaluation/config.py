"""
Configuration settings and directory paths for the HUDCO Evaluation Harness.
"""

from pathlib import Path

# Base Paths
EVAL_DIR = Path(__file__).resolve().parent
ROOT_DIR = EVAL_DIR.parent
DATA_DIR = ROOT_DIR / "data"

# Raw and Intermediate Source Paths
RAW_PDF_PATH = DATA_DIR / "raw" / "annual_reports" / "ar26.pdf"
SECTIONS_DIR = DATA_DIR / "intermediate" / "sections"
STAGE1_MANIFEST_PATH = (
    DATA_DIR / "intermediate" / "ingestion_runs" / "run_20260923_212152" / "stage1_manifest.json"
)

# Evaluation Workspace Paths
EVAL_DATA_DIR = EVAL_DIR / "data"
EVAL_EXTRACTED_DIR = EVAL_DIR / "extracted"
EVAL_RUNS_DIR = EVAL_DIR / "runs"

# File Paths for Artifacts
EXTRACTED_PAGES_FILE = EVAL_EXTRACTED_DIR / "extracted_pages.jsonl"
EVALUATION_CHUNKS_FILE = EVAL_EXTRACTED_DIR / "evaluation_chunks.jsonl"
EXTRACTION_SUMMARY_FILE = EVAL_EXTRACTED_DIR / "extraction_summary.json"
DEFAULT_QUESTIONS_FILE = EVAL_DATA_DIR / "evaluation_questions.jsonl"

# Extraction & Chunking Parameters
MIN_PAGE_CHAR_WARN = 100         # Flag pages with fewer chars as suspiciously short
MIN_CHUNK_CHARS = 150            # Minimum meaningful chunk character count
TARGET_CHUNK_CHARS = 1000        # Target character window per chunk
CHUNK_OVERLAP_CHARS = 150        # Overlap characters between chunks within a page

# BM25 Hyperparameters
BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_TOP_K = 5

# Ollama Endpoint Configuration (Optional Phase 6)
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT_SECONDS = 60

def init_eval_directories() -> None:
    """Ensure all required evaluation directories exist."""
    for p in [EVAL_DATA_DIR, EVAL_EXTRACTED_DIR, EVAL_RUNS_DIR]:
        p.mkdir(parents=True, exist_ok=True)
