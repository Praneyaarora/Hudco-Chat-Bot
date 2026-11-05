"""
Robust Document Downloader with Single-Pass Incremental Hashing, Deduplication,
Temporary File Streaming, and Filename Collision Protection.
"""

import os
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests
import pypdf

from config.settings import settings

logger = logging.getLogger(__name__)

class DocumentDownloader:
    """
    Handles streaming acquisition of HUDCO documents with single-pass SHA-256 computation,
    signature verification, retry logic, and deduplication.
    """

    PDF_MAGIC_BYTES = b"%PDF-"

    def __init__(
        self,
        target_dir: Optional[Path] = None,
        registry_path: Optional[Path] = None,
        chunk_size: int = settings.DOWNLOAD_CHUNK_SIZE_BYTES,
        timeout: int = settings.DOWNLOAD_TIMEOUT_SECONDS,
        max_retries: int = settings.DOWNLOAD_MAX_RETRIES,
    ):
        self.target_dir = target_dir or settings.RAW_DATA_DIR
        self.registry_path = registry_path or settings.DOCUMENT_REGISTRY_JSON
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.max_retries = max_retries
        self._ensure_registry()

    def _ensure_registry(self) -> None:
        """Initialize local document registry file if not present."""
        if not self.registry_path.exists():
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump({"documents": {}, "hashes": {}}, f, indent=2)

    def _read_registry(self) -> Dict[str, Any]:
        """Read local registry state."""
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read registry ({e}), creating fresh state.")
            return {"documents": {}, "hashes": {}}

    def _write_registry(self, data: Dict[str, Any]) -> None:
        """Persist registry state."""
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def lookup_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        """Check if content hash is already registered."""
        reg = self._read_registry()
        return reg.get("hashes", {}).get(sha256_hash)

    def register_document(self, metadata: Dict[str, Any]) -> None:
        """Register document in local registry."""
        reg = self._read_registry()
        sha256 = metadata["sha256"]
        file_name = metadata["file_name"]
        reg.setdefault("hashes", {})[sha256] = metadata
        reg.setdefault("documents", {})[file_name] = metadata
        self._write_registry(reg)

    @staticmethod
    def compute_sha256_of_file(file_path: Path, chunk_size: int = 65536) -> str:
        """Compute SHA-256 checksum of an existing file in streaming chunks."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def validate_local_pdf(file_path: Path, min_size: int = 10000) -> Tuple[bool, str]:
        """
        Validates that a local PDF exists, has plausible size (> 10KB), contains %PDF- magic bytes,
        does not contain HTML error text, and can be structurally opened and parsed by pypdf.
        """
        if not file_path.exists():
            return False, "File does not exist."
        size = file_path.stat().st_size
        if size < min_size:
            return False, f"File size ({size} bytes) is suspiciously small for a full Annual Report."
        try:
            with open(file_path, "rb") as f:
                header = f.read(1024)
            if DocumentDownloader.PDF_MAGIC_BYTES not in header:
                if b"<html" in header.lower() or b"<!doctype html" in header.lower():
                    return False, "File is an HTML error page, not a valid PDF."
                return False, "File lacks %PDF- magic signature."
            reader = pypdf.PdfReader(str(file_path))
            if len(reader.pages) == 0:
                return False, "PDF has 0 pages."
            return True, f"Valid PDF ({len(reader.pages)} pages)"
        except Exception as e:
            return False, f"PDF structural validation failed: {str(e)}"

    def download_file(
        self,
        url: str,
        destination_filename: str,
        subdirectory: str = "annual_reports",
        expected_sha256: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stream download a remote file to a temporary .part location, validate PDF magic bytes,
        compute SHA-256 incrementally in one pass, deduplicate against existing content,
        and protect existing files from collision.
        """
        dest_folder = self.target_dir / subdirectory
        dest_folder.mkdir(parents=True, exist_ok=True)

        received_filename = destination_filename
        part_filepath = dest_folder / f"{destination_filename}.part"

        start_time = time.time()
        attempt = 0
        response = None
        hasher = hashlib.sha256()
        bytes_downloaded = 0
        first_chunk = True

        while attempt < self.max_retries:
            attempt += 1
            try:
                logger.info(f"Downloading (attempt {attempt}/{self.max_retries}): {url}")
                hasher = hashlib.sha256()
                bytes_downloaded = 0
                first_chunk = True

                session = requests.Session()
                response = session.get(url, stream=True, timeout=self.timeout)
                response.raise_for_status()

                # Detect if the server returned HTML content instead of binary/pdf
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    raise ValueError(
                        f"Server returned HTML error page (Content-Type: '{content_type}') instead of PDF binary for {url}."
                    )

                # Stream to .part file while computing SHA-256 in one pass
                with open(part_filepath, "wb") as f_out:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if not chunk:
                            continue

                        if first_chunk:
                            # PDF Magic Signature Validation
                            if not chunk.startswith(self.PDF_MAGIC_BYTES):
                                # Check if it's within first 1024 bytes (some PDFs have leading whitespace/BOM)
                                if self.PDF_MAGIC_BYTES not in chunk[:1024]:
                                    raise ValueError(
                                        f"Invalid PDF stream from {url}: Missing %PDF- magic signature."
                                    )
                            # Extra check: ensure not HTML text in body
                            if b"<html" in chunk[:1024].lower() or b"<!doctype html" in chunk[:1024].lower():
                                raise ValueError(
                                    f"Invalid PDF stream from {url}: Stream contains HTML document markers."
                                )
                            first_chunk = False

                        f_out.write(chunk)
                        hasher.update(chunk)
                        bytes_downloaded += len(chunk)

                # Successfully written to .part
                break

            except Exception as err:
                logger.warning(f"Download attempt {attempt} failed: {err}")
                if part_filepath.exists():
                    try:
                        part_filepath.unlink()
                    except OSError:
                        pass
                if attempt >= self.max_retries:
                    raise RuntimeError(f"Download failed after {self.max_retries} attempts for {url}: {err}") from err
                time.sleep(2 ** attempt)

        elapsed_time = time.time() - start_time
        calculated_sha256 = hasher.hexdigest()

        if expected_sha256 and calculated_sha256 != expected_sha256:
            if part_filepath.exists():
                part_filepath.unlink()
            raise ValueError(f"Checksum mismatch! Expected: {expected_sha256}, Got: {calculated_sha256}")

        # 1. Content Deduplication Check
        existing_doc = self.lookup_hash(calculated_sha256)
        if existing_doc and Path(existing_doc["file_path"]).exists():
            logger.info(f"Deduplication hit: SHA-256 {calculated_sha256[:12]} already registered as {existing_doc['file_name']}.")
            if part_filepath.exists():
                part_filepath.unlink()
            return {
                "status": "DUPLICATE",
                "is_duplicate": True,
                "received_filename": received_filename,
                "file_path": existing_doc["file_path"],
                "file_name": existing_doc["file_name"],
                "sha256": calculated_sha256,
                "size_bytes": existing_doc["size_bytes"],
                "source_url": url,
                "elapsed_seconds": round(elapsed_time, 2),
                "http_status": response.status_code if response else 200,
                "content_type": response.headers.get("Content-Type", "") if response else "application/pdf",
                "canonical_document": existing_doc
            }

        # 2. Filename Collision Protection
        target_path = dest_folder / destination_filename
        final_filename = destination_filename

        if target_path.exists():
            target_sha = self.compute_sha256_of_file(target_path)
            if target_sha == calculated_sha256:
                logger.info(f"Target file {destination_filename} already has identical content.")
                if part_filepath.exists():
                    part_filepath.unlink()
                result_meta = {
                    "status": "DUPLICATE",
                    "is_duplicate": True,
                    "received_filename": received_filename,
                    "file_path": str(target_path),
                    "file_name": target_path.name,
                    "sha256": calculated_sha256,
                    "size_bytes": target_path.stat().st_size,
                    "source_url": url,
                    "elapsed_seconds": round(elapsed_time, 2),
                    "http_status": response.status_code if response else 200,
                    "content_type": response.headers.get("Content-Type", "") if response else "application/pdf"
                }
                self.register_document(result_meta)
                return result_meta
            else:
                # Same filename, different content -> create disambiguated name
                stem = Path(destination_filename).stem
                suffix = Path(destination_filename).suffix
                final_filename = f"{stem}_{calculated_sha256[:8]}{suffix}"
                target_path = dest_folder / final_filename
                logger.warning(f"Filename collision on {destination_filename}! Storing safely as {final_filename}.")

        # 3. Rename .part to final destination
        if part_filepath.exists():
            part_filepath.replace(target_path)

        result_meta = {
            "status": "DOWNLOADED",
            "is_duplicate": False,
            "received_filename": received_filename,
            "file_path": str(target_path),
            "file_name": target_path.name,
            "sha256": calculated_sha256,
            "size_bytes": bytes_downloaded,
            "source_url": url,
            "elapsed_seconds": round(elapsed_time, 2),
            "http_status": response.status_code if response else 200,
            "content_type": response.headers.get("Content-Type", "") if response else "application/pdf"
        }

        self.register_document(result_meta)
        logger.info(f"Successfully ingested raw file: {target_path.name} ({bytes_downloaded / (1024*1024):.2f} MB)")
        return result_meta

    def ingest_local_file(
        self,
        local_path: Path,
        received_filename: Optional[str] = None,
        source_url: Optional[str] = None,
        subdirectory: str = "annual_reports"
    ) -> Dict[str, Any]:
        """
        Ingest an existing local file without downloading, validating magic bytes and calculating SHA-256.
        """
        if not local_path.exists():
            raise FileNotFoundError(f"Local file does not exist: {local_path}")

        with open(local_path, "rb") as f:
            header = f.read(1024)
            if self.PDF_MAGIC_BYTES not in header:
                raise ValueError(f"File {local_path.name} is not a valid PDF (%PDF- header missing).")

        sha256 = self.compute_sha256_of_file(local_path)
        size_bytes = local_path.stat().st_size
        rec_name = received_filename or local_path.name

        existing_doc = self.lookup_hash(sha256)
        if existing_doc and Path(existing_doc["file_path"]).resolve() == local_path.resolve():
            return {
                "status": "EXISTING_LOCAL",
                "is_duplicate": False,
                "received_filename": rec_name,
                "file_path": str(local_path.resolve()),
                "file_name": local_path.name,
                "sha256": sha256,
                "size_bytes": size_bytes,
                "source_url": source_url,
                "http_status": 200,
                "content_type": "application/pdf"
            }

        result_meta = {
            "status": "LOCAL_FILE",
            "is_duplicate": bool(existing_doc),
            "received_filename": rec_name,
            "file_path": str(local_path.resolve()),
            "file_name": local_path.name,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "source_url": source_url,
            "http_status": 200,
            "content_type": "application/pdf"
        }

        self.register_document(result_meta)
        return result_meta
