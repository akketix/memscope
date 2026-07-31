"""Sortable process table with a per-row Kill button."""

from __future__ import annotations

import psutil
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)


def _fmt_bytes(b: int) -> str:
    """Format a byte count as either ``"12.3 GB"`` or ``"456 MB"``."""
    gb = b / (1024**3)
    if gb >= 1.0:
        return f"{gb:.1f} GB"
    return f"{b / (1024**2):.0f} MB"


class ProcTable(QTableWidget):
    """Sortable process table with a per-row Kill button.

    Feeds :class:`memscope.core.sample.ProcRow` objects via
    :meth:`set_rows`. Emits :attr:`row_killed` with the pid after a
    successful kill.
    """

    row_killed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pid_names: dict[int, str] = {}

        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(
            ["Name", "RSS", "Private", "VRAM", "CPU%", "Kill"]
        )
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setVisible(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 90)
        self.setColumnWidth(3, 90)
        self.setColumnWidth(4, 70)
        self.setColumnWidth(5, 70)
        header.setStretchLastSection(False)

    def set_rows(self, rows: list) -> None:
        """Clear and repopulate the table from ``ProcRow`` objects."""
        self.setSortingEnabled(False)
        self.setRowCount(0)
        self._pid_names.clear()

        ordered = sorted(rows, key=lambda r: r.private_bytes, reverse=True)
        self.setRowCount(len(ordered))
        for row_idx, row in enumerate(ordered):
            pid = row.pid
            self._pid_names[pid] = row.name

            name_item = QTableWidgetItem(row.name)
            name_item.setData(Qt.UserRole, pid)
            self.setItem(row_idx, 0, name_item)

            self.setItem(row_idx, 1, QTableWidgetItem(_fmt_bytes(row.rss_bytes)))
            self.setItem(row_idx, 2, QTableWidgetItem(_fmt_bytes(row.private_bytes)))
            self.setItem(row_idx, 3, QTableWidgetItem(_fmt_bytes(row.vram_bytes)))
            self.setItem(row_idx, 4, QTableWidgetItem(f"{row.cpu_percent:.1f}"))

            kill_btn = QPushButton("Kill")
            kill_btn.clicked.connect(lambda _checked=False, p=pid: self._kill(p))
            self.setCellWidget(row_idx, 5, kill_btn)

        self.setSortingEnabled(True)

    def _kill(self, pid: int) -> None:
        """Confirm then terminate the process for ``pid``; emit on success."""
        name = self._pid_names.get(pid, str(pid))
        question = f"Kill {name} (pid {pid})?"
        confirm = QMessageBox.question(
            self,
            "Kill process",
            question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except Exception:
                proc.kill()
        except psutil.NoSuchProcess:
            self.row_killed.emit(pid)
            return
        except Exception as exc:  # noqa: BLE001 -- surface unexpected errors
            QMessageBox.warning(
                self,
                "Kill failed",
                f"Could not kill {name} (pid {pid}):\n{exc}",
            )
            return

        self.row_killed.emit(pid)
