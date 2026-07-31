"""Dark/light QSS stylesheet system + pyqtgraph theme helpers for MemScope."""

from __future__ import annotations

import contextlib
from typing import Any

# ---------------------------------------------------------------------------
# Palette constants
# ---------------------------------------------------------------------------

DARK: dict[str, str] = {
    "window_bg": "#1e2228",
    "text": "#c8d0da",
    "panel_bg": "#252a32",
    "accent": "#3a7d3a",
    "border": "#3a4150",
    "table_alt": "#22272f",
    "highlight": "#3a7d3a",
}

LIGHT: dict[str, str] = {
    "window_bg": "#f4f5f7",
    "text": "#1a1a1a",
    "panel_bg": "#ffffff",
    "accent": "#3a7d3a",
    "border": "#c8ccd2",
    "table_alt": "#eef0f3",
    "highlight": "#3a7d3a",
}

_PALETTES = {"dark": DARK, "light": LIGHT}

_DEFAULT_ACCENT = "#3a7d3a"


def _palette(theme: str) -> dict[str, str]:
    key = theme.lower()
    if key not in _PALETTES:
        key = "dark"
    return _PALETTES[key]


# ---------------------------------------------------------------------------
# QSS stylesheet
# ---------------------------------------------------------------------------


def stylesheet(theme: str = "dark", accent: str = _DEFAULT_ACCENT) -> str:
    """Return a complete QSS string for the given theme and accent color."""
    p = _palette(theme)
    window_bg = p["window_bg"]
    text = p["text"]
    panel_bg = p["panel_bg"]
    border = p["border"]
    table_alt = p["table_alt"]
    highlight = accent

    parts: list[str] = []

    parts.append(
        f"""QMainWindow, QWidget {{
    background-color: {window_bg};
    color: {text};
    font-family: 'Segoe UI', 'DejaVu Sans', sans-serif;
    font-size: 10pt;
}}"""
    )

    parts.append(
        f"""QLabel {{
    background: transparent;
    color: {text};
}}"""
    )

    parts.append(
        f"""QGroupBox {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    margin-top: 10px;
    padding: 10px 6px 6px 6px;
    color: {text};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {text};
}}"""
    )

    parts.append(
        f"""QPushButton {{
    background-color: {panel_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover {{
    background-color: {accent};
    color: #ffffff;
    border: 1px solid {accent};
}}
QPushButton:pressed {{
    background-color: {accent};
    color: #ffffff;
}}
QPushButton:disabled {{
    color: #6b7280;
    border: 1px solid {border};
}}"""
    )

    parts.append(
        f"""QTableWidget {{
    background-color: {panel_bg};
    alternate-background-color: {table_alt};
    color: {text};
    border: 1px solid {border};
    border-radius: 4px;
    gridline-color: {border};
    selection-background-color: {highlight};
    selection-color: #ffffff;
}}
QTableWidget::item {{
    padding: 3px 6px;
}}
QTableWidget::item:alternate {{
    background-color: {table_alt};
}}
QTableWidget::item:selected {{
    background-color: {highlight};
    color: #ffffff;
}}"""
    )

    parts.append(
        f"""QHeaderView {{
    background-color: {panel_bg};
    border: none;
    border-bottom: 1px solid {border};
}}
QHeaderView::section {{
    background-color: {table_alt};
    color: {text};
    padding: 4px 8px;
    border: none;
    border-right: 1px solid {border};
    font-weight: bold;
}}"""
    )

    parts.append(
        f"""QMenu {{
    background-color: {panel_bg};
    color: {text};
    border: 1px solid {border};
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 18px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background-color: {highlight};
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 8px;
}}"""
    )

    parts.append(
        f"""QMenuBar {{
    background-color: {window_bg};
    color: {text};
    border-bottom: 1px solid {border};
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 12px;
}}
QMenuBar::item:selected {{
    background-color: {highlight};
    color: #ffffff;
}}"""
    )

    parts.append(
        f"""QScrollBar:vertical {{
    background: {window_bg};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {highlight};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {window_bg};
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {border};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {highlight};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}"""
    )

    return "\n\n".join(parts) + "\n"


def apply_theme(app: Any, theme: str = "dark", accent: str = _DEFAULT_ACCENT) -> None:
    """Apply the given theme's stylesheet to a QApplication instance."""
    app.setStyleSheet(stylesheet(theme, accent))


# ---------------------------------------------------------------------------
# pyqtgraph helpers
# ---------------------------------------------------------------------------

_PLOT_DARK = ("#0f1620", "#c8d0da", "#2a3340")
_PLOT_LIGHT = ("#ffffff", "#1a1a1a", "#e0e0e0")

_PLOT_PALETTES = {"dark": _PLOT_DARK, "light": _PLOT_LIGHT}


def plot_colors(theme: str = "dark") -> tuple[str, str, str]:
    """Return (background, foreground, grid) colors for pyqtgraph."""
    key = theme.lower()
    if key not in _PLOT_PALETTES:
        key = "dark"
    return _PLOT_PALETTES[key]


def apply_plot_theme(plot_widget: Any, theme: str = "dark") -> None:
    """Apply theme colors to a pyqtgraph PlotWidget.

    Sets the background and axis pen/text colors, guarding each step so a
    missing axis or method never raises.
    """
    bg, fg, _grid = plot_colors(theme)

    with contextlib.suppress(Exception):
        plot_widget.setBackground(bg)

    with contextlib.suppress(Exception):
        axis = plot_widget.getAxis("left")
        if hasattr(axis, "setPen"):
            axis.setPen(fg)
        if hasattr(axis, "setTextPen"):
            axis.setTextPen(fg)

    with contextlib.suppress(Exception):
        axis = plot_widget.getAxis("bottom")
        if hasattr(axis, "setPen"):
            axis.setPen(fg)
        if hasattr(axis, "setTextPen"):
            axis.setTextPen(fg)
