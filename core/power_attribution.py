"""CPU package power attribution per process.

Estimates each process's share of the CPU package power from per-pid CPU-time
deltas. Maintains module-level prev-state so successive calls produce
non-zero deltas; the first call seeds state and returns attribution only on
the second call.

Everything here is best-effort: hardware telemetry is optional and may be
unavailable, psutil may lose a pid between ticks, etc. Nothing in this module
ever raises to the caller.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import psutil

from .sample import ProcRow

if TYPE_CHECKING:
    from .telemetry import HardwareSample

# Module-level prev state: pid -> cumulative cpu time (user+system seconds)
# and the timestamp of the last attribution call.
_prev_cpu_times: dict[int, float] = {}
_prev_ts: float = 0.0


def _pid_cpu_time(pid: int) -> float | None:
    """Cumulative CPU time (user+system) for a pid, or None on failure."""
    try:
        p = psutil.Process(pid)
        ct = p.cpu_times()
        return (ct.user or 0.0) + (ct.system or 0.0)
    except Exception:
        return None


def cpu_package_watts(hardware: HardwareSample | None) -> float:
    """Best-effort CPU package power (watts) from a HardwareSample.

    Prefers a SensorReading in ``hardware.cpu.powers`` whose name contains
    "package" (case-insensitive); otherwise the max CPU power reading;
    otherwise 0.0. Never raises.
    """
    try:
        if hardware is None:
            return 0.0
        cpu = getattr(hardware, "cpu", None)
        if cpu is None:
            return 0.0
        powers = getattr(cpu, "powers", None) or []
        if not powers:
            return 0.0
        pkg = None
        for sr in powers:
            try:
                name = sr.name or ""
            except Exception:
                name = ""
            if "package" in name.lower():
                try:
                    return float(sr.value)
                except Exception:
                    continue
            if pkg is None:
                pkg = sr
        if pkg is not None:
            try:
                return float(pkg.value)
            except Exception:
                return 0.0
        return 0.0
    except Exception:
        return 0.0


def attributed(processes: list[ProcRow], hardware: HardwareSample | None) -> dict[int, float]:
    """Estimate per-process CPU package power (watts).

    ``processes`` is a list of :class:`ProcRow` (each has pid, name,
    cpu_percent). Returns a dict mapping pid -> round(watts, 2). The first call
    seeds prev-state and returns zeros; subsequent calls return attribution
    based on deltas. Never raises (returns {} on any failure). If
    ``hardware`` is None, returns {}.
    """
    global _prev_cpu_times, _prev_ts
    try:
        if hardware is None:
            return {}

        now = time.time()
        current_times: dict[int, float] = {}
        for row in processes:
            pid = row.pid
            ct = _pid_cpu_time(pid)
            if ct is not None:
                current_times[pid] = ct

        elapsed = now - _prev_ts
        if elapsed <= 0.0:
            # First call or clock anomaly: seed state and return zeros.
            _prev_cpu_times = current_times
            _prev_ts = now
            return {pid: 0.0 for pid in current_times}

        deltas: dict[int, float] = {}
        total_delta = 0.0
        for pid, ct in current_times.items():
            prev = _prev_cpu_times.get(pid, ct)  # new pid -> delta 0
            d = ct - prev
            if d < 0.0:
                d = 0.0
            deltas[pid] = d
            total_delta += d

        package_w = cpu_package_watts(hardware)
        out: dict[int, float] = {}
        if total_delta > 0.0:
            for pid, d in deltas.items():
                share = d / total_delta
                out[pid] = round(package_w * share, 2)
        else:
            for pid in current_times:
                out[pid] = 0.0

        _prev_cpu_times = current_times
        _prev_ts = now
        return out
    except Exception:
        return {}
