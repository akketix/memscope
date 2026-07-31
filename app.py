"""MemScope application entry point with single-instance guarding."""

from __future__ import annotations

import contextlib
import os
import sys

from PySide6.QtCore import QSharedMemory
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from memscope.config import load as load_cfg, save as save_cfg
from memscope.ui.main_window import MainWindow
from memscope.ui.theme import apply_theme

# Module-level holder for the shared-memory segment so it stays alive for the
# whole process lifetime (QApplication does not expose a custom attribute).
_SHARED_MEM: QSharedMemory | None = None

# Repo root: app.py -> memscope -> repo root.
_REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_path(rel: str) -> str:
    """Resolve a bundled resource path (PyInstaller _MEIPASS-aware)."""
    base = getattr(sys, "_MEIPASS", _REPO_ROOT)
    return os.path.join(base, rel)


def main() -> int:
    global _SHARED_MEM

    app = QApplication(sys.argv)
    app.setApplicationName("MemScope")
    # Application-wide window icon (PyInstaller _MEIPASS-aware).
    app.setWindowIcon(QIcon(_resource_path("memscope/assets/icon.ico")))
    # Apply the persisted theme before the window is constructed/shown.
    with contextlib.suppress(Exception):
        cfg = load_cfg()
        apply_theme(app, cfg.theme, cfg.accent)
    # Closing the main window must NOT quit the app: the tray Quit action is
    # the real exit. setQuitOnLastWindowClosed(False) keeps the tray alive
    # even when the window is hidden.
    app.setQuitOnLastWindowClosed(False)

    # Single-instance guard: if we can attach to an existing shared segment,
    # another MemScope is already running.
    shm = QSharedMemory("memscope-single")
    if shm.attach():
        QMessageBox.warning(
            None,
            "MemScope",
            "Another instance of MemScope is already running.",
        )
        return 0
    shm.create(1)
    # Keep the segment alive for the lifetime of the app.
    _SHARED_MEM = shm

    window = MainWindow()
    window.show()

    # Ensure the tray icon is visible (the tray owns the quit action).
    if window.tray is not None:
        window.tray.set_visible(True)

    def _on_about_to_quit() -> None:
        # Stop the sampler thread promptly on exit.
        with contextlib.suppress(Exception):
            window.sampler.stop()
        # Persist config if it was changed at runtime.
        with contextlib.suppress(Exception):
            save_cfg(window.config)

    app.aboutToQuit.connect(_on_about_to_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
