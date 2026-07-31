"""Configuration foundation for MemScope.

Persists a dataclass-based config to %APPDATA%/MemScope/config.json,
falling back to a local file (memscope/.config.json) when APPDATA is
unavailable. Provides load() and save() helpers plus the Config,
AlertThreshold and WorkloadDef dataclasses other components depend on.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "AlertThreshold",
    "WorkloadDef",
    "Config",
    "default_alerts",
    "default_workloads",
    "default_config",
    "config_path",
    "load",
    "save",
]

# Valid metric identifiers for AlertThreshold.metric.
_ALERT_METRICS = ("compressed_mb", "pressure_index", "pressure_tier", "vram_percent")

# Valid free_action identifiers for WorkloadDef.free_action.
_FREE_ACTIONS = ("comfyui_free", "llama_clear", None)


@dataclass
class AlertThreshold:
    """A single alert rule evaluated against sampled metrics."""

    metric: str
    threshold: float
    tier: str | None = None
    duration_s: float = 60.0
    cooldown_s: float = 300.0
    label: str = ""

    def __post_init__(self) -> None:
        if self.metric not in _ALERT_METRICS:
            raise ValueError(
                f"AlertThreshold.metric must be one of {_ALERT_METRICS!r}, got {self.metric!r}"
            )


@dataclass
class WorkloadDef:
    """A recognized workload process MemScope can track and unload."""

    name: str
    match_name: str
    match_cmd: str | None = None
    idle_timeout_s: float = 600.0
    auto_unload: bool = False
    free_action: str | None = None
    free_url: str | None = None

    def __post_init__(self) -> None:
        if self.free_action not in _FREE_ACTIONS:
            raise ValueError(
                f"WorkloadDef.free_action must be one of {_FREE_ACTIONS!r}, "
                f"got {self.free_action!r}"
            )


def default_alerts() -> list[AlertThreshold]:
    """Return a fresh copy of the default alert thresholds."""
    return [
        AlertThreshold(
            "pressure_tier",
            0.0,
            tier="HIGH",
            duration_s=60.0,
            cooldown_s=300.0,
            label="Pressure HIGH",
        ),
        AlertThreshold(
            "compressed_mb",
            15000.0,
            duration_s=60.0,
            cooldown_s=300.0,
            label="Compressed >15GB",
        ),
    ]


def default_workloads() -> list[WorkloadDef]:
    """Return a fresh copy of the default workload definitions."""
    return [
        WorkloadDef(
            "ComfyUI",
            "python.exe",
            match_cmd="main.py",
            free_action="comfyui_free",
            free_url="http://127.0.0.1:8000/free",
        ),
        WorkloadDef(
            "llama-server",
            "llama-server.exe",
            free_action="llama_clear",
            free_url="http://127.0.0.1:8080/clear",
        ),
    ]


@dataclass
class Config:
    """Top-level MemScope configuration."""

    interval: float = 1.0
    autostart: bool = False
    overlay_enabled: bool = True
    overlay_opacity: float = 0.85
    overlay_corner: str = "BR"
    alerts: list[AlertThreshold] = field(default_factory=default_alerts)
    workloads: list[WorkloadDef] = field(default_factory=default_workloads)
    watchdog_enabled: bool = False
    # Phase 9 polish: appearance + login startup.
    theme: str = "dark"
    accent: str = "#3a7d3a"
    start_with_windows: bool = False


def default_config() -> Config:
    """Return a Config populated with factory defaults."""
    return Config()


def _appdata_dir() -> Path | None:
    """Return the MemScope config dir under APPDATA, or None if unavailable."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "MemScope"


def _fallback_dir() -> Path:
    """Return the local fallback config dir inside the memscope package."""
    return Path(__file__).resolve().parent


def config_path() -> Path:
    """Return the resolved config file path (APPDATA preferred, fallback local)."""
    appdata_dir = _appdata_dir()
    if appdata_dir is not None:
        return appdata_dir / "config.json"
    return _fallback_dir() / ".config.json"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _coerce_config(raw: Any) -> Config:
    """Coerce a parsed JSON dict into a validated Config, applying defaults."""
    if not isinstance(raw, dict):
        return default_config()

    cfg = Config()
    # Scalar fields: keep defaults when absent.
    for key in (
        "interval",
        "autostart",
        "overlay_enabled",
        "overlay_opacity",
        "overlay_corner",
        "watchdog_enabled",
        "theme",
        "accent",
        "start_with_windows",
    ):
        if key in raw:
            setattr(cfg, key, raw[key])

    # Nested collections: rebuild through the dataclass constructors so
    # __post_init__ validation still runs.
    raw_alerts = raw.get("alerts")
    if isinstance(raw_alerts, list):
        cfg.alerts = []
        for item in raw_alerts:
            if not isinstance(item, dict):
                continue
            metric = item.get("metric")
            if metric is None or metric not in _ALERT_METRICS:
                continue
            cfg.alerts.append(
                AlertThreshold(
                    metric,
                    float(item.get("threshold", 0.0)),
                    tier=item.get("tier"),
                    duration_s=float(item.get("duration_s", 60.0)),
                    cooldown_s=float(item.get("cooldown_s", 300.0)),
                    label=item.get("label", ""),
                )
            )

    raw_workloads = raw.get("workloads")
    if isinstance(raw_workloads, list):
        cfg.workloads = []
        for item in raw_workloads:
            if not isinstance(item, dict):
                continue
            free_action = item.get("free_action")
            if free_action not in _FREE_ACTIONS:
                continue
            cfg.workloads.append(
                WorkloadDef(
                    item.get("name", ""),
                    item.get("match_name", ""),
                    match_cmd=item.get("match_cmd"),
                    idle_timeout_s=float(item.get("idle_timeout_s", 600.0)),
                    auto_unload=bool(item.get("auto_unload", False)),
                    free_action=free_action,
                    free_url=item.get("free_url"),
                )
            )

    return cfg


def load() -> Config:
    """Load config from disk, writing/returning defaults when missing or invalid."""
    path = config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        cfg = default_config()
        # Persisting defaults is best-effort; never block startup on it.
        with contextlib.suppress(Exception):
            save(cfg)
        return cfg

    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        cfg = default_config()
        with contextlib.suppress(Exception):
            save(cfg)
        return cfg

    return _coerce_config(raw)


def save(cfg: Config) -> None:
    """Atomically persist cfg to the resolved config path."""
    path = config_path()
    _ensure_parent(path)
    payload = json.dumps(asdict(cfg), indent=2)
    # Atomic write: write a temp file in the same directory then replace.
    fd, tmp_name = tempfile.mkstemp(
        prefix=".config.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            if not payload.endswith("\n"):
                fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(Exception):
            tmp_path.unlink(missing_ok=True)
        raise
