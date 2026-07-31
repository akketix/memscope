"""Ring-buffer history of samples for MemScope time-series charts.

All access happens on the main thread (the MainWindow._update callback), so
no locking is required. We store only the lightweight metrics the charts need
rather than the full Sample, and trim by timestamp.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid the import cost at runtime; only needed for typing
    from .sample import Sample


class _Record:
    """Lightweight per-sample record kept in the history buffer."""

    __slots__ = (
        "ts",
        "ram_used_gb",
        "ram_available_gb",
        "compressed_mb",
        "pressure_index",
        "pressure_tier",
        "gpu_used_gb",
    )

    def __init__(self, ts: float) -> None:
        self.ts = ts
        self.ram_used_gb: float = 0.0
        self.ram_available_gb: float = 0.0
        self.compressed_mb: float = 0.0
        self.pressure_index: float = 0.0
        self.pressure_tier: str = "IDLE"
        self.gpu_used_gb: dict[str, float] = {}


class HistoryBuffer:
    """Keeps the last ``max_seconds`` of sample metrics for the charts."""

    def __init__(self, max_seconds: float = 3600.0) -> None:
        self.max_seconds = max_seconds
        self._records: list[_Record] = []

    # ------------------------------------------------------------------ #
    # ingest
    # ------------------------------------------------------------------ #
    def append(self, sample: Sample) -> None:
        """Store the relevant metrics from ``sample`` and drop stale records."""
        rec = _Record(sample.ts)
        rec.ram_used_gb = sample.ram.used_gb
        rec.ram_available_gb = sample.ram.available_gb
        rec.compressed_mb = sample.ram.compressed_mb
        rec.pressure_index = sample.pressure_index
        rec.pressure_tier = sample.pressure_tier
        rec.gpu_used_gb = {g.luid_key: g.used_gb for g in sample.gpus}
        self._records.append(rec)
        self._trim(sample.ts)

    def _trim(self, now_ts: float) -> None:
        cutoff = now_ts - self.max_seconds
        # Records are appended in time order, so the stale ones are at the head.
        idx = 0
        for rec in self._records:
            if rec.ts >= cutoff:
                break
            idx += 1
        if idx:
            del self._records[:idx]

    # ------------------------------------------------------------------ #
    # accessors
    # ------------------------------------------------------------------ #
    def ram_used(self) -> tuple[list[float], list[float]]:
        ts = [r.ts for r in self._records]
        vals = [r.ram_used_gb for r in self._records]
        return ts, vals

    def ram_available(self) -> tuple[list[float], list[float]]:
        ts = [r.ts for r in self._records]
        vals = [r.ram_available_gb for r in self._records]
        return ts, vals

    def compressed_mb(self) -> tuple[list[float], list[float]]:
        ts = [r.ts for r in self._records]
        vals = [r.compressed_mb for r in self._records]
        return ts, vals

    def pressure_index(self) -> tuple[list[float], list[float]]:
        ts = [r.ts for r in self._records]
        vals = [r.pressure_index for r in self._records]
        return ts, vals

    def gpu_dedicated(self, luid_key: str) -> tuple[list[float], list[float]]:
        ts: list[float] = []
        vals: list[float] = []
        for rec in self._records:
            if luid_key in rec.gpu_used_gb:
                ts.append(rec.ts)
                vals.append(rec.gpu_used_gb[luid_key])
        return ts, vals

    def recent_tiers(self, n: int = 60) -> list[str]:
        if n <= 0:
            return []
        return [r.pressure_tier for r in self._records[-n:]]

    # ------------------------------------------------------------------ #
    # maintenance
    # ------------------------------------------------------------------ #
    def clear(self) -> None:
        self._records.clear()
