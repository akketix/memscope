"""Top-level MemScope window: gauges, pressure readout, process table."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from memscope.actions.startup import set_startup
from memscope.actions.watchdog import WorkloadGuard
from memscope.config import Config, load as load_cfg, save as save_cfg
from memscope.core.history import HistoryBuffer
from memscope.ui.about import show_about
from memscope.ui.alerts import AlertEngine
from memscope.ui.overlay import MiniOverlay
from memscope.ui.sampler_thread import SamplerThread
from memscope.ui.theme import apply_plot_theme, apply_theme
from memscope.ui.tray import TrayController
from memscope.ui.widgets.gauge import GaugeWidget
from memscope.ui.widgets.hardwarepanel import HardwarePanel
from memscope.ui.widgets.heatmap import PressureHeatmap
from memscope.ui.widgets.plot import HistoryPlot
from memscope.ui.widgets.porttable import PortInspectorTab
from memscope.ui.widgets.proctable import ProcTable

# Repo root: memscope/ui/main_window.py -> memscope/ui -> memscope -> repo root.
_REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Tokens stripped from a DXGI adapter name to keep the gauge title short
# (e.g. "AMD Radeon RX 7900 GRE" -> "7900 GRE", titled "AMD 7900 GRE").
_VENDOR_TOKENS: set[str] = {
    "amd",
    "nvidia",
    "intel",
    "microsoft",
    "unknown",
    "radeon",
    "geforce",
    "rtx",
    "gtx",
    "rx",
    "arc",
    "direct3d",
}

_TIER_COLOR: dict[str, QColor] = {
    "IDLE": QColor(0x27, 0xAE, 0x60),
    "LIGHT": QColor(0x27, 0xAE, 0x60),
    "MODERATE": QColor(0xE6, 0x7E, 0x22),
    "HIGH": QColor(0xC0, 0x39, 0x2B),
    "CRITICAL": QColor(0xC0, 0x39, 0x2B),
}


def _short_gpu_name(name: str) -> str:
    """Strip vendor/marketing tokens and cap length for a compact gauge title."""
    parts = name.split()
    kept = [p for p in parts if p.lower() not in _VENDOR_TOKENS]
    if not kept:
        kept = parts
    short = " ".join(kept).strip()
    if len(short) > 24:
        short = short[:24].strip()
    return short or name


class MainWindow(QMainWindow):
    """Main MemScope window: a row of RAM/GPU gauges over a process table."""

    @staticmethod
    def _resource_path(rel: str) -> str:
        """Resolve a bundled resource path (PyInstaller _MEIPASS-aware)."""
        base = getattr(sys, "_MEIPASS", _REPO_ROOT)
        return os.path.join(base, rel)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MemScope")
        self.resize(900, 600)

        # Window icon (PyInstaller _MEIPASS-aware).
        self.setWindowIcon(QIcon(self._resource_path("memscope/assets/icon.ico")))

        self.ram_gauge: GaugeWidget = GaugeWidget("RAM")
        self.gpu_gauges: dict[str, GaugeWidget] = {}
        self.proc_table: ProcTable = ProcTable()
        self.pressure_label: QLabel = QLabel("Pressure: IDLE (0.0)")
        self.compress_label: QLabel = QLabel("Compressed: 0.0 MB")
        self._started: bool = False
        self._last_sample = None
        self._last_statuses: list = []
        self.history: HistoryBuffer = HistoryBuffer()
        self.plot: HistoryPlot = HistoryPlot()
        self.heatmap: PressureHeatmap = PressureHeatmap(60)

        # --- config + integration components (Phase 5) ---
        self.config: Config = load_cfg()
        self.tray: TrayController = TrayController(self)
        self.overlay: MiniOverlay = MiniOverlay(self.config)
        self.alerts: AlertEngine = AlertEngine(self.config, self)
        self.guard: WorkloadGuard = WorkloadGuard(self.config, on_alert=self.tray.notify)

        # --- Phase 9: theme application ---
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config.theme, self.config.accent)
        apply_plot_theme(self.plot, self.config.theme)

        # --- layout: three-tab central widget ---------------------------
        central = QWidget()
        self.setCentralWidget(central)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.tabs)

        # --- Tab 1: Memory & Pressure (existing widgets) ---
        mem_tab = QWidget()
        self._gauge_row = QHBoxLayout()
        self._gauge_row.setContentsMargins(8, 8, 8, 8)
        self._gauge_row.setSpacing(12)
        self._gauge_row.addWidget(self.ram_gauge)

        mem_layout = QVBoxLayout(mem_tab)
        mem_layout.setContentsMargins(8, 8, 8, 8)
        mem_layout.setSpacing(8)
        mem_layout.addLayout(self._gauge_row)

        self.pressure_label.setStyleSheet("font-weight: bold; font-size: 14pt;")
        self.compress_label.setStyleSheet("font-size: 12pt;")
        mem_layout.addWidget(self.pressure_label)
        mem_layout.addWidget(self.compress_label)
        mem_layout.addWidget(self.heatmap)
        mem_layout.addWidget(self.plot, 1)
        mem_layout.addWidget(self.proc_table, 1)

        # --- workloads panel (kept on the Memory tab) ---
        self.workloads_group = QGroupBox("Workloads")
        wl_layout = QVBoxLayout(self.workloads_group)
        wl_layout.setContentsMargins(4, 4, 4, 4)
        wl_layout.setSpacing(4)
        self.workloads_table = QTableWidget(0, 8)
        self.workloads_table.setHorizontalHeaderLabels(
            ["Name", "Running", "PID", "RAM", "VRAM", "Idle", "Free", "Stop"]
        )
        self.workloads_table.verticalHeader().setVisible(False)
        self.workloads_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.workloads_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        wl_layout.addWidget(self.workloads_table)
        mem_layout.addWidget(self.workloads_group)

        self.tabs.addTab(mem_tab, "Memory & Pressure")

        # --- Tab 2: Hardware ---
        self.hw_panel = HardwarePanel()
        self.tabs.addTab(self.hw_panel, "Hardware")

        # --- Tab 3: Network ---
        self.port_tab = PortInspectorTab()
        self.port_tab.row_killed.connect(lambda pid: self.tray.notify("Process killed", str(pid)))
        self.tabs.addTab(self.port_tab, "Network")

        # --- sampler ---
        self.sampler = SamplerThread(float(self.config.interval))
        self.sampler.sample_ready.connect(self._update)

        # --- wire integration components ---
        self.tray.showhide_requested.connect(self._toggle_visibility)
        self.tray.overlay_requested.connect(self.overlay.toggle)
        self.tray.snapshot_requested.connect(self._snapshot)
        self.tray.quit_requested.connect(self._quit)
        self.tray.about_requested.connect(lambda: show_about(self))
        self.tray.startup_toggled.connect(self._on_startup_toggled)
        self.alerts.fired.connect(self.tray.notify)
        self.guard.unloaded.connect(lambda name: self.tray.notify("Workload unloaded", str(name)))

        # Overlay placement + visibility from config.
        self.overlay.set_opacity(float(self.config.overlay_opacity))
        self.overlay.apply_corner(str(self.config.overlay_corner))
        if self.config.overlay_enabled:
            self.overlay.show()

        # --- Phase 9: menu bar + tray startup check sync ---
        self._build_menu_bar()
        self.tray.set_startup_checked(bool(self.config.start_with_windows))

        self.tray.set_visible(True)

    # -- Qt overrides -------------------------------------------------------

    def _build_menu_bar(self) -> None:
        """Build the View / Help menu bar (Phase 9)."""
        menubar = self.menuBar()

        view_menu = menubar.addMenu("&View")
        self.act_dark_theme = QAction("Dark theme", self)
        self.act_dark_theme.setCheckable(True)
        self.act_dark_theme.setChecked(self.config.theme == "dark")
        self.act_dark_theme.triggered.connect(self._toggle_theme)
        view_menu.addAction(self.act_dark_theme)

        help_menu = menubar.addMenu("&Help")
        act_about = QAction("About MemScope...", self)
        act_about.triggered.connect(lambda: show_about(self))
        help_menu.addAction(act_about)

    def _toggle_theme(self) -> None:
        """Toggle dark/light theme, re-apply, and persist config."""
        dark = self.act_dark_theme.isChecked()
        self.config.theme = "dark" if dark else "light"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config.theme, self.config.accent)
        apply_plot_theme(self.plot, self.config.theme)
        with contextlib.suppress(Exception):
            save_cfg(self.config)

    def _on_startup_toggled(self, enabled: bool) -> None:
        """Apply the Start-with-Windows toggle and persist config."""
        ok = set_startup(bool(enabled))
        self.config.start_with_windows = bool(enabled) and ok
        self.tray.set_startup_checked(self.config.start_with_windows)
        with contextlib.suppress(Exception):
            save_cfg(self.config)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self._started:
            self._started = True
            self.sampler.start()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.sampler.stop()
        event.accept()

    # -- updates -----------------------------------------------------------

    def _update(self, sample) -> None:
        """Refresh every widget from a fresh :class:`Sample`."""
        self.history.append(sample)
        ts, ru = self.history.ram_used()
        _, cm = self.history.compressed_mb()
        _, pi = self.history.pressure_index()
        self.plot.set_data(ts, ru, cm, pi)
        self.heatmap.set_tiers(self.history.recent_tiers(60))

        ram = sample.ram
        self.ram_gauge.set_value(ram.used_bytes, ram.total_bytes)

        for gpu in sample.gpus:
            key = gpu.luid_key or gpu.name
            gauge = self.gpu_gauges.get(key)
            if gauge is None:
                title = f"{gpu.vendor} {_short_gpu_name(gpu.name)}".strip()
                gauge = GaugeWidget(title)
                self.gpu_gauges[key] = gauge
                self._gauge_row.addWidget(gauge)
            gauge.set_value(gpu.dedicated_used_bytes, gpu.total_bytes)

        self.proc_table.set_rows(sample.procs)

        tier = sample.pressure_tier or "IDLE"
        color = _TIER_COLOR.get(tier, QColor(0xDD, 0xDD, 0xDD))
        self.pressure_label.setText(f"Pressure: {tier} ({sample.pressure_index:.1f})")
        self.pressure_label.setStyleSheet(
            f"font-weight: bold; font-size: 14pt; color: {color.name()};"
        )

        self.compress_label.setText(f"Compressed: {ram.compressed_mb:.1f} MB")

        # --- Phase 5 integration: overlay, tray, alerts, watchdog ---
        self._last_sample = sample
        self.overlay.set_value(sample)
        self.tray.update(sample)
        self.alerts.evaluate(sample)
        try:
            statuses = self.guard.update(sample)
        except Exception:
            statuses = []
        self._last_statuses = statuses
        self._refresh_workloads(statuses)

        # --- phase 3 tabs: hardware panel + port inspector ---
        # Hardware refreshes every sample (cheap; cached QLabels).
        try:
            self.hw_panel.set_hardware(sample.hardware)
        except Exception:
            pass
        # Only repopulate the Network table when it is the current tab to
        # avoid rebuilding a large socket table on every tick.
        try:
            if self.tabs.currentIndex() == self.tabs.indexOf(self.port_tab) and getattr(
                sample, "connections", None
            ):
                self.port_tab.set_connections(sample.connections)
        except Exception:
            pass

    # -- visibility / tray -----------------------------------------------

    def _toggle_visibility(self) -> None:
        """Flip the main window between shown and hidden (for tray)."""
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    # -- workloads panel --------------------------------------------------

    def _refresh_workloads(self, statuses) -> None:
        """Rebuild the workloads table from guard statuses (called on main thread)."""
        table = self.workloads_table
        table.setRowCount(len(statuses))
        for row, st in enumerate(statuses):
            name = st.name
            running = "yes" if st.running else "no"
            pid = str(st.pid) if st.pid else ""
            ram_mb = st.rss_bytes / (1024**2)
            vram_mb = st.vram_bytes / (1024**2)
            ram_txt = f"{ram_mb:.0f} MB" if ram_mb else ""
            vram_txt = f"{vram_mb:.0f} MB" if vram_mb else ""
            idle_txt = f"idle {st.idle_s:.0f}s" if st.running else ""

            items = [
                QTableWidgetItem(name),
                QTableWidgetItem(running),
                QTableWidgetItem(pid),
                QTableWidgetItem(ram_txt),
                QTableWidgetItem(vram_txt),
                QTableWidgetItem(idle_txt),
            ]
            for col, item in enumerate(items):
                table.setItem(row, col, item)

            btn_free = QPushButton("Free")
            btn_stop = QPushButton("Stop")
            btn_free.setEnabled(st.running)
            btn_stop.setEnabled(st.running)
            btn_free.clicked.connect(lambda _checked=False, n=name: self._free_workload(n))
            btn_stop.clicked.connect(lambda _checked=False, n=name: self._stop_workload(n))
            table.setCellWidget(row, 6, btn_free)
            table.setCellWidget(row, 7, btn_stop)

    def _free_workload(self, name: str) -> None:
        """Ask the guard to free VRAM for a workload (with confirmation)."""
        confirm = QMessageBox.question(
            self,
            "Free workload",
            "Free VRAM for " + name + "?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok = self.guard.free(name)
        if ok:
            self.tray.notify("Workload freed", name)

    def _stop_workload(self, name: str) -> None:
        """Ask the guard to terminate a workload (with confirmation)."""
        confirm = QMessageBox.question(
            self,
            "Stop workload",
            "Stop " + name + "? This terminates the process.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok = self.guard.restart(name)
        if ok:
            self.tray.notify("Workload stopped", name)

    # -- snapshots --------------------------------------------------------

    def _snapshot(self) -> None:
        """Write the latest sample as JSON under %APPDATA%/MemScope/snapshots."""
        sample = self._last_sample
        if sample is None:
            self.tray.notify("Snapshot", "No sample available yet.")
            return
        appdata = os.environ.get("APPDATA")
        if not appdata:
            self.tray.notify("Snapshot failed", "APPDATA is not set.")
            return
        snap_dir = Path(appdata) / "MemScope" / "snapshots"
        try:
            snap_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.tray.notify("Snapshot failed", "Could not create dir: " + str(exc))
            return

        ram = sample.ram
        payload = {
            "ts": float(sample.ts),
            "pressure_index": float(sample.pressure_index),
            "pressure_tier": str(sample.pressure_tier),
            "ram": {
                "used_bytes": int(ram.used_bytes),
                "total_bytes": int(ram.total_bytes),
                "compressed_mb": float(ram.compressed_mb),
            },
            "gpus": [
                {
                    "name": g.name,
                    "vendor": g.vendor,
                    "used_bytes": int(g.dedicated_used_bytes),
                    "total_bytes": int(g.total_bytes),
                }
                for g in sample.gpus
            ],
            "procs": [
                {
                    "pid": int(p.pid),
                    "name": p.name,
                    "rss_bytes": int(p.rss_bytes),
                    "private_bytes": int(p.private_bytes),
                    "vram_bytes": int(p.vram_bytes),
                    "cpu_percent": float(p.cpu_percent),
                }
                for p in sample.procs[:20]
            ],
        }
        fname = time.strftime("%Y%m%d-%H%M%S", time.localtime(sample.ts)) + ".json"
        path = snap_dir / fname
        try:
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            self.tray.notify("Snapshot failed", "Write error: " + str(exc))
            return
        self.tray.notify("Snapshot saved", str(path))

    # -- quit -------------------------------------------------------------

    def _quit(self) -> None:
        """Stop sampling, close the window, and quit the application."""
        with contextlib.suppress(Exception):
            self.sampler.stop()
        self.close()
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()
