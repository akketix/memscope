"""FastAPI app + background sampler thread for MemScope telemetry.

The app caches a combined state (a :class:`memscope.core.sample.Sample` plus a
:class:`memscope.core.telemetry.HardwareSample`) refreshed every
``DEFAULT_INTERVAL_S`` seconds by a daemon thread. Endpoints return JSON
serialized via :func:`dataclasses.asdict`; ``GET /metrics`` returns Prometheus
exposition text. ``app`` is a module-level instance so uvicorn can target
``memscope.api.server:app`` directly.

Run::

    uvicorn memscope.api.server:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any

import psutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from memscope import __version__
from memscope.actions.watchdog import WorkloadGuard, WorkloadStatus
from memscope.config import load as load_config
from memscope.console import take_sample
from memscope.core import ports as ports_mod
from memscope.core import power_attribution as pa_mod
from memscope.core.sample import Sample
from memscope.core.telemetry import HardwareSample, sample_hardware

__all__ = [
    "DEFAULT_INTERVAL_S",
    "build_app",
    "app",
    "start_sampler",
    "stop_sampler",
    "get_state",
]

# --- background sampler -----------------------------------------------------

DEFAULT_INTERVAL_S = 2.0

_lock = threading.Lock()
_sample: Sample | None = None
_hardware: HardwareSample | None = None
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _tick() -> None:
    """Take one combined sample and store it under the lock."""
    global _sample, _hardware
    try:
        sample = take_sample()
    except Exception:
        sample = Sample(ts=time.time())
    try:
        hardware = sample_hardware()
    except Exception:
        hardware = HardwareSample()
    with _lock:
        _sample = sample
        _hardware = hardware


def _sampler_loop(interval: float) -> None:
    assert _stop_event is not None
    while not _stop_event.wait(interval):
        _tick()


def _ensure_sample() -> tuple[Sample, HardwareSample]:
    """Return cached sample/hardware, ticking once if none exists yet."""
    global _sample, _hardware
    with _lock:
        cached_sample = _sample
        cached_hardware = _hardware
    if cached_sample is None or cached_hardware is None:
        _tick()
        with _lock:
            cached_sample = _sample
            cached_hardware = _hardware
    # At this point both are populated (a tick always sets both).
    assert cached_sample is not None and cached_hardware is not None
    return cached_sample, cached_hardware


def start_sampler(interval: float = DEFAULT_INTERVAL_S) -> None:
    """Start the background sampler thread (idempotent)."""
    global _thread, _stop_event
    if _thread is not None and _thread.is_alive():
        return
    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_sampler_loop,
        args=(interval,),
        name="memscope-sampler",
        daemon=True,
    )
    _thread.start()


def stop_sampler() -> None:
    """Signal the sampler thread to stop (idempotent)."""
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5.0)
    _thread = None
    _stop_event = None


def get_state() -> dict[str, Any]:
    """Return the combined state dict used by ``GET /state``."""
    sample, hardware = _ensure_sample()
    top = sorted(
        sample.procs,
        key=lambda p: p.private_bytes,
        reverse=True,
    )[:50]
    return {
        "ts": sample.ts,
        "ram": asdict(sample.ram),
        "pressure": {"index": sample.pressure_index, "tier": sample.pressure_tier},
        "gpus": [asdict(g) for g in sample.gpus],
        "processes": [asdict(p) for p in top],
        "hardware": asdict(hardware),
    }


# --- request/response models -------------------------------------------------


class KillRequest(BaseModel):
    pid: int


class WorkloadFreeRequest(BaseModel):
    name: str


# --- prometheus exposition --------------------------------------------------


def _prom_line(name: str, value: float | int, labels: str | None = None) -> str:
    if labels:
        return name + "{" + labels + "} " + str(value)
    return name + " " + str(value)


def build_metrics(sample: Sample, hardware: HardwareSample) -> str:
    """Build Prometheus exposition text for the given samples."""
    lines: list[str] = []
    r = sample.ram
    lines.append("# HELP memscope_ram_used_bytes RAM currently in use (bytes).")
    lines.append("# TYPE memscope_ram_used_bytes gauge")
    lines.append(_prom_line("memscope_ram_used_bytes", r.used_bytes))
    lines.append("# HELP memscope_ram_total_bytes Total physical RAM (bytes).")
    lines.append("# TYPE memscope_ram_total_bytes gauge")
    lines.append(_prom_line("memscope_ram_total_bytes", r.total_bytes))
    lines.append("# HELP memscope_compressed_bytes Memory Compression working set (bytes).")
    lines.append("# TYPE memscope_compressed_bytes gauge")
    lines.append(_prom_line("memscope_compressed_bytes", r.compressed_working_set_bytes))
    lines.append("# HELP memscope_pressure_index Derived memory pressure index.")
    lines.append("# TYPE memscope_pressure_index gauge")
    lines.append(_prom_line("memscope_pressure_index", sample.pressure_index))

    lines.append("# HELP memscope_gpu_used_bytes GPU dedicated VRAM in use (bytes).")
    lines.append("# TYPE memscope_gpu_used_bytes gauge")
    lines.append("# HELP memscope_gpu_power_watts GPU board power draw (watts).")
    lines.append("# TYPE memscope_gpu_power_watts gauge")
    lines.append("# HELP memscope_gpu_temp_celsius GPU core temperature (Celsius).")
    lines.append("# TYPE memscope_gpu_temp_celsius gauge")
    for g in sample.gpus:
        luid = g.luid_key or "gpu"
        labels = "luid=" + _prom_label_value(luid)
        lines.append(_prom_line("memscope_gpu_used_bytes", g.dedicated_used_bytes, labels))
    # Hardware telemetry carries richer per-GPU thermal/power data, joined by
    # name when available.
    for gt in hardware.gpus:
        labels = "name=" + _prom_label_value(gt.name)
        if gt.power_w is not None:
            lines.append(_prom_line("memscope_gpu_power_watts", gt.power_w, labels))
        if gt.core_temp_c is not None:
            lines.append(_prom_line("memscope_gpu_temp_celsius", gt.core_temp_c, labels))

    lines.append("# HELP memscope_cpu_temp_celsius CPU temperature (Celsius).")
    lines.append("# TYPE memscope_cpu_temp_celsius gauge")
    lines.append("# HELP memscope_cpu_power_watts CPU package power (watts).")
    lines.append("# TYPE memscope_cpu_power_watts gauge")
    for sr in hardware.cpu.temps:
        labels = "sensor=" + _prom_label_value(sr.name)
        lines.append(_prom_line("memscope_cpu_temp_celsius", sr.value, labels))
    for sr in hardware.cpu.powers:
        labels = "sensor=" + _prom_label_value(sr.name)
        lines.append(_prom_line("memscope_cpu_power_watts", sr.value, labels))

    lines.append("")
    return "\n".join(lines)


def _prom_label_value(value: str) -> str:
    """Quote a label value for Prometheus text exposition."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + escaped + '"'


# --- app builder ------------------------------------------------------------


def build_app() -> FastAPI:
    """Build and return the FastAPI application with all routes wired."""
    application = FastAPI(
        title="MemScope Telemetry API",
        version=__version__,
        summary="Local RAM/VRAM pressure and hardware telemetry API for MemScope.",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://127.0.0.1",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.on_event("startup")
    def _on_startup() -> None:
        start_sampler()

    @application.get("/healthz")
    def healthz() -> dict[str, Any]:
        sample, hardware = _ensure_sample()
        return {"ok": True, "source": hardware.source}

    @application.get("/state")
    def state() -> dict[str, Any]:
        return get_state()

    @application.get("/hardware")
    def hardware() -> dict[str, Any]:
        _s, hw = _ensure_sample()
        return asdict(hw)

    @application.get("/processes")
    def processes(limit: int = 50) -> list[dict[str, Any]]:
        sample, _hw = _ensure_sample()
        if limit < 1:
            limit = 1
        if limit > 500:
            limit = 500
        top = sorted(
            sample.procs,
            key=lambda p: p.private_bytes,
            reverse=True,
        )[:limit]
        return [asdict(p) for p in top]

    @application.get("/gpus")
    def gpus() -> list[dict[str, Any]]:
        sample, hw = _ensure_sample()
        adapters = [asdict(g) for g in sample.gpus]
        # Attach matching telemetry (by name) so callers get temps/power/fan.
        telemetry_by_name = {gt.name: asdict(gt) for gt in hw.gpus}
        for adapter in adapters:
            name = adapter.get("name", "")
            adapter["telemetry"] = telemetry_by_name.get(name, {})
        return adapters

    @application.get("/ports")
    def ports() -> dict[str, Any]:
        """Listening + all connections + per-NIC interface stats."""
        sample, _hw = _ensure_sample()
        try:
            listening = [asdict(c) for c in ports_mod.listening_ports()]
        except Exception:
            listening = []
        try:
            all_conns = [asdict(c) for c in ports_mod.sample_connections()]
        except Exception:
            all_conns = []
        try:
            interfaces = [asdict(n) for n in ports_mod.interface_stats()]
        except Exception:
            interfaces = []
        return {
            "listening": listening,
            "all": all_conns,
            "interfaces": interfaces,
        }

    @application.get("/power")
    def power() -> dict[str, Any]:
        """CPU package watts + per-process power attribution."""
        sample, hw = _ensure_sample()
        try:
            cpu_pkg = pa_mod.cpu_package_watts(hw)
        except Exception:
            cpu_pkg = 0.0
        try:
            per_proc = pa_mod.attributed(sample.procs, hw)
        except Exception:
            per_proc = {}
        return {
            "cpu_package_watts": cpu_pkg,
            "per_process": {int(k): float(v) for k, v in per_proc.items()},
        }

    @application.get(
        "/metrics",
        response_class=PlainTextResponse,
    )
    def metrics() -> PlainTextResponse:
        sample, hw = _ensure_sample()
        return PlainTextResponse(
            content=build_metrics(sample, hw),
            media_type="text/plain; version=0.0.4",
        )

    @application.post("/actions/kill")
    def kill(req: KillRequest) -> dict[str, Any]:
        pid = req.pid
        killed = False
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
                killed = True
            except Exception:
                if proc.is_running():
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
                killed = True
        except psutil.NoSuchProcess:
            # Already gone: treat as success.
            killed = True
        except Exception:
            killed = False
        return {"ok": killed, "pid": pid, "killed": killed}

    @application.post("/actions/workload/free")
    def workload_free(req: WorkloadFreeRequest) -> dict[str, Any]:
        cfg = load_config()
        # WorkloadGuard inherits QObject; constructed here without a Qt event
        # loop so it can run in any thread. Free is best-effort and never
        # raises.
        guard = WorkloadGuard(cfg)
        ok = guard.free(req.name)
        return {"ok": ok, "name": req.name}

    @application.get("/actions/workload/list")
    def workload_list() -> list[dict[str, Any]]:
        cfg = load_config()
        guard = WorkloadGuard(cfg)
        sample, _hw = _ensure_sample()
        statuses: list[WorkloadStatus] = guard.update(sample)
        return [asdict(s) for s in statuses]

    return application


app = build_app()
