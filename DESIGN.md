# MemScope — RAM / VRAM Pressure Monitor (Windows EXE)

A polished, single-EXE Windows utility that shows live RAM + VRAM usage,
the Windows "Memory Compression" pressure signal, per-process breakdowns,
historical time-series, alerts, a tray icon, an always-on-top mini overlay,
and a watchdog that can keep ComfyUI / llama-server alive.

## Why it exists

Windows "Memory Compression" working set is a *pressure symptom* — there is no
stock tool that surfaces it next to VRAM and per-process hogs in one place.
MemScope makes pressure visible and actionable.

---

## Tech stack

- **UI:** PySide6 (Qt6) + `pyqtgraph` for live time-series plots.
- **System data:** `psutil` (RAM, per-process), `pywin32` pdh wrappers for
  Windows performance counters (GPU adapter/process memory, Memory Compression
  working set, GPU engine utilization), `ctypes` DXGI adapter desc for the
  *true* total VRAM (works around the 4 GB `AdapterRAM` 32-bit bug on AMD cards).
- **Packaging:** PyInstaller `--onefile` (or `--onedir` for faster cold start).
- **Python:** 3.11+ (you already have 3.12 via uv).

## Data sources (all verified against the manual analysis we just ran)

| Signal | Source | Notes |
|---|---|---|
| RAM total/used/free/percent | `psutil.virtual_memory()` | reliable |
| Pagefile in/out | `psutil.swap_memory()` | |
| Per-process RAM (rss/vms/private) | `psutil.process_iter()` | |
| **Memory Compression working set** | perf counter `\Process(Memory Compression)\Working Set` via pywin32 pdh | the pressure signal |
| GPU dedicated/shared usage | `\GPU Adapter Memory(*)\Dedicated/Shared Usage` | per-adapter |
| Per-process VRAM | `\GPU Process Memory(*)\Local Usage` | map PID→name |
| GPU utilization | `\GPU Engine(*)\Utilization Percentage` | |
| **Total VRAM (correct, >4 GB)** | DXGI `IDXGIAdapter::GetDesc()` → `DedicatedVideoMemory` | avoids Win32_VideoController 32-bit cap |

## Pressure index (derived, our own)

`pressure = 0..100` blended from:

- compressed MB (primary),
- available MB (low = higher pressure),
- pagefile usage %,
- optional: rate-of-change of compressed MB (pressure *rising* flag).

Tiers: Idle <3GB · Light <8GB · **Moderate <15GB** · **High <22GB** · Critical ≥22GB
(mirrors the thresholds we observed on your box).

---

## UI layout (main window)

```
┌─ MemScope ──────────────────────────────────────────────────────┐
│  File  View  Tools  Help                          [_][□][X]      │
├──────────────────────────────────────────────────────────────────┤
│  ┌ RAM ──────────────┐  ┌ VRAM (AMD RX 7900 GRE 16GB) ────────┐  │
│  │ Used  34.8 / 63.6 │  │ Used  7.8 / 16.0 GB   (49%)         │  │
│  │ ▓▓▓▓▓▓▓▓░░░░░░ 55%│  │ ▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░          │  │
│  │ Compressed 10.0GB │  │ Shared 0.68 GB                      │  │
│  │ Pressure: ▓▓ LIGHT │  │ GPU util 1.9%                       │  │
│  └───────────────────┘  └─────────────────────────────────────┘  │
│                                                                  │
│  ┌ Pressure history (60 min) ─────────────────────────────────┐  │
│  │   ╱╲    ╱╲╱╲          compressed ─────  available ·····    │  │
│  │  ╱  ╲__╱    ╲___                                         │  │
│  │ ╱              \___________                               │  │
│  │  ──────────────────────────────────────────────            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Top RAM processes               Top VRAM processes             │
│  Name       RAM    Priv   [kill]  PID  Name        VRAM   [kill] │
│  ComfyUI    1.9GB  23.9GB [x]    24832 llama-srv 7.2GB  [x]     │
│  chrome×31  4.5GB           [x]   28804 dwm       304MB  [x]    │
│  node×17    2.7GB           [x]   18948 chrome     187MB  [x]    │
│  ...                                                            │
├──────────────────────────────────────────────────────────────────┤
│  ● sampling 1.0s   pressure: LIGHT   [Snapshot] [Overlay] [⚙]   │
└──────────────────────────────────────────────────────────────────┘
```

### Tray + overlay

- **Tray icon** color = pressure tier (green/amber/red). Right-click menu:
  Show/Hide · Toggle overlay · Snapshot · Kill top hog · Watchdog on/off · Quit.
- **Mini overlay** (frameless, always-on-top, ~220×64px, draggable):
  `RAM 55% · VRAM 49% · PRESSURE: LIGHT`. Configurable corner + opacity.

### Alerts

- Rules per-metric with threshold + duration (avoid flapping):
  e.g. "Compressed > 15GB for 60s" → tray balloon + optional TTS.
- Watchdog rules: keep ComfyUI (`POST :8000/free` or restart) /
  llama-server alive; kill+relaunch on crash; cooldown to avoid loops.

---

## Module layout

```
memscope/
  main.py                 # QApplication, single-instance, wiring
  config.py               # JSON in %APPDATA%/MemScope/config.json
  core/
    sample.py             # Sample dataclass (one snapshot, all metrics)
    sampler.py            # QThread poller @ interval, emits Sample
    ram.py                # psutil RAM + pagefile
    procs.py              # psutil process table
    perf_counters.py      # pywin32 pdh: GPU adapter/process, MemCompression WS
    dxgi.py               # ctypes: IDXGIFactory.EnumAdapters.GetDesc (total VRAM)
    pressure.py           # pressure index math
    history.py            # ring buffer (default 3600s) for charts
  ui/
    main_window.py
    widgets/gauge.py      # circular gauge (RAM/VRAM)
    widgets/plot.py       # pyqtgraph time-series
    widgets/proctable.py  # sortable tables with [kill] buttons
    overlay.py            # frameless always-on-top mini
    tray.py               # QSystemTrayIcon + menu
    alerts.py             # rule engine → notifications
  actions/
    process_ops.py        # kill-by-pid (elevate if needed)
    watchdog.py           # keep-alive ComfyUI + llama-server
    snapshot.py            # export JSON/CSV + PNG of charts
  assets/icon*.png
  build/memscope.spec     # PyInstaller
  tests/
```

## Build plan (phased)

1. **Core sampler + Sample model** — poll RAM/proc every 1s to console; confirm matches Task Manager. ✅ DONE (RAM + Memory Compression + top procs validated against Task Manager.)
2. **VRAM layer** — perf counters + DXGI total; confirm 16 GB and per-process VRAM. ✅ DONE (DXGI via ctypes gives true 16 GB total; win32pdh adapter/process counters give live usage; joined by LUID; validated against Task Manager. Cross-vendor: works for AMD/NVIDIA/Intel.)
3. **Main window (core monitor)** — gauges + two process tables + kill buttons. ✅ DONE (5 parallel agents: sampler thread + gauge widget + process table built in parallel, integrated into MainWindow + app.py; verified offscreen render 900x600 with 1 GPU gauge + 561 proc rows from live data.)
4. **History + plots + pressure index** — pyqtgraph 60-min series, pressure tier coloring. ✅ DONE (5-agent fan-out: HistoryBuffer ring buffer + pyqtgraph HistoryPlot + PressureHeatmap, integrated into MainWindow; verified offscreen with live history records.)
5. **Tray + overlay + alerts** — tray icon colored by tier, mini overlay, threshold rules. ✅ DONE (7-agent fan-out: config foundation + tray + mini overlay + alert engine + workload guard built in parallel, integrated into MainWindow/app; verified offscreen 1100x800 with all components live; alert path fires on HIGH.)
5.5. **Named-workload guards + auto-unload** — ✅ DONE (WorkloadGuard detects ComfyUI/llama-server by name+cmdline, tracks idle, best-effort `/free` (ComfyUI) and `/clear` (llama) via urllib, opt-in auto-unload on HIGH pressure + idle; Workloads panel with Free/Stop buttons in MainWindow.)
6. **Config + snapshot/export** — persist settings (✅ config done in 5), JSON/CSV/PNG export (snapshot stub added; full export pending).
7. **Watchdog** — keep ComfyUI + llama-server alive (restart, cooldown). ✅ partially (free/clear + terminate in WorkloadGuard; relaunch-on-crash pending.)
8. **Package EXE** — PyInstaller spec, cold-start test, optional startup-with-Windows. ✅ DONE (MemScope.spec onefile/windowed, excludes heavy Qt modules; dist/MemScope.exe = 60 MB; cold-start verified offscreen (boots, no crash); single-instance QSharedMemory cleans up across hard-kill; build_exe.py reproducible build script.)
9. **Polish** — icons, theme, about, README. ✅ DONE (5-agent fan-out: dark/light QSS theme system + About dialog + startup-with-Windows; reproducible Pillow icon generator (memscope/assets/make_icon.py -> icon.ico 16..256); icon baked into spec + bundled as data + set as window/tray icon; View menu theme toggle + Help→About + tray Start-with-Windows toggle; README.md; EXE rebuilt 59.2 MB with icon, cold-start verified.)

## Out of scope for v1

- Per-core CPU chart (keep CPU optional/minimal — focus is memory).
- Remote/network monitoring.
- Linux/macOS (Windows-only by design — perf counters + DXGI).
