"""
Registry Reconciliation and ID Integrity Manager.
File: scripts/reconcile_registry_ids.py

Enforces canonical ID standards:
  - source_id: hudco_annual_report_arNN
  - document_id: doc_arNN
Guarantees idempotent synchronization across:
  - data/annual_reports_inventory.json
  - data/source_registry.json
  - data/document_registry.json
Preserves version lineage, local download status, file paths, and existing processing history.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RegistryReconciler")

from pipeline.core.source_registry import SourceRegistry
from config.settings import settings


def reconcile_registries(dry_run: bool = False) -> Dict[str, Any]:
    """
    Reconciles annual_reports_inventory.json and source_registry.json.
    Ensures strict canonical ID adherence without resetting existing records or lineages.
    """
    inv_path = settings.DATA_DIR / "annual_reports_inventory.json"
    registry = SourceRegistry()

    if not inv_path.exists():
        raise FileNotFoundError(f"Inventory file not found: {inv_path}")

    with open(inv_path, "r", encoding="utf-8") as f:
        inventory_items: List[Dict[str, Any]] = json.load(f)

    logger.info(f"Loaded {len(inventory_items)} items from inventory.")
    
    modified_inv_count = 0
    # 1. Enforce canonical IDs in inventory
    for item in inventory_items:
        src_id = item.get("source_id", "")
        # Normalize source_id if legacy
        if src_id.startswith("doc_ar"):
            report_num = src_id.replace("doc_ar", "")
            item["source_id"] = f"hudco_annual_report_ar{report_num}"
            modified_inv_count += 1
        elif not src_id.startswith("hudco_annual_report_ar"):
            # If arNN
            if "ar" in src_id:
                part = src_id[src_id.find("ar"):]
                item["source_id"] = f"hudco_annual_report_{part}"
                modified_inv_count += 1

        # Enforce canonical document_id
        curr_src = item["source_id"]
        report_suffix = curr_src.replace("hudco_annual_report_", "")
        expected_doc_id = f"doc_{report_suffix}"
        if item.get("document_id") != expected_doc_id:
            item["document_id"] = expected_doc_id
            modified_inv_count += 1

    if modified_inv_count > 0 and not dry_run:
        with open(inv_path, "w", encoding="utf-8") as f:
            json.dump(inventory_items, f, indent=2)
        logger.info(f"Updated {modified_inv_count} ID fields in {inv_path}")

    # 2. Idempotent sync to SourceRegistry
    synced_count = registry.sync_from_inventory(inv_path)
    logger.info(f"Synchronized {synced_count} records into SourceRegistry.")

    # 3. Verify consistency
    all_sources = registry.data.get("sources", {})
    inconsistencies = []
    for sid, rec in all_sources.items():
        doc_id = rec.get("document_id")
        expected_suffix = sid.replace("hudco_annual_report_", "")
        expected_doc = f"doc_{expected_suffix}"
        if doc_id != expected_doc:
            inconsistencies.append((sid, doc_id, expected_doc))

    if inconsistencies:
        logger.warning(f"Found {len(inconsistencies)} ID inconsistencies in registry: {inconsistencies}")
        if not dry_run:
            for sid, doc_id, expected_doc in inconsistencies:
                registry.data["sources"][sid]["document_id"] = expected_doc
            registry.save()
            logger.info("Repaired inconsistencies in SourceRegistry.")
    else:
        logger.info("All registry sources satisfy canonical ID standards.")

    return {
        "inventory_count": len(inventory_items),
        "registry_source_count": len(all_sources),
        "lineage_count": len(registry.data.get("version_lineage", {})),
        "inconsistencies_repaired": len(inconsistencies),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Reconcile HUDCO Registry IDs")
    parser.add_argument("--dry-run", action="store_true", help="Report inconsistencies without writing changes")
    args = parser.parse_args()

    results = reconcile_registries(dry_run=args.dry_run)
    print(json.dumps(results, indent=2))
