"""RAM + pagefile + Memory Compression sampler (phase 1)."""

from __future__ import annotations

import psutil

from . import perf_counters
from .sample import RamSample


def sample_ram() -> RamSample:
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    return RamSample(
        total_bytes=vm.total,
        available_bytes=vm.available,
        used_bytes=vm.used,
        percent=vm.percent,
        swap_total_bytes=sm.total,
        swap_used_bytes=sm.used,
        swap_percent=sm.percent,
        # The pressure signal: Windows compresses cold pages in RAM under load.
        compressed_working_set_bytes=perf_counters.memory_compression_working_set_bytes(),
    )
