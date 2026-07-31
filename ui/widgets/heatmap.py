"""Custom-painted pressure-tier heatmap widget for MemScope.

A horizontal row of colored cells, newest on the right, showing recent
pressure history. Each cell maps a pressure tier label (IDLE / LIGHT /
MODERATE / HIGH / CRITICAL) to a fixed color; no-data cells are dark gray.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

# Tier -> color. Empty/no-data slots use the empty color.
_TIER_COLORS: dict[str, QColor] = {
    "IDLE": QColor(0x2D, 0x5A, 0x2D),
    "LIGHT": QColor(0x6B, 0x9A, 0x3A),
    "MODERATE": QColor(0xD9, 0xA4, 0x41),
    "HIGH": QColor(0xD9, 0x53, 0x4F),
    "CRITICAL": QColor(0xA0, 0x2B, 0x2B),
}

_EMPTY_COLOR: QColor = QColor(0x33, 0x33, 0x33)

# 1px gap between cells keeps adjacent tiers visually distinct.
_GAP: int = 1

_DEFAULT_HEIGHT: int = 28
_SIZE_HINT: QSize = QSize(600, _DEFAULT_HEIGHT)


class PressureHeatmap(QWidget):
    """Horizontal pressure-tier heatmap: oldest cell on the left, newest on the right.

    ``set_tiers`` accepts the recent history of tier labels (oldest -> newest).
    If fewer than ``cells`` are supplied, the row is right-aligned and the
    leading slots are painted with the empty color. If more are supplied, only
    the newest ``cells`` entries are kept.
    """

    def __init__(self, cells: int = 60, parent=None) -> None:
        super().__init__(parent)
        self._cells: int = max(1, int(cells))
        # Each slot holds either a tier label or None for no-data.
        self._tiers: list[str | None] = [None] * self._cells
        self.setMinimumHeight(_DEFAULT_HEIGHT)

    def set_tiers(self, tiers: list[str]) -> None:
        """Update the heatmap from a recent-history list (oldest -> newest).

        Right-aligns when short (pads left with empty), keeps newest when long.
        """
        n = len(tiers)
        if n >= self._cells:
            # Keep only the newest cells.
            kept = list(tiers[n - self._cells :])
        else:
            # Right-align: pad on the left with empty (None) slots.
            kept = [None] * (self._cells - n) + list(tiers)
        # Normalize: unknown tier labels render as empty.
        normalized: list[str | None] = []
        for label in kept:
            if isinstance(label, str) and label in _TIER_COLORS:
                normalized.append(label)
            else:
                normalized.append(None)
        self._tiers = normalized
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override name
        return QSize(_SIZE_HINT)

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        width = self.width()
        height = self.height()
        cells = self._cells
        if cells <= 0 or width <= 0 or height <= 0:
            painter.end()
            return

        # Total gap budget: (cells - 1) gaps between cells.
        total_gap = _GAP * (cells - 1) if cells > 1 else 0
        cell_w = max(1, (width - total_gap) // cells)
        # Center the row horizontally in case of rounding slack.
        used_w = cell_w * cells + total_gap
        x0 = (width - used_w) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(cells):
            label = self._tiers[i]
            color = _TIER_COLORS[label] if label is not None else _EMPTY_COLOR
            painter.setBrush(color)
            x = x0 + i * (cell_w + _GAP)
            painter.drawRect(x, 0, cell_w, height)

        painter.end()
