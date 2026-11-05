"""
Command-Line Interface for HUDCO End-to-End Pipeline.
File: scripts/run_pipeline.py

Usage:
    python scripts/run_pipeline.py [OPTIONS]

Options:
    --force-reprocess     Force extraction and chunking even if source hash is unchanged.
    --validation-only     Run validation, tests, and retrieval eval without ingestion.
    --source-file PATH    Path to raw input PDF (default: data/raw/annual_reports/ar26.pdf).
    --questions PATH      Path to evaluation questions (default: evaluation/data/evaluation_questions.jsonl).
    --output-dir PATH     Base output directory (default: data/output_chunks).
"""

import sys
import logging
import argparse
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.runner import EndToEndPipelineRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HUDCO Document Processing Pipeline (Layers 1-4 End-to-End Runner)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Force full document extraction and chunking even if source document is unchanged.",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="Run preflight, artifact validation, test suite, and retrieval evaluation without reprocessing.",
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw" / "annual_reports" / "ar26.pdf",
        help="Path to raw source PDF document.",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "data" / "evaluation_questions.jsonl",
        help="Path to ground-truth evaluation questions benchmark.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "output_chunks",
        help="Base directory for canonical chunk outputs and run manifests.",
    )

    args = parser.parse_args()

    runner = EndToEndPipelineRunner(
        project_root=PROJECT_ROOT,
        source_pdf=args.source_file,
        output_base_dir=args.output_dir,
        questions_path=args.questions,
        force_reprocess=args.force_reprocess,
        validation_only=args.validation_only,
    )

    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
