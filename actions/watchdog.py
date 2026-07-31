"""Named-workload guard: detect running apps, track idle time, and provide
best-effort Unload / Free-VRAM / Restart actions plus an opt-in auto-unload
rule.

Detection is driven by the WorkloadDef list in Config: a process matches when
its name contains ``match_name`` and, when ``match_cmd`` is set, its command
line contains that token. Free/Restart are best-effort: a missing URL,
connection refused, or an unknown process never raises.
"""

from __future__ import annotations

import contextlib
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil
from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..config import Config, WorkloadDef
    from ..core.sample import Sample

__all__ = ["WorkloadStatus", "WorkloadGuard"]

# Cooldown between automatic unload triggers for the same workload.
_AUTO_UNLOAD_COOLDOWN_S = 300.0
# HTTP timeout for best-effort free calls (ComfyUI /free, llama /clear).
_FREE_TIMEOUT_S = 5.0


@dataclass
class WorkloadStatus:
    """Snapshot of one tracked workload as seen by the guard."""

    name: str
    running: bool
    pid: int = 0
    rss_bytes: int = 0
    vram_bytes: int = 0
    idle_s: float = 0.0
    match_name: str = ""
    match_cmd: str | None = None


class WorkloadGuard(QObject):
    """Track named workloads and act on them when pressure rises.

    All public methods are safe to call on the main thread (the sampler emits
    each Sample there). Detection/Free/Restart never raise on failure: problems
    are reported via :attr:`action_failed` instead.
    """

    unloaded = Signal(str)  # workload name
    action_failed = Signal(str, str)  # workload name, error

    def __init__(
        self,
        config: Config,
        on_alert: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._on_alert = on_alert
        # name -> last matched pid (used by restart()).
        self._pids: dict[str, int] = {}
        # name -> epoch of last successful free (auto-unload cooldown).
        self._last_unload: dict[str, float] = {}

    # -- detection -----------------------------------------------------------

    def _find_def(self, name: str) -> WorkloadDef | None:
        for w in self._config.workloads:
            if w.name == name:
                return w
        return None

    @staticmethod
    def _cmdline(proc: psutil.Process) -> list[str]:
        try:
            return proc.cmdline()
        except Exception:
            return []

    def _match_process(self, w: WorkloadDef) -> psutil.Process | None:
        needle = w.match_name.lower()
        for proc in psutil.process_iter(["pid", "name"]):
            pname = ""
            try:
                info = proc.info
                pname = info.get("name") or ""
            except Exception:
                continue
            if needle not in pname.lower():
                continue
            if w.match_cmd:
                cmd = " ".join(self._cmdline(proc)).lower()
                if w.match_cmd.lower() not in cmd:
                    continue
            return proc
        return None

    # -- main entry ---------------------------------------------------------

    def update(self, sample: Sample) -> list[WorkloadStatus]:
        statuses: list[WorkloadStatus] = []
        now = time.time()
        for w in self._config.workloads:
            proc = self._match_process(w)
            if proc is None:
                self._pids.pop(w.name, None)
                statuses.append(
                    WorkloadStatus(
                        name=w.name,
                        running=False,
                        match_name=w.match_name,
                        match_cmd=w.match_cmd,
                    )
                )
                continue
            try:
                pid = proc.pid
                create_time = proc.create_time()
                rss = int(proc.memory_info().rss)
            except Exception:
                self._pids.pop(w.name, None)
                statuses.append(
                    WorkloadStatus(
                        name=w.name,
                        running=False,
                        match_name=w.match_name,
                        match_cmd=w.match_cmd,
                    )
                )
                continue
            self._pids[w.name] = pid
            # Per-process VRAM is sourced from the sampler's join (GPU counter
            # by pid) so the guard does not duplicate DXGI work.
            vram = 0
            for row in sample.procs:
                if row.pid == pid:
                    vram = row.vram_bytes
                    break
            # Rough idle proxy: time since the process was started. A real
            # CPU-delta tracker could refine this later.
            idle_s = max(0.0, now - create_time)
            statuses.append(
                WorkloadStatus(
                    name=w.name,
                    running=True,
                    pid=pid,
                    rss_bytes=rss,
                    vram_bytes=vram,
                    idle_s=idle_s,
                    match_name=w.match_name,
                    match_cmd=w.match_cmd,
                )
            )
            self._maybe_auto_unload(w, sample.pressure_tier, idle_s, now)
        return statuses

    def _maybe_auto_unload(
        self,
        w: WorkloadDef,
        tier: str,
        idle_s: float,
        now: float,
    ) -> None:
        if not w.auto_unload:
            return
        if tier not in ("HIGH", "CRITICAL"):
            return
        if idle_s < w.idle_timeout_s:
            return
        if now - self._last_unload.get(w.name, 0.0) < _AUTO_UNLOAD_COOLDOWN_S:
            return
        if not self.free(w.name):
            return
        self._last_unload[w.name] = now
        if self._on_alert is not None:
            with contextlib.suppress(Exception):
                # Alerting is best-effort; never let a callback failure escape.
                self._on_alert(
                    "Workload auto-unloaded",
                    w.name + " freed to relieve memory pressure.",
                )

    # -- actions ------------------------------------------------------------

    def free(self, name: str) -> bool:
        """Best-effort free-VRAM call (ComfyUI /free or llama /clear).

        Returns True on success, False on any failure (emits action_failed).
        """
        w = self._find_def(name)
        if w is None:
            self.action_failed.emit(name, "unknown workload")
            return False
        url = w.free_url
        if not url:
            self.action_failed.emit(name, "no free_url configured")
            return False
        try:
            if w.free_action == "comfyui_free":
                body = json.dumps({"unload_models": True}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
            else:  # llama_clear
                req = urllib.request.Request(url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=_FREE_TIMEOUT_S) as resp:
                resp.read()
        except Exception as exc:
            self.action_failed.emit(name, "free failed: " + str(exc))
            return False
        self.unloaded.emit(name)
        return True

    def restart(self, name: str) -> bool:
        """Terminate the matching process. Does NOT relaunch in v1.

        Returns True if the process was terminated, False on failure.
        """
        # NOTE: relaunching a fresh process is a future feature; v1 only stops.
        w = self._find_def(name)
        if w is None:
            self.action_failed.emit(name, "unknown workload")
            return False
        proc = self._match_process(w)
        if proc is None:
            self.action_failed.emit(name, "process not running")
            return False
        try:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except Exception:
                proc.kill()
        except Exception as exc:
            self.action_failed.emit(name, "restart failed: " + str(exc))
            return False
        self._pids.pop(name, None)
        return True

    def unload(self, name: str) -> bool:
        """Best-effort unload: free() for HTTP workloads, restart() otherwise."""
        w = self._find_def(name)
        if w is None:
            self.action_failed.emit(name, "unknown workload")
            return False
        if w.free_action is not None:
            return self.free(name)
        return self.restart(name)
