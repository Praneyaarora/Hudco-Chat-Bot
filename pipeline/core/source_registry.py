"""
Persistent Source Registry and Version Lineage Manager for HUDCO Corpus.
File: pipeline/core/source_registry.py

Governs multi-report source tracking, official provenance, content hashes,
version lineage, download status, and safe incremental updates.
Guarantees atomic file updates using temporary file replacement to prevent
state corruption across process interrupts.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from config.settings import settings

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class SourceRegistry:
    """
    Persistent registry of all discovered and ingested annual reports.
    Tracks provenance, fiscal year, content hashes, version lineage, and status.
    """

    DEFAULT_REGISTRY_PATH = settings.DATA_DIR / "source_registry.json"

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = Path(registry_path or self.DEFAULT_REGISTRY_PATH)
        self.data: Dict[str, Any] = {
            "sources": {},
            "version_lineage": {},
            "schema_version": "2.0"
        }
        self._load()

    def _load(self) -> None:
        """Loads registry from JSON file or migrates legacy registry if missing."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict) and "sources" in loaded:
                        self.data = loaded
                        logger.info(f"Loaded {len(self.data['sources'])} sources from {self.registry_path}")
                        return
            except Exception as e:
                logger.error(f"Error loading {self.registry_path}: {e}. Creating fresh state.")

        # Check for legacy document_registry.json to migrate
        legacy_path = settings.DOCUMENT_REGISTRY_JSON
        if legacy_path.exists():
            try:
                with open(legacy_path, "r", encoding="utf-8") as lf:
                    legacy_data = json.load(lf)
                docs = legacy_data.get("documents", {})
                for fname, dinfo in docs.items():
                    src_id = f"hudco_{fname.replace('.', '_')}"
                    self.register_source(
                        source_id=src_id,
                        document_id=f"doc_{fname.replace('.pdf', '')}",
                        source_url=dinfo.get("source_url", f"https://www.hudco.org.in/writereaddata/{fname}"),
                        report_title=f"HUDCO Annual Report ({fname})",
                        report_fiscal_year="2025-26" if "ar26" in fname else None,
                        discovery_method="legacy_migration",
                        http_status=dinfo.get("http_status", 200),
                        remote_size_bytes=dinfo.get("size_bytes"),
                        download_status="DOWNLOADED_LOCAL" if dinfo.get("file_path") and os.path.exists(dinfo.get("file_path")) else "NOT_DOWNLOADED",
                        verification_status="OFFICIALLY_VERIFIED" if "ar26" in fname else "URL_VERIFIED_CONTENT_UNVERIFIED",
                        content_sha256=dinfo.get("sha256"),
                        file_path=dinfo.get("file_path"),
                    )
                logger.info(f"Migrated {len(docs)} legacy documents into source registry.")
                self.save()
            except Exception as le:
                logger.warning(f"Could not migrate legacy registry: {le}")

    def save(self) -> None:
        """Persists registry to disk atomically via temporary file rename."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.registry_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp_path, self.registry_path)
            logger.debug(f"Saved source registry atomically to {self.registry_path}")
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            logger.error(f"Failed to save source registry: {e}")
            raise

    def register_source(
        self,
        source_id: str,
        document_id: str,
        source_url: str,
        report_title: Optional[str] = None,
        report_fiscal_year: Optional[str] = None,
        publication_date: Optional[str] = None,
        discovery_method: str = "direct_server_probe",
        source_type: str = "direct_url",
        http_status: Optional[int] = None,
        remote_size_bytes: Optional[int] = None,
        download_status: str = "NOT_DOWNLOADED",
        verification_status: str = "UNVERIFIED",
        content_sha256: Optional[str] = None,
        file_path: Optional[str] = None,
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Registers a new report source or updates an existing source without overwriting history."""
        sources = self.data.setdefault("sources", {})
        now = utc_now_iso()

        if source_id in sources:
            record = sources[source_id]
            # Detect content hash change
            old_hash = record.get("content_sha256")
            if content_sha256 and old_hash and content_sha256 != old_hash:
                # Content changed! Record version lineage
                lineage = self.data.setdefault("version_lineage", {}).setdefault(source_id, [])
                lineage.append({
                    "version_number": len(lineage) + 1,
                    "superseded_sha256": old_hash,
                    "superseded_at": now,
                    "superseded_file_path": record.get("file_path"),
                })
                record["version_count"] = record.get("version_count", 1) + 1
                logger.info(f"Source {source_id} hash updated: {old_hash[:8]} -> {content_sha256[:8]}")

            # Update mutable fields safely without downgrading local download or verification status
            if document_id:
                record["document_id"] = document_id
            if report_title:
                record["report_title"] = report_title
            if report_fiscal_year:
                record["report_fiscal_year"] = report_fiscal_year
            if publication_date:
                record["publication_date"] = publication_date
            if http_status is not None:
                record["http_status"] = http_status
            if remote_size_bytes is not None:
                record["remote_size_bytes"] = remote_size_bytes

            # Do not downgrade DOWNLOADED_LOCAL to NOT_DOWNLOADED
            if download_status and (record.get("download_status") != "DOWNLOADED_LOCAL" or download_status == "DOWNLOADED_LOCAL"):
                record["download_status"] = download_status

            # Do not downgrade OFFICIALLY_VERIFIED to UNVERIFIED
            if verification_status and (record.get("verification_status") != "OFFICIALLY_VERIFIED" or verification_status == "OFFICIALLY_VERIFIED"):
                record["verification_status"] = verification_status

            if content_sha256:
                record["content_sha256"] = content_sha256
            if file_path:
                record["file_path"] = file_path
            record["last_checked_at"] = now
            if warnings:
                record.setdefault("warnings", []).extend([w for w in warnings if w not in record.get("warnings", [])])
        else:
            record = {
                "source_id": source_id,
                "document_id": document_id,
                "source_url": source_url,
                "resolved_url": source_url,
                "source_type": source_type,
                "report_title": report_title or f"HUDCO Report {source_id}",
                "report_fiscal_year": report_fiscal_year,
                "publication_date": publication_date,
                "discovery_method": discovery_method,
                "http_status": http_status,
                "content_type": "application/pdf",
                "remote_size_bytes": remote_size_bytes,
                "download_status": download_status,
                "verification_status": verification_status,
                "content_sha256": content_sha256,
                "file_path": file_path,
                "version_count": 1,
                "first_seen_at": now,
                "last_checked_at": now,
                "warnings": list(warnings or []),
            }
            sources[source_id] = record

        self.save()
        return record

    def record_download(self, source_id: str, file_path: str, content_sha256: str, size_bytes: int) -> None:
        """Updates source status to DOWNLOADED_LOCAL with exact hash and file path."""
        if source_id not in self.data.get("sources", {}):
            raise KeyError(f"Source {source_id} not found in registry")
        record = self.data["sources"][source_id]
        record["file_path"] = str(file_path)
        record["content_sha256"] = content_sha256
        record["remote_size_bytes"] = size_bytes
        record["download_status"] = "DOWNLOADED_LOCAL"
        record["last_checked_at"] = utc_now_iso()
        self.save()

    def record_processing(
        self,
        source_id: str,
        chunk_count: int,
        output_dir: str,
        processing_status: str = "PROCESSED",
    ) -> None:
        """Records successful ingestion/chunking results on a source record."""
        if source_id not in self.data.get("sources", {}):
            raise KeyError(f"Source {source_id} not found in registry")
        record = self.data["sources"][source_id]
        record["processing_status"] = processing_status
        record["chunk_count"] = chunk_count
        record["output_dir"] = str(output_dir)
        record["last_checked_at"] = utc_now_iso()
        self.save()

    def record_error(self, source_id: str, error_message: str) -> None:
        """Records error on a source without removing it from the registry."""
        if source_id in self.data.get("sources", {}):
            record = self.data["sources"][source_id]
            record["last_error"] = str(error_message)
            record["verification_status"] = "ERROR"
            record["last_checked_at"] = utc_now_iso()
            self.save()

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single source record by ID."""
        return self.data.get("sources", {}).get(source_id)

    def get_version_lineage(self, source_id: str) -> List[Dict[str, Any]]:
        """Returns the chronological list of superseded versions for a source."""
        return self.data.get("version_lineage", {}).get(source_id, [])

    def register_failed_request(
        self, source_id: str, error_message: str, http_status: Optional[int] = None
    ) -> None:
        """
        Records a failed request or network error for a source without removing
        or resetting previously ingested evidence.
        """
        sources = self.data.setdefault("sources", {})
        now = utc_now_iso()
        if source_id in sources:
            rec = sources[source_id]
            if http_status is not None:
                rec["http_status"] = http_status
            rec["last_error"] = str(error_message)
            rec["last_checked_at"] = now
            rec.setdefault("warnings", []).append(f"Request failed at {now}: {error_message}")
        else:
            rec = {
                "source_id": source_id,
                "document_id": f"doc_{source_id}",
                "source_url": "",
                "http_status": http_status,
                "last_error": str(error_message),
                "download_status": "FAILED",
                "verification_status": "ERROR",
                "first_seen_at": now,
                "last_checked_at": now,
                "warnings": [f"Request failed: {error_message}"],
            }
            sources[source_id] = rec
        self.save()


    def list_sources(
        self,
        verification_status: Optional[str] = None,
        fiscal_year: Optional[str] = None,
        downloaded_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Lists registered sources with optional filtering."""
        results = []
        for src in self.data.get("sources", {}).values():
            if verification_status and src.get("verification_status") != verification_status:
                continue
            if fiscal_year and src.get("report_fiscal_year") != fiscal_year:
                continue
            if downloaded_only and src.get("download_status") != "DOWNLOADED_LOCAL":
                continue
            results.append(src)
        return results

    def sync_from_inventory(self, inventory_path: Optional[Path] = None) -> int:
        """Imports discovered items from annual_reports_inventory.json."""
        inv_path = Path(inventory_path or (settings.DATA_DIR / "annual_reports_inventory.json"))
        if not inv_path.exists():
            logger.warning(f"Inventory file {inv_path} not found.")
            return 0

        with open(inv_path, "r", encoding="utf-8") as f:
            items = json.load(f)

        count = 0
        for item in items:
            self.register_source(
                source_id=item["source_id"],
                document_id=item.get("document_id", f"doc_{item['source_id']}"),
                source_url=item["source_url"],
                report_title=item.get("report_title"),
                report_fiscal_year=item.get("report_fiscal_year"),
                publication_date=item.get("publication_date"),
                discovery_method=item.get("discovery_method", "direct_server_probe"),
                http_status=item.get("http_status"),
                remote_size_bytes=item.get("remote_size_bytes"),
                download_status=item.get("download_status", "NOT_DOWNLOADED"),
                verification_status=item.get("verification_status", "UNVERIFIED"),
                content_sha256=item.get("content_sha256"),
                warnings=item.get("warnings"),
            )
            count += 1

        logger.info(f"Synced {count} items from inventory into SourceRegistry.")
        return count
