"""Port-inspector tab: socket connections with per-row Kill buttons."""

from __future__ import annotations

import psutil
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Visible column order (the trailing Kill column is set via setCellWidget).
_COLUMNS = ["Proto", "Family", "Local", "Remote", "Status", "PID", "Process"]


def _addr_port(addr, port) -> str:
    """Render an ``addr:port`` pair, tolerating missing pieces."""
    if not addr and not port:
        return ""
    if addr and port:
        return "{}:{}".format(addr, port)
    if port:
        return ":{}".format(port)
    return str(addr)


def _attr(row, name, default=None):
    """Read ``name`` from a dict (key) or object (attribute)."""
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


class PortInspectorTab(QWidget):
    """Tab widget listing active socket connections.

    Feed ConnRow-like rows (dicts or objects exposing ``pid``, ``name``,
    ``proto``, ``family``, ``local_addr``, ``local_port``, ``remote_addr``,
    ``remote_port`` and ``status``) via :meth:`set_connections`. Emits
    :attr:`row_killed` after a successful kill and :attr:`refresh_requested`
    when the user clicks ``Refresh``.
    """

    row_killed = Signal(int)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._rows: list = []
        self._pid_names: dict[int, str] = {}

        # --- Top bar -----------------------------------------------------
        bar = QHBoxLayout()
        self.filter_label = QLabel("Filter:")
        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setPlaceholderText("case-insensitive match on any column")
        self.filter_edit.textChanged.connect(self._refilter)

        self.only_listening = QCheckBox("Only listening")
        self.only_listening.setChecked(True)
        self.only_listening.toggled.connect(self._refilter)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_requested)

        bar.addWidget(self.filter_label)
        bar.addWidget(self.filter_edit, 1)
        bar.addWidget(self.only_listening)
        bar.addWidget(self.refresh_btn)

        # --- Table -------------------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels(_COLUMNS + ["Kill"])
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(len(_COLUMNS), QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 70)  # Proto
        self.table.setColumnWidth(1, 80)  # Family
        self.table.setColumnWidth(2, 220)  # Local
        self.table.setColumnWidth(3, 220)  # Remote
        self.table.setColumnWidth(4, 90)  # Status
        self.table.setColumnWidth(5, 70)  # PID
        self.table.setColumnWidth(6, 140)  # Process
        self.table.setColumnWidth(7, 70)  # Kill
        header.setStretchLastSection(True)

        # --- Layout ------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_connections(self, rows: list) -> None:
        """Store ``rows`` and repopulate the (filtered) table."""
        self._rows = list(rows)
        self._refilter()

    def current_count(self) -> int:
        """Return the number of rows currently shown."""
        return self.table.rowCount()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _refilter(self, *_args) -> None:
        """Re-apply the filter + only-listening toggle and rebuild the table."""
        needle = self.filter_edit.text().strip().lower()
        only_listen = self.only_listening.isChecked()

        kept = []
        for row in self._rows:
            status = str(_attr(row, "status", "") or "").upper()
            if only_listen and status != "LISTEN":
                continue
            if needle and not self._row_matches(row, needle):
                continue
            kept.append(row)

        kept.sort(key=lambda r: int(_attr(r, "local_port", 0) or 0))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._pid_names.clear()
        self.table.setRowCount(len(kept))

        for idx, row in enumerate(kept):
            pid = int(_attr(row, "pid", 0) or 0)
            name = str(_attr(row, "name", "") or "")
            self._pid_names[pid] = name

            proto = str(_attr(row, "proto", "") or "")
            family = str(_attr(row, "family", "") or "")
            local = _addr_port(_attr(row, "local_addr"), _attr(row, "local_port"))
            remote = _addr_port(_attr(row, "remote_addr"), _attr(row, "remote_port"))
            status = str(_attr(row, "status", "") or "")

            self.table.setItem(idx, 0, QTableWidgetItem(proto))
            self.table.setItem(idx, 1, QTableWidgetItem(family))
            self.table.setItem(idx, 2, QTableWidgetItem(local))
            self.table.setItem(idx, 3, QTableWidgetItem(remote))
            self.table.setItem(idx, 4, QTableWidgetItem(status))

            pid_item = QTableWidgetItem(str(pid))
            pid_item.setData(Qt.UserRole, pid)
            self.table.setItem(idx, 5, pid_item)

            self.table.setItem(idx, 6, QTableWidgetItem(name))

            kill_btn = QPushButton("Kill")
            kill_btn.clicked.connect(lambda _checked=False, p=pid, n=name: self._kill(p, n))
            self.table.setCellWidget(idx, 7, kill_btn)

        self.table.setSortingEnabled(True)

    def _row_matches(self, row, needle: str) -> bool:
        """Return True if ``needle`` appears in any visible column text."""
        local = _addr_port(_attr(row, "local_addr"), _attr(row, "local_port"))
        remote = _addr_port(_attr(row, "remote_addr"), _attr(row, "remote_port"))
        fields = [
            str(_attr(row, "proto", "") or ""),
            str(_attr(row, "family", "") or ""),
            local,
            remote,
            str(_attr(row, "status", "") or ""),
            str(_attr(row, "pid", "") or ""),
            str(_attr(row, "name", "") or ""),
        ]
        for field in fields:
            if needle in field.lower():
                return True
        return False

    def _kill(self, pid: int, name: str) -> None:
        """Confirm then terminate ``pid``; emit :attr:`row_killed` on success."""
        question = "Kill {} (pid {})?".format(name or str(pid), pid)
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
                if proc.is_running():
                    proc.kill()
        except psutil.NoSuchProcess:
            self.row_killed.emit(pid)
            return
        except Exception as exc:  # noqa: BLE001 -- surface unexpected errors
            QMessageBox.warning(
                self,
                "Kill failed",
                "Could not kill {} (pid {}):\n{}".format(name, pid, exc),
            )
            return

        self.row_killed.emit(pid)
