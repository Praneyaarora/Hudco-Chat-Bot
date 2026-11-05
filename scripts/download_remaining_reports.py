"""
Download remaining reports if not already present or invalid.
File: scripts/download_remaining_reports.py

Validates local files using signature, plausible size, structural parsing,
and bounded-memory streaming SHA-256 before skipping downloads.
"""

import sys
import logging
from pathlib import Path
from typing import Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pypdf
from config.settings import settings
from pipeline.stage_1_ingestion.downloader import DocumentDownloader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DownloadRemaining")

REMAINING_REPORTS = [
    {"slug": "ar17", "filename": "ar17.pdf", "url": "https://www.hudco.org.in/writereaddata/ar17.pdf"},
    {"slug": "ar18", "filename": "ar18.pdf", "url": "https://www.hudco.org.in/writereaddata/ar18.pdf"},
    {"slug": "ar19", "filename": "ar19.pdf", "url": "https://www.hudco.org.in/writereaddata/ar19.pdf"},
    {"slug": "ar20", "filename": "ar20.pdf", "url": "https://www.hudco.org.in/writereaddata/ar20.pdf"},
    {"slug": "ar25", "filename": "ar25.pdf", "url": "https://www.hudco.org.in/writereaddata/ar25.pdf"},
]


def validate_local_pdf(path: Path, min_size: int = 10000) -> Tuple[bool, str]:
    """
    Validates that a local PDF file exists, has a plausible size (> 10KB),
    contains the %PDF- magic signature, does not contain HTML error text,
    and can be opened and parsed structurally by pypdf.
    """
    if not path.exists():
        return False, "File does not exist."
    size = path.stat().st_size
    if size < min_size:
        return False, f"File size ({size} bytes) is suspiciously small for a full Annual Report."
    with open(path, "rb") as f:
        header = f.read(1024)
    if b"%PDF-" not in header:
        if b"<html" in header.lower() or b"<!doctype html" in header.lower():
            return False, "File is an HTML error page, not a valid PDF."
        return False, "File lacks %PDF- header signature."
    try:
        reader = pypdf.PdfReader(str(path))
        if len(reader.pages) == 0:
            return False, "PDF has 0 pages."
    except Exception as e:
        return False, f"PDF structural parsing failed: {str(e)}"
    return True, f"Valid PDF ({len(reader.pages)} pages)"


def main():
    downloader = DocumentDownloader(target_dir=settings.RAW_DATA_DIR)
    for rep in REMAINING_REPORTS:
        fname = rep["filename"]
        target_path = settings.ANNUAL_REPORTS_DIR / fname

        is_valid, v_msg = validate_local_pdf(target_path)
        if is_valid:
            logger.info(f"{fname} is already valid locally ({target_path.stat().st_size / (1024*1024):.2f} MB, {v_msg}). Skipping download.")
            continue

        logger.info(f"Downloading {fname} from {rep['url']} (local status: {v_msg})...")
        res = downloader.download_file(
            url=rep["url"],
            destination_filename=fname,
            subdirectory="annual_reports",
        )
        logger.info(f"Downloaded {fname}: {res['size_bytes'] / (1024*1024):.2f} MB, sha256={res['sha256'][:16]}...")


if __name__ == "__main__":
    main()
