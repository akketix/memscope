"""Phase-2 console runner: prints RAM + Memory Compression + GPU VRAM + top
processes (with per-process VRAM) every second so we can validate the numbers
against Task Manager before building any UI.

Run:  python -m memscope.console
or:   python memscope/console.py
"""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import TYPE_CHECKING

from .core import pressure as pressure_mod
from .core import procs as procs_mod
from .core import ram as ram_mod
from .core import vram as vram_mod
from .core.sample import Sample

if TYPE_CHECKING:
    # Type-only: avoids a hard runtime import of the optional telemetry layer.
    from .core.telemetry import HardwareSample


def _fmt_bytes(b: float) -> str:
    gb = b / (1024**3)
    if gb >= 1.0:
        return f"{gb:6.2f} GB"
    return f"{b / (1024**2):6.1f} MB"


def take_sample() -> Sample:
    ram = ram_mod.sample_ram()
    procs = procs_mod.sample_processes()
    idx, tier = pressure_mod.pressure_index(ram)
    # Fill per-process VRAM from the GPU process counter, joined by pid.
    pvram = vram_mod.process_vram_bytes()
    for row in procs:
        row.vram_bytes = pvram.get(row.pid, 0)
    sample = Sample(
        ts=time.time(),
        ram=ram,
        procs=procs,
        gpus=vram_mod.sample_gpus(),
        pressure_index=idx,
        pressure_tier=tier,
    )
    # Optionally attach hardware telemetry (temps/power/EXPO/disks).
    # Only sampled when available (slow / needs elevation); a telemetry
    # failure must never break the sampler.
    try:
        from .core.telemetry import is_hardware_available, sample_hardware

        if is_hardware_available():
            sample.hardware = sample_hardware()
    except Exception:
        pass
    # Optionally attach network connections + interface stats (phase 3).
    # Never break the sampler on a ports/psutil failure.
    try:
        from .core import ports as ports_mod

        sample.connections = ports_mod.sample_connections()
        sample.interfaces = ports_mod.interface_stats()
    except Exception:
        pass
    # Optionally attach per-process CPU package power attribution (phase 3).
    try:
        from .core import power_attribution as pa_mod

        sample.per_proc_power = pa_mod.attributed(sample.procs, sample.hardware)
    except Exception:
        pass
    return sample


def render(sample: Sample, top_n: int = 10, with_hardware: bool = False) -> str:
    r = sample.ram
    lines: list[str] = []
    lines.append(
        f"RAM  {_fmt_bytes(r.used_bytes)} / {_fmt_bytes(r.total_bytes)} "
        f"({r.percent:.1f}%)   avail {_fmt_bytes(r.available_bytes)}"
    )
    lines.append(
        f"COMP {r.compressed_mb:7.1f} MB   "
        f"pressure {sample.pressure_index:5.1f} [{sample.pressure_tier}]"
    )
    if r.swap_total_bytes > 0:
        lines.append(
            f"PAGE {r.swap_percent:5.1f}%  "
            f"({_fmt_bytes(r.swap_used_bytes)} / "
            f"{_fmt_bytes(r.swap_total_bytes)})"
        )
    lines.append("")
    lines.append("GPU(s) -- VRAM (DXGI total + live usage):")
    for g in sample.gpus:
        used = g.dedicated_used_bytes / 1024**3
        lines.append(
            f"  {g.vendor:7} {g.name[:34]:<34} "
            f"{used:5.2f} / {g.total_gb:5.2f} GB ({g.percent:4.1f}%)"
        )
    if sample.gpus:
        lines.append("")
    lines.append("Top RAM processes (by private committed):")
    header = (
        "  "
        + "NAME".ljust(22)
        + "RSS".rjust(11)
        + "PRIVATE".rjust(12)
        + "VRAM".rjust(9)
        + "CPU".rjust(7)
    )
    lines.append(header)
    for row in sample.procs[:top_n]:
        lines.append(
            f"  {row.name[:22]:<22}{_fmt_bytes(row.rss_bytes):>11}"
            f"{_fmt_bytes(row.private_bytes):>12}"
            f"{_fmt_bytes(row.vram_bytes):>9}{row.cpu_percent:>6.1f}%"
        )
    lines.append("")
    if with_hardware and sample.hardware is not None:
        lines.extend(_render_hardware(sample.hardware))
    return "\n".join(lines)


def _render_hardware(hw: "HardwareSample") -> list[str]:
    """Compact hardware block: CPU, GPUs, memory EXPO, disk count."""
    out: list[str] = ["HARDWARE:"]
    cpu = hw.cpu
    out.append("  CPU " + (cpu.name or "?") + " [" + (cpu.vendor_label or "?") + "]")
    for g in hw.gpus:
        temp = "?" if g.core_temp_c is None else "{:.0f}C".format(g.core_temp_c)
        pwr = "?" if g.power_w is None else "{:.0f}W".format(g.power_w)
        fan = "?" if g.fan_rpm is None else "{}RPM".format(int(g.fan_rpm))
        out.append("  GPU " + (g.name or "?") + "  core " + temp + "  " + pwr + "  fan " + fan)
    mem = hw.memory
    if mem.expo_enabled is True:
        expo = "ON"
    elif mem.expo_enabled is False:
        expo = "OFF"
    else:
        expo = "?"
    out.append("  MEM " + (mem.expo_label or "EXPO") + " " + expo + "  " + (mem.reason or ""))
    out.append("  DISKS " + str(len(hw.disks)))
    out.append("")
    return out


def main(interval: float = 1.0) -> int:
    # Stop on Ctrl+C cleanly.
    def _sigint(_s, _f):
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    print("MemScope phase-2 console -- Ctrl+C to stop\n" + "=" * 60)
    while True:
        sample = take_sample()
        # Clear screen on Windows; fall back to separator on others.
        os.system("cls" if os.name == "nt" else "clear")
        print("=" * 60)
        print(render(sample))
        print("=" * 60)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
