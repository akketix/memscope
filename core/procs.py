"""Per-process sampler (phase 1): RAM only; VRAM filled in phase 2."""

from __future__ import annotations

import psutil

from .sample import ProcRow


def sample_processes(top_n: int = 0) -> list[ProcRow]:
    """Snapshot all processes. If `top_n` > 0, return only the N biggest by
    private committed bytes (the metric that caught ComfyUI's 24 GB).
    """
    rows: list[ProcRow] = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        info = p.info
        mi = info.get("memory_info")
        if mi is None:
            continue
        rows.append(
            ProcRow(
                pid=int(info["pid"]),
                name=str(info.get("name") or "unknown"),
                rss_bytes=int(getattr(mi, "rss", 0)),
                private_bytes=int(
                    getattr(mi, "private_bytes", 0) or getattr(mi, "vms", 0)
                ),
                cpu_percent=float(info.get("cpu_percent", 0.0) or 0.0),
            )
        )

    # Sort by private bytes desc (committed memory — the real hog metric).
    rows.sort(key=lambda r: r.private_bytes, reverse=True)
    if top_n > 0:
        rows = rows[:top_n]
    return rows
