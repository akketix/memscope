"""About dialog for MemScope."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from memscope import __version__

_DESCRIPTION = "RAM / VRAM pressure monitor for Windows (AMD, NVIDIA, Intel)."
_TAGLINE = "Surfaces the Windows Memory Compression pressure signal no stock tool shows."

_TIERS = [
    ("IDLE", "#3a7d3a"),
    ("LIGHT", "#8bb44a"),
    ("MODERATE", "#d9a441"),
    ("HIGH", "#d9534f"),
    ("CRITICAL", "#a02b2b"),
]


def _tier_row(label: str, color: str, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    swatch = QLabel(row)
    swatch.setFixedSize(16, 16)
    swatch.setStyleSheet("background-color: " + color + "; border: 1px solid #222;")
    h.addWidget(swatch)
    text = QLabel(label, row)
    h.addWidget(text)
    h.addStretch(1)
    return row


def build_about_dialog(parent: QWidget | None = None) -> QDialog:
    """Construct (but do not exec) the About dialog."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("About MemScope")
    dlg.setFixedSize(420, 320)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(20, 20, 20, 20)
    root.setSpacing(10)

    name = QLabel("MemScope", dlg)
    name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name.setStyleSheet("font-size: 26pt; font-weight: 700;")
    root.addWidget(name)

    version = QLabel("v" + __version__, dlg)
    version.setAlignment(Qt.AlignmentFlag.AlignCenter)
    version.setStyleSheet("font-size: 11pt; color: #888;")
    root.addWidget(version)

    desc = QLabel(_DESCRIPTION, dlg)
    desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
    desc.setWordWrap(True)
    root.addWidget(desc)

    legend_title = QLabel("Pressure tiers", dlg)
    legend_title.setStyleSheet("font-weight: 600; margin-top: 6px;")
    root.addWidget(legend_title)
    for label, color in _TIERS:
        root.addWidget(_tier_row(label, color, dlg))

    tagline = QLabel(_TAGLINE, dlg)
    tagline.setWordWrap(True)
    tagline.setStyleSheet("font-style: italic; color: #777; margin-top: 6px;")
    root.addWidget(tagline)

    root.addStretch(1)

    ok_btn = QPushButton("OK", dlg)
    ok_btn.setDefault(True)
    ok_btn.clicked.connect(dlg.accept)
    hbox = QHBoxLayout()
    hbox.addStretch(1)
    hbox.addWidget(ok_btn)
    hbox.addStretch(1)
    root.addLayout(hbox)

    return dlg


def show_about(parent: QWidget | None = None) -> int:
    """Build and execute the About dialog. Returns exec() code."""
    dlg = build_about_dialog(parent)
    return dlg.exec()
