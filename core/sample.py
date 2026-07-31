"""Single point of definition for all metric dataclasses used by MemScope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # No hard runtime import: telemetry is optional and only needed for the
    # `hardware` field, which stays None when unavailable / disabled.
    from .telemetry import HardwareSample


@dataclass(slots=True)
class RamSample:
    total_bytes: int = 0
    available_bytes: int = 0
    used_bytes: int = 0
    percent: float = 0.0
    # pagefile / swap
    swap_total_bytes: int = 0
    swap_used_bytes: int = 0
    swap_percent: float = 0.0
    # Windows "Memory Compression" pseudo-process working set (the pressure signal)
    compressed_working_set_bytes: int = 0

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024**3)

    @property
    def available_gb(self) -> float:
        return self.available_bytes / (1024**3)

    @property
    def compressed_mb(self) -> float:
        return self.compressed_working_set_bytes / (1024**2)


@dataclass(slots=True)
class ProcRow:
    pid: int
    name: str
    rss_bytes: int = 0  # working set (resident)
    private_bytes: int = 0  # committed private (the ComfyUI 24GB anomaly)
    vram_bytes: int = 0  # filled by VRAM sampler in phase 2
    cpu_percent: float = 0.0

    @property
    def rss_mb(self) -> float:
        return self.rss_bytes / (1024**2)

    @property
    def private_gb(self) -> float:
        return self.private_bytes / (1024**3)


@dataclass(slots=True)
class GpuAdapter:
    name: str = ""
    vendor: str = "UNKNOWN"  # AMD / NVIDIA / Intel / Microsoft / Unknown
    vendor_id: int = 0
    total_bytes: int = 0  # DedicatedVideoMemory from DXGI (real VRAM)
    shared_total_bytes: int = 0
    dedicated_used_bytes: int = 0  # live, from GPU perf counters
    shared_used_bytes: int = 0
    luid_key: str = ""  # joins perf counters

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        return self.dedicated_used_bytes / (1024**3)

    @property
    def percent(self) -> float:
        return self.dedicated_used_bytes / self.total_bytes * 100.0 if self.total_bytes else 0.0


@dataclass(slots=True)
class Sample:
    """One full snapshot taken at `ts` (epoch seconds)."""

    ts: float = 0.0
    ram: RamSample = field(default_factory=RamSample)
    procs: list[ProcRow] = field(default_factory=list)
    gpus: list[GpuAdapter] = field(default_factory=list)

    # derived
    pressure_index: float = 0.0
    pressure_tier: str = "IDLE"
    # Optional hardware telemetry (temperatures, power, EXPO/XMP, disks).
    # None when hardware is unavailable or telemetry disabled; never raises.
    hardware: Optional["HardwareSample"] = None
    # Optional network/ports + per-process power attribution (phase 3).
    # Plain list/dict typed (no hard import of ports/power_attribution here)
    # so a telemetry or attribution failure never breaks the sampler.
    connections: list = field(default_factory=list)
    interfaces: list = field(default_factory=list)
    per_proc_power: dict = field(default_factory=dict)
