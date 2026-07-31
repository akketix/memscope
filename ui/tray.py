"""System-tray controller: tier-colored icon, context menu, and balloon helper."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from memscope.core.sample import Sample

# Tier -> icon color (hex). Default (unknown tier) is gray.
_TIER_COLOR: dict[str, str] = {
    "IDLE": "#3a7d3a",
    "LIGHT": "#8bb44a",
    "MODERATE": "#d9a441",
    "HIGH": "#d9534f",
    "CRITICAL": "#a02b2b",
}
_DEFAULT_COLOR: str = "#808080"

_ICON_SIZE: int = 64


class TrayController(QObject):
    """Owns the QSystemTrayIcon and emits user-intent signals.

    The icon is a 64x64 filled circle whose color reflects the current pressure
    tier. update() must be called on the main thread (same as MainWindow._update).
    """

    # User intent emitted to the rest of the app. The controller never touches
    # the window/sampler directly -- owners connect these signals.
    showhide_requested = Signal()
    overlay_requested = Signal()
    snapshot_requested = Signal()
    about_requested = Signal()
    startup_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self, parent_window: QObject | None = None) -> None:
        super().__init__(parent_window)
        self._shown: bool = False

        self.tray = QSystemTrayIcon(self._icon(_DEFAULT_COLOR), parent_window)
        self.tray.setToolTip("MemScope")

        menu = QMenu()
        act_showhide = QAction("Show/Hide", menu)
        act_overlay = QAction("Toggle Overlay", menu)
        act_snapshot = QAction("Snapshot", menu)
        act_about = QAction("About MemScope...", menu)
        self.act_startup = QAction("Start with Windows", menu)
        self.act_startup.setCheckable(True)
        act_quit = QAction("Quit", menu)
        menu.addAction(act_showhide)
        menu.addAction(act_overlay)
        menu.addAction(act_snapshot)
        menu.addSeparator()
        menu.addAction(self.act_startup)
        menu.addAction(act_about)
        menu.addSeparator()
        menu.addAction(act_quit)

        act_showhide.triggered.connect(self.showhide_requested)
        act_overlay.triggered.connect(self.overlay_requested)
        act_snapshot.triggered.connect(self.snapshot_requested)
        act_about.triggered.connect(self.about_requested)
        self.act_startup.toggled.connect(self.startup_toggled)
        act_quit.triggered.connect(self.quit_requested)

        self.tray.setContextMenu(menu)
        # Left-click on the tray icon toggles the main window too.
        self.tray.activated.connect(self._on_activated)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _icon(color: str) -> QIcon:
        """Paint a filled antialiased circle of ``color`` into a 64x64 icon."""
        pixmap = QPixmap(_ICON_SIZE, _ICON_SIZE)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(color))
        painter.setPen(QColor(color))
        radius = _ICON_SIZE // 2 - 2
        center = _ICON_SIZE // 2
        painter.drawEllipse(center, center, radius, radius)
        painter.end()
        return QIcon(pixmap)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A single click on the tray icon toggles the window; ignore other
        # reasons so the context menu and double-click stay distinct.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showhide_requested.emit()

    # -- public API --------------------------------------------------------

    def set_visible(self, visible: bool) -> None:
        if visible:
            self.tray.show()
            self._shown = True
        else:
            self.tray.hide()

    def set_startup_checked(self, checked: bool) -> None:
        """Sync the checkable 'Start with Windows' action without emitting."""
        was = self.act_startup.blockSignals(True)
        try:
            self.act_startup.setChecked(checked)
        finally:
            self.act_startup.blockSignals(was)

    def update(self, sample: Sample) -> None:
        """Refresh icon color and tooltip from a fresh :class:`Sample`."""
        tier = sample.pressure_tier or "IDLE"
        color = _TIER_COLOR.get(tier, _DEFAULT_COLOR)
        self.tray.setIcon(self._icon(color))

        ram_pct = sample.ram.percent if sample.ram.total_bytes else 0.0
        gpu_pct = 0.0
        for gpu in sample.gpus:
            if gpu.total_bytes:
                gpu_pct = gpu.percent
                break

        tooltip = f"MemScope | RAM {ram_pct:.0f}% | VRAM {gpu_pct:.0f}% | {tier}"
        self.tray.setToolTip(tooltip)

        if not self._shown:
            self.tray.show()
            self._shown = True

    def notify(self, title: str, msg: str) -> None:
        """Show a balloon message if the platform supports tray messages."""
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 5000)
