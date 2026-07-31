"""GPU / VRAM sampler (phase 2).

Joins two vendor-agnostic sources:
  * dxgi.enumerate_adapters()         -> total VRAM + vendor/name/LUID
  * perf_counters GPU adapter/process -> live dedicated/shared usage per
                                         adapter and per PID

Works identically for AMD, NVIDIA, and Intel: DXGI gives totals, Windows GPU
perf counters give live usage, joined by the adapter LUID.
"""

from __future__ import annotations

from . import dxgi, perf_counters
from .sample import GpuAdapter


def sample_gpus() -> list[GpuAdapter]:
    """Snapshot all real GPUs with live dedicated/shared usage filled in."""
    adapters = dxgi.enumerate_adapters()
    adapter_usage = perf_counters.enumerate_gpu_adapter_usage()

    out: list[GpuAdapter] = []
    for info in adapters:
        usage = adapter_usage.get(info.luid_key, {"dedicated": 0, "shared": 0})
        out.append(
            GpuAdapter(
                name=info.name,
                vendor=info.vendor,
                vendor_id=info.vendor_id,
                total_bytes=info.total_bytes,
                shared_total_bytes=info.shared_total_bytes,
                dedicated_used_bytes=usage["dedicated"],
                shared_used_bytes=usage["shared"],
                luid_key=info.luid_key,
            )
        )
    return out


def process_vram_bytes() -> dict[int, int]:
    """Return {pid: vram_bytes} for all GPU-using processes (summed per pid)."""
    return perf_counters.enumerate_gpu_process_usage()
