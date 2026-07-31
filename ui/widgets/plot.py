"""pyqtgraph time-series plot for RAM/Compression/Pressure history."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

# Curve colors (consistent with the rest of the MemScope palette).
_RAM_PEN = pg.mkPen(color=(0x29, 0x80, 0xB9), width=2)  # blue
_COMPRESSED_PEN = pg.mkPen(color=(0xE6, 0x7E, 0x22), width=2)  # orange
_PRESSURE_PEN = pg.mkPen(color=(0xC0, 0x39, 0x2B), width=2)  # red

_PRESSURE_MIN = 0.0
_PRESSURE_MAX = 100.0


class HistoryPlot(QWidget):
    """QWidget wrapping a :class:`pg.PlotWidget` showing three history curves.

    Left Y axis: GB for RAM used (blue) and Compressed working set (orange).
    Right Y axis: 0..100 for the Pressure index (red), on a linked ViewBox.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._plot = pg.PlotWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

        item = self._plot.getPlotItem()
        item.setLabel("left", "GB")
        item.setLabel("bottom", "elapsed s")
        item.showGrid(x=True, y=True, alpha=0.25)
        item.setMouseEnabled(x=False, y=False)
        item.setMenuEnabled(False)

        # --- second ViewBox for the pressure index (right axis 0..100) ---
        self._pressure_vb = pg.ViewBox()
        item.scene().addItem(self._pressure_vb)
        item.showAxis("right")
        item.setLabel("right", "Pressure 0-100")
        item.getAxis("right").linkToView(self._pressure_vb)
        self._pressure_vb.setXLink(item)
        self._pressure_vb.setYRange(_PRESSURE_MIN, _PRESSURE_MAX, padding=0)

        # Keep the pressure ViewBox geometry in sync with the main one.
        item.vb.sigResized.connect(self._sync_pressure_view)

        # --- curves (created once, updated via setData) ---
        self._ram_curve = item.plot(pen=_RAM_PEN, name="RAM used")
        self._compressed_curve = item.plot(pen=_COMPRESSED_PEN, name="Compressed")
        self._pressure_curve = pg.PlotDataItem(pen=_PRESSURE_PEN, name="Pressure")
        self._pressure_vb.addItem(self._pressure_curve)

        # Track whether we have any data plotted yet.
        self._has_data = False

    # -- internal ----------------------------------------------------------

    def _sync_pressure_view(self, *args) -> None:
        """Mirror the main ViewBox geometry onto the pressure ViewBox."""
        main = self._plot.getPlotItem().vb
        self._pressure_vb.setGeometry(main.sceneBoundingRect())
        self._pressure_vb.linkedViewChanged(main, self._pressure_vb.XAxis)

    # -- public API --------------------------------------------------------

    def set_data(
        self,
        ts: list[float],
        ram_used_gb: list[float],
        compressed_mb: list[float],
        pressure: list[float],
    ) -> None:
        """Update all three curves from equal-length history lists.

        ``ts`` are absolute epoch seconds; x is plotted as relative seconds
        from the first sample (ts[i] - ts[0]). Empty lists clear the plot.
        """
        n = len(ts)
        if n == 0 or not ram_used_gb or not compressed_mb or not pressure:
            self._clear()
            return

        x0 = ts[0]
        x = [t - x0 for t in ts]

        self._ram_curve.setData(x, ram_used_gb)
        self._compressed_curve.setData(x, compressed_mb)
        self._pressure_curve.setData(x, pressure)

        # Keep the pressure axis pinned to 0..100 regardless of values.
        self._pressure_vb.setYRange(_PRESSURE_MIN, _PRESSURE_MAX, padding=0)
        self._has_data = True

    def _clear(self) -> None:
        """Drop all plotted data without recreating the curve objects."""
        self._ram_curve.setData([], [])
        self._compressed_curve.setData([], [])
        self._pressure_curve.setData([], [])
        self._has_data = False
