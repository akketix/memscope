"""Frameless always-on-top mini overlay: RAM / VRAM / pressure at a glance.

A tiny translucent window pinned to a screen corner that mirrors the current
pressure tier in real time. Drag it anywhere; toggle it from the tray.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from memscope.core.sample import Sample

# Tier -> label color. Mirrors the tray icon + MainWindow pressure palette:
# green for healthy tiers, amber for moderate, red for the hot tiers.
_TIER_COLOR: dict[str, str] = {
    "IDLE": "#27AE60",
    "LIGHT": "#27AE60",
    "MODERATE": "#E67E22",
    "HIGH": "#C0392B",
    "CRITICAL": "#C0392B",
}

# Friendly text color for the always-on RAM / VRAM readouts.
_LABEL_COLOR: str = "#ECECEC"

_DEFAULT_OPACITY: float = 0.85
_DEFAULT_CORNER: str = "BR"


def _tier_color_hex(tier: str) -> str:
    """Return the hex color for a pressure tier (red if unknown)."""
    return _TIER_COLOR.get(tier, "#C0392B")


class MiniOverlay(QWidget):
    """Frameless, always-on-top, draggable mini status overlay.

    Reads ``overlay_opacity`` (0..1) and ``overlay_corner`` (BR/BL/TR/TL) from
    the optional ``config`` object (the :class:`Config` dataclass from
    :mod:`memscope.config`). Both fields fall back to defaults when the config
    is not supplied or does not yet carry them.
    """

    def __init__(self, config=None) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(260, 40)

        # Config is duck-typed so this module works before memscope.config
        # exists; the fields default sensibly when absent.
        opacity = _DEFAULT_OPACITY
        corner = _DEFAULT_CORNER
        if config is not None:
            opacity = float(getattr(config, "overlay_opacity", _DEFAULT_OPACITY))
            corner = str(getattr(config, "overlay_corner", _DEFAULT_CORNER))

        self._drag_offset: QPoint | None = None

        # Three compact readouts in one row.
        self.lbl_ram = QLabel("RAM --%")
        self.lbl_vram = QLabel("VRAM --%")
        self.lbl_pressure = QLabel("IDLE")

        for lbl in (self.lbl_ram, self.lbl_vram, self.lbl_pressure):
            lbl.setStyleSheet(
                f"color: {_LABEL_COLOR}; font: 11pt 'Consolas'; padding: 0 4px;"
            )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        layout.addWidget(self.lbl_ram)
        layout.addWidget(self.lbl_vram)
        layout.addWidget(self.lbl_pressure, 1)

        # A neutral dark background so the colored text reads on any desktop.
        self.setStyleSheet(
            "MiniOverlay { background-color: rgba(20, 20, 20, 255);"
            " border: 1px solid #333333; border-radius: 6px; }"
        )

        self.set_opacity(opacity)
        if config is not None:
            self.apply_corner(corner)

    # -- updates -----------------------------------------------------------

    def set_value(self, sample: Sample) -> None:
        """Refresh the three labels from a fresh :class:`Sample`."""
        ram_pct = float(sample.ram.percent)
        if sample.gpus:
            vram_pct = sum(g.percent for g in sample.gpus) / len(sample.gpus)
        else:
            vram_pct = 0.0

        self.lbl_ram.setText(f"RAM {ram_pct:5.0f}%")
        self.lbl_vram.setText(f"VRAM {vram_pct:5.0f}%")

        tier = str(sample.pressure_tier)
        self.lbl_pressure.setText(tier)
        self.lbl_pressure.setStyleSheet(
            f"color: {_tier_color_hex(tier)};"
            f" font: bold 11pt 'Consolas'; padding: 0 4px;"
        )

    # -- appearance / placement -------------------------------------------

    def set_opacity(self, f: float) -> None:
        """Clamp the window opacity to a sane 0.2..1.0 range and apply it."""
        self.setWindowOpacity(max(0.2, min(1.0, float(f))))

    def apply_corner(self, corner: str) -> None:
        """Pin the overlay to a screen corner: BR / BL / TR / TL."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        w = self.width()
        h = self.height()
        c = corner.upper()
        if c == "BR":
            self.move(geo.right() - w + 1, geo.bottom() - h + 1)
        elif c == "BL":
            self.move(geo.left(), geo.bottom() - h + 1)
        elif c == "TR":
            self.move(geo.right() - w + 1, geo.top())
        elif c == "TL":
            self.move(geo.left(), geo.top())
        # Unknown corner: leave it where Qt placed it.

    # -- dragging ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 -- Qt override
        if self._drag_offset is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt override
        self._drag_offset = None
        event.accept()

    # -- visibility -------------------------------------------------------

    def toggle(self) -> None:
        """Flip the overlay between shown and hidden."""
        self.setVisible(not self.isVisible())
