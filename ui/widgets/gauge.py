"""Custom-painted circular gauge widget for RAM/VRAM load display."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

# Arc geometry: a ~270 degree sweep starting at 135deg (bottom-left),
# sweeping clockwise to 45deg (bottom-right), leaving a 90deg gap at the bottom.
_ARC_START_DEG: int = 135  # Qt angles are 1/16 degree; this is the human-facing start
_ARC_SPAN_DEG: int = 270  # full sweep length

_GB: int = 1024**3


def _load_color(percent: float) -> QColor:
    """Pick arc color by load: green <50%, amber <80%, red >=80%."""
    if percent >= 80.0:
        return QColor(0xC0, 0x39, 0x2B)  # red
    if percent >= 50.0:
        return QColor(0xE6, 0x7E, 0x22)  # amber
    return QColor(0x27, 0xAE, 0x60)  # green


class GaugeWidget(QWidget):
    """Circular gauge showing used/total bytes for RAM or a GPU adapter."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.title: str = title
        self.used_bytes: int = 0
        self.total_bytes: int = 0
        self.setMinimumSize(160, 160)

    def set_value(self, used_bytes: int, total_bytes: int) -> None:
        """Update the gauge values and trigger a repaint."""
        self.used_bytes = int(used_bytes)
        self.total_bytes = int(total_bytes)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(220, 220)

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()
        side = min(width, height)

        # Square, centered drawing region.
        margin = int(side * 0.08)
        diameter = side - 2 * margin
        rect = painter.viewport()
        x0 = rect.x() + (width - side) // 2 + margin
        y0 = rect.y() + (height - side) // 2 + margin

        total = self.total_bytes
        used = self.used_bytes
        percent = (used / total * 100.0) if total > 0 else 0.0

        # --- track (background arc) ---
        track_pen = QPen(QColor(0x44, 0x44, 0x44), max(6, int(side * 0.06)))
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(
            x0,
            y0,
            diameter,
            diameter,
            _ARC_START_DEG * 16,
            -_ARC_SPAN_DEG * 16,
        )

        # --- value arc ---
        if total > 0 and used >= 0:
            span = int(-_ARC_SPAN_DEG * 16 * (percent / 100.0))
            value_pen = QPen(_load_color(percent), max(6, int(side * 0.06)))
            value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(value_pen)
            painter.drawArc(x0, y0, diameter, diameter, _ARC_START_DEG * 16, span)

        # --- text: title at top ---
        if self.title:
            title_font = QFont()
            title_font.setPointSizeF(max(8.0, side * 0.055))
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor(0xDD, 0xDD, 0xDD))
            painter.drawText(
                QRectF(0, margin // 2, width, side * 0.12),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.title,
            )

        # --- center text: used GB / total GB ---
        used_gb = used / _GB
        total_gb = total / _GB
        center = f"{used_gb:.1f} / {total_gb:.1f} GB"
        center_font = QFont()
        center_font.setPointSizeF(max(9.0, side * 0.075))
        center_font.setBold(True)
        painter.setFont(center_font)
        painter.setPen(QColor(0xF2, 0xF2, 0xF2))
        painter.drawText(
            QRectF(0, side * 0.38, width, side * 0.18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            center,
        )

        # --- percent below center ---
        pct_text = f"{percent:.0f}%"
        pct_font = QFont()
        pct_font.setPointSizeF(max(8.0, side * 0.055))
        painter.setFont(pct_font)
        painter.setPen(_load_color(percent).lighter(120))
        painter.drawText(
            QRectF(0, side * 0.58, width, side * 0.12),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            pct_text,
        )

        painter.end()
