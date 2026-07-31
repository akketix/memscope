"""Windows performance-counter reader via pywin32 (win32pdh).

Phase 1 only needs the Memory Compression working set (the pressure signal).
Phase 2 adds the GPU adapter / process / engine counters here so all counter
plumbing lives in one place.
"""

from __future__ import annotations

import re

import win32pdh  # type: ignore

# Format constants (from pdh.h). PDH_FMT_DOUBLE = a floating-point value.
_FMT_DOUBLE = 0x00000200


# --- wildcard (multi-instance) counter helper -------------------------------


def _read_wildcard_counter(path: str) -> dict[str, int]:
    """Read a wildcard (multi-instance) counter, return {instance: int value}.

    Vendor-agnostic: the same Windows GPU counters work for AMD, NVIDIA, and
    Intel.
    """
    try:
        query = win32pdh.OpenQuery()
        try:
            counter = win32pdh.AddCounter(query, path)
            try:
                win32pdh.CollectQueryData(query)
                data = win32pdh.GetFormattedCounterArray(counter, _FMT_DOUBLE)
                return {str(k): int(v) for k, v in data.items()}
            finally:
                win32pdh.RemoveCounter(counter)
        finally:
            win32pdh.CloseQuery(query)
    except Exception:
        return {}


def _resolve_memory_compression_instance() -> str | None:
    """Find the Process-object instance name for Memory Compression.

    Modern Windows exposes it as 'Memory Compression' (possibly suffixed with
    a pid, e.g. 'Memory Compression#4000'). Enumerate Process instances and
    pick the one whose name starts with 'Memory Compression'.
    """
    try:
        # EnumObjectItems(machine, object, parent, instance, detail, flags)
        # Returns (counter_list, instance_list).
        result = win32pdh.EnumObjectItems(
            None, None, "Process", win32pdh.PERF_DETAIL_WIZARD
        )
        instances = result[1] if isinstance(result, tuple) else []
    except Exception:
        return None

    for inst in instances:
        if inst.startswith("Memory Compression"):
            return inst
    return None


def memory_compression_working_set_bytes() -> int:
    """Return the Memory Compression process working set in bytes, else 0.

    This is the compressed-page pool Windows grows under RAM pressure — the
    core pressure signal MemScope surfaces that no stock tool highlights.
    """
    instance = _resolve_memory_compression_instance()
    if instance is None:
        return 0

    counter_path = rf"\Process({instance})\Working Set"
    try:
        query = win32pdh.OpenQuery()
        try:
            counter = win32pdh.AddCounter(query, counter_path)
            try:
                win32pdh.CollectQueryData(query)
                _status, value = win32pdh.GetFormattedCounterValue(counter, _FMT_DOUBLE)
                return int(value)
            finally:
                win32pdh.RemoveCounter(counter)
        finally:
            win32pdh.CloseQuery(query)
    except Exception:
        return 0


# --- GPU counters (vendor-agnostic: AMD / NVIDIA / Intel) ------------------

# Instance names look like:
#   adapter:  luid_0x00000000_0x1655A17B_phys_0   (hex may be upper or lower)
#   process: pid_24832_luid_0x00000000_0x1655A17B_phys_0
_ADAPTER_RE = re.compile(r"^(luid_0x[0-9a-fA-F]{8}_0x[0-9a-fA-F]{8})(?:_phys_\d+)?$")
_PROC_RE = re.compile(
    r"^pid_(\d+)_luid_0x[0-9a-fA-F]{8}_0x[0-9a-fA-F]{8}(?:_phys_\d+)?$"
)


def enumerate_gpu_adapter_usage() -> dict[str, dict[str, int]]:
    """Return {luid_key (lowercased): {"dedicated": bytes, "shared": bytes}}.

    The luid_key strips the trailing `_phys_N` and is lowercased so it can be
    joined directly against dxgi.enumerate_adapters().
    """
    out: dict[str, dict[str, int]] = {}
    for kind, path in (
        ("dedicated", r"\GPU Adapter Memory(*)\Dedicated Usage"),
        ("shared", r"\GPU Adapter Memory(*)\Shared Usage"),
    ):
        for instance, value in _read_wildcard_counter(path).items():
            m = _ADAPTER_RE.match(instance)
            if not m:
                continue
            key = m.group(1).lower()
            out.setdefault(key, {"dedicated": 0, "shared": 0})[kind] = value
    return out


def enumerate_gpu_process_usage() -> dict[int, int]:
    """Return {pid: vram_bytes} summed across all adapters.

    A process appears once per GPU adapter; we sum so a multi-GPU process's
    total VRAM is correct.
    """
    out: dict[int, int] = {}
    for instance, value in _read_wildcard_counter(
        r"\GPU Process Memory(*)\Local Usage"
    ).items():
        m = _PROC_RE.match(instance)
        if not m:
            continue
        pid = int(m.group(1))
        out[pid] = out.get(pid, 0) + value
    return out
