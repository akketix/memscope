"""Threshold + duration alert engine with per-rule cooldown (no flapping)."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

from memscope.config import AlertThreshold, Config
from memscope.core.sample import Sample


def _metric_value(rule: AlertThreshold, sample: Sample) -> float:
    """Resolve a rule's metric to a comparable float on this sample."""
    metric = rule.metric
    if metric == "compressed_mb":
        return float(sample.ram.compressed_mb)
    if metric == "pressure_index":
        return float(sample.pressure_index)
    if metric == "vram_percent":
        if not sample.gpus:
            return 0.0
        return float(max(gpu.percent for gpu in sample.gpus))
    if metric == "pressure_tier":
        # 1.0 when the sample's tier matches the rule's target tier, else 0.0.
        return 1.0 if sample.pressure_tier == rule.tier else 0.0
    return 0.0


def _build_message(rule: AlertThreshold, value: float) -> str:
    """Human-readable alert body describing what crossed and by how much."""
    if rule.metric == "pressure_tier":
        return f"{rule.label} reached tier {rule.tier} (threshold {rule.threshold})"
    return f"{rule.label} reached {value:.1f} (threshold {rule.threshold:.1f})"


class AlertEngine(QObject):
    """Evaluates alert rules against samples, honoring hold time and cooldown."""

    fired = Signal(str, str)  # title, message

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        # Per-rule cooldown tracker: {rule_label: last_fired_ts}.
        self._last_fired: dict[str, float] = {}
        # Per-rule hold tracker: {rule_label: first_seen_ts} while condition holds.
        self._first_seen: dict[str, float] = {}

    def evaluate(self, sample: Sample) -> list[tuple[str, str]]:
        """Evaluate every configured rule and return the list of fired alerts."""
        results: list[tuple[str, str]] = []
        rules = getattr(self._config, "alerts", None)
        if not rules:
            return results

        now = time.time()
        for rule in rules:
            label = rule.label
            value = _metric_value(rule, sample)

            # Condition: value at/over threshold. For pressure_tier the
            # threshold is compared against the 0.0/1.0 match signal.
            condition_holds = value >= rule.threshold

            if not condition_holds:
                # Reset the hold window so a fresh crossing restarts the timer.
                self._first_seen.pop(label, None)
                continue

            first_seen = self._first_seen.get(label)
            if first_seen is None:
                first_seen = now
                self._first_seen[label] = first_seen

            held = now - first_seen
            if held < rule.duration_s:
                continue

            # Held long enough -- respect cooldown so a sustained condition
            # only notifies once per cooldown window.
            last = self._last_fired.get(label, 0.0)
            if now - last < rule.cooldown_s:
                continue

            message = _build_message(rule, value)
            self._last_fired[label] = now
            self.fired.emit(label, message)
            results.append((label, message))

        return results

    def reset(self) -> None:
        """Clear all cooldown and hold trackers."""
        self._last_fired.clear()
        self._first_seen.clear()
