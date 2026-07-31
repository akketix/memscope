"""Pressure index: blend Memory Compression working set, available RAM, and
pagefile usage into a single 0..100 score plus a human-readable tier.

Tiers mirror the thresholds we measured on this machine:
  IDLE       <  3 GB compressed
  LIGHT      <  8 GB
  MODERATE   < 15 GB
  HIGH       < 22 GB
  CRITICAL   >= 22 GB
"""

from __future__ import annotations

from .sample import RamSample

_GB = 1024**3


def pressure_index(ram: RamSample) -> tuple[float, str]:
    """Return (index 0..100, tier label) for a RAM sample.

    The index is dominated by the compressed working set (the direct pressure
    symptom) and nudged by low available RAM and pagefile usage.
    """
    compressed_gb = ram.compressed_working_set_bytes / _GB

    # Primary: compressed working set mapped onto 0..100 over 0..24 GB.
    index = min(100.0, compressed_gb / 24.0 * 100.0)

    # Nudge: if available RAM is under 10% of total, add pressure.
    if ram.total_bytes > 0:
        avail_pct = ram.available_bytes / ram.total_bytes
        if avail_pct < 0.10:
            index = min(100.0, index + (0.10 - avail_pct) * 200.0)

    # Nudge: heavy pagefile use adds pressure.
    if ram.swap_percent > 50.0:
        index = min(100.0, index + (ram.swap_percent - 50.0) / 5.0)

    index = max(0.0, round(index, 1))

    if compressed_gb < 3:
        tier = "IDLE"
    elif compressed_gb < 8:
        tier = "LIGHT"
    elif compressed_gb < 15:
        tier = "MODERATE"
    elif compressed_gb < 22:
        tier = "HIGH"
    else:
        tier = "CRITICAL"

    return index, tier
