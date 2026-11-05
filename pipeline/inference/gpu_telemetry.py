"""
GPU and Hardware Telemetry Module.
File: pipeline/inference/gpu_telemetry.py

Provides real-time hardware telemetry for NVIDIA GPUs (RTX 5060 Laptop GPU)
via nvidia-smi CLI and torch.cuda inspections. Never fabricates metrics;
reports 'unavailable' when hardware monitors cannot be accessed.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_gpu_telemetry() -> Dict[str, Any]:
    """
    Collects live GPU metrics using nvidia-smi.
    Returns:
        dict containing:
            available: bool
            gpu_name: str
            utilization_gpu_pct: Optional[float]
            vram_used_mb: Optional[float]
            vram_total_mb: Optional[float]
            vram_free_mb: Optional[float]
            temperature_c: Optional[float]
            driver_version: Optional[str]
            error: Optional[str]
    """
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        return {
            "available": False,
            "gpu_name": "N/A (nvidia-smi not found)",
            "utilization_gpu_pct": None,
            "vram_used_mb": None,
            "vram_total_mb": None,
            "vram_free_mb": None,
            "temperature_c": None,
            "driver_version": None,
            "error": "nvidia-smi executable not located in system PATH",
        }

    try:
        cmd = [
            nvsmi,
            "--query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total,memory.free,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=3.0)
        line = res.stdout.strip()
        if not line:
            return {
                "available": False,
                "gpu_name": "Unknown",
                "utilization_gpu_pct": None,
                "vram_used_mb": None,
                "vram_total_mb": None,
                "vram_free_mb": None,
                "temperature_c": None,
                "driver_version": None,
                "error": "nvidia-smi returned empty output",
            }

        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7:
            gpu_name = parts[0]
            driver_ver = parts[1]
            util_gpu = float(parts[2]) if parts[2] not in ("N/A", "[Not Supported]") else None
            used_mb = float(parts[3]) if parts[3] not in ("N/A", "[Not Supported]") else None
            total_mb = float(parts[4]) if parts[4] not in ("N/A", "[Not Supported]") else None
            free_mb = float(parts[5]) if parts[5] not in ("N/A", "[Not Supported]") else None
            temp_c = float(parts[6]) if parts[6] not in ("N/A", "[Not Supported]") else None

            return {
                "available": True,
                "gpu_name": gpu_name,
                "driver_version": driver_ver,
                "utilization_gpu_pct": util_gpu,
                "vram_used_mb": used_mb,
                "vram_total_mb": total_mb,
                "vram_free_mb": free_mb,
                "temperature_c": temp_c,
                "error": None,
            }
        else:
            return {
                "available": False,
                "gpu_name": "Incomplete query output",
                "utilization_gpu_pct": None,
                "vram_used_mb": None,
                "vram_total_mb": None,
                "vram_free_mb": None,
                "temperature_c": None,
                "driver_version": None,
                "error": f"Unexpected nvidia-smi output: '{line}'",
            }

    except Exception as e:
        logger.warning(f"Could not read GPU telemetry from nvidia-smi: {e}")
        return {
            "available": False,
            "gpu_name": "Unavailable",
            "utilization_gpu_pct": None,
            "vram_used_mb": None,
            "vram_total_mb": None,
            "vram_free_mb": None,
            "temperature_c": None,
            "driver_version": None,
            "error": str(e),
        }
