"""Background thread that polls RAM/VRAM snapshots and emits them."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class SamplerThread(QThread):
    """Polls :func:`memscope.console.take_sample` every ``interval`` seconds.

    Emits each fully-filled :class:`memscope.core.sample.Sample` via
    :attr:`sample_ready`. The loop is exception-safe: a single bad sample
    never kills the thread. Stop promptly with :meth:`stop`.
    """

    sample_ready = Signal(object)

    def __init__(self, interval: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self._interval = float(interval)

    def run(self) -> None:  # noqa: D401 -- QThread entry point
        # Imported lazily so importing this module is side-effect free.
        from memscope.console import take_sample

        while not self.isInterruptionRequested():
            try:
                s = take_sample()
            except Exception:
                s = None
            if s is not None:
                self.sample_ready.emit(s)

            # Sleep in small slices so stop() responds promptly.
            remaining = self._interval
            while remaining > 0.0 and not self.isInterruptionRequested():
                self.msleep(max(0, int(min(0.1, remaining) * 1000)))
                remaining -= 0.1

    def stop(self) -> None:
        """Request interruption and block briefly until the thread exits."""
        self.requestInterruption()
        self.quit()
        self.wait(2000)
