"""Hardware telemetry panel: renders a HardwareSample as read-only Qt groups.

Displays CPU identity + temps/powers, per-GPU telemetry with colour-coded
temperatures, memory EXPO/XMP status + DIMM info, disks, fans and voltages.
Designed to be cheap to refresh every second: cached QLabels are updated in
place; only variable-length GPU/disk/fan/voltage sub-rows are rebuilt when
their count changes.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from memscope.core.telemetry import (
    CpuInfo,
    DiskInfo,
    GpuTelemetry,
    HardwareSample,
    MemoryInfo,
    SensorReading,
)

# Temperature colour thresholds (degrees Celsius).
_TEMP_HOT_C: float = 80.0
_TEMP_WARM_C: float = 70.0

_COLOUR_GREEN: str = "#27AE60"
_COLOUR_AMBER: str = "#E67E22"
_COLOUR_RED: str = "#C0392B"
_COLOUR_GREY: str = "#7F8C8D"
_COLOUR_TEXT: str = "#E0E0E0"


def _temp_color(temp_c: float | None) -> str:
    """Pick a stylesheet colour for a temperature reading."""
    if temp_c is None:
        return _COLOUR_GREY
    if temp_c >= _TEMP_HOT_C:
        return _COLOUR_RED
    if temp_c >= _TEMP_WARM_C:
        return _COLOUR_AMBER
    return _COLOUR_GREEN


def _fmt_opt(value: float | None, suffix: str, fmt: str = "{:.0f}") -> str:
    """Format an optional float, returning a dash when unknown."""
    if value is None:
        return "—"
    return fmt.format(value) + suffix


def _section_header_font() -> QFont:
    font = QFont()
    font.setBold(True)
    font.setPointSize(10)
    return font


def _value_label(text: str = "", color: str = _COLOUR_TEXT) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: " + color + ";")
    return lbl


class HardwarePanel(QWidget):
    """Read-only panel that visualises a :class:`HardwareSample`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._gpu_groups: list[dict[str, object]] = []
        self._disk_rows: list[QLabel] = []
        self._fan_rows: list[QLabel] = []
        self._volt_rows: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- source / elevation header -------------------------------------
        self.source_label = QLabel("hardware: —")
        self.source_label.setStyleSheet(
            "color: " + _COLOUR_TEXT + "; font-weight: bold; padding: 2px;"
        )
        root.addWidget(self.source_label)

        # --- CPU section ---------------------------------------------------
        cpu_box = QGroupBox("CPU")
        cpu_form = QFormLayout(cpu_box)
        self._cpu_name = QLabel("—")
        self._cpu_vendor = QLabel("—")
        self._cpu_cores = QLabel("—")
        self._cpu_clock = QLabel("—")
        self._cpu_sensors = QLabel("temps: —\npowers: —")
        self._cpu_sensors.setWordWrap(True)
        for label_text, widget in (
            ("Name", self._cpu_name),
            ("Vendor", self._cpu_vendor),
            ("Cores/Threads", self._cpu_cores),
            ("Max clock", self._cpu_clock),
        ):
            cpu_form.addRow(label_text, widget)
        cpu_form.addRow("Sensors", self._cpu_sensors)
        root.addWidget(cpu_box)

        # --- GPU section (rebuilt when GPU count changes) ------------------
        self._gpu_container = QWidget()
        self._gpu_layout = QVBoxLayout(self._gpu_container)
        self._gpu_layout.setContentsMargins(0, 0, 0, 0)
        self._gpu_layout.setSpacing(6)
        root.addWidget(self._gpu_container)

        # --- Memory section ------------------------------------------------
        mem_box = QGroupBox("Memory")
        mem_form = QFormLayout(mem_box)
        self._mem_expo = QLabel("EXPO/XMP: —")
        self._mem_expo.setStyleSheet("font-weight: bold;")
        self._mem_reason = QLabel("—")
        self._mem_reason.setWordWrap(True)
        self._mem_speed = QLabel("—")
        self._mem_dimms = QLabel("—")
        mem_form.addRow("Profile", self._mem_expo)
        mem_form.addRow("Reason", self._mem_reason)
        mem_form.addRow("Speed", self._mem_speed)
        mem_form.addRow("DIMMs", self._mem_dimms)
        root.addWidget(mem_box)

        # --- Disks section (rebuilt when count changes) --------------------
        self._disk_box = QGroupBox("Disks")
        self._disk_grid = QGridLayout(self._disk_box)
        self._disk_grid.setContentsMargins(8, 8, 8, 8)
        root.addWidget(self._disk_box)

        # --- Fans section (rebuilt when count changes) ----------------------
        self._fan_box = QGroupBox("Fans")
        self._fan_layout = QVBoxLayout(self._fan_box)
        root.addWidget(self._fan_box)

        # --- Voltages section (rebuilt when count changes) -----------------
        self._volt_box = QGroupBox("Voltages")
        self._volt_layout = QVBoxLayout(self._volt_box)
        root.addWidget(self._volt_box)

        root.addStretch(1)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def set_hardware(self, hardware: HardwareSample | None) -> None:
        """Refresh every group from ``hardware``. Tolerates ``None``."""
        if hardware is None:
            self.source_label.setText("hardware: unavailable")
            return
        self._update_source(hardware)
        self._update_cpu(hardware.cpu)
        self._update_gpus(hardware.gpus)
        self._update_memory(hardware.memory)
        self._update_disks(hardware.disks)
        self._update_fans(hardware.fans)
        self._update_voltages(hardware.voltages)

    # ------------------------------------------------------------------ #
    # section updaters
    # ------------------------------------------------------------------ #

    def _update_source(self, hw: HardwareSample) -> None:
        elevated = "elevated" if hw.elevated else "user"
        self.source_label.setText("hardware: " + hw.source + " (" + elevated + ")")

    def _update_cpu(self, cpu: CpuInfo) -> None:
        self._cpu_name.setText(cpu.name or "—")
        self._cpu_vendor.setText(cpu.vendor_label or cpu.vendor or "—")
        cores = cpu.cores
        threads = cpu.threads
        if cores or threads:
            self._cpu_cores.setText(str(cores) + " / " + str(threads))
        else:
            self._cpu_cores.setText("—")
        self._cpu_clock.setText(str(cpu.max_clock_mhz) + " MHz" if cpu.max_clock_mhz else "—")

        temps = ", ".join(self._format_sensor(sr, "C") for sr in cpu.temps) or "—"
        powers = ", ".join(self._format_sensor(sr, "W") for sr in cpu.powers) or "—"
        self._cpu_sensors.setText("temps: " + temps + "\npowers: " + powers)

    def _update_gpus(self, gpus: list[GpuTelemetry]) -> None:
        if len(gpus) != len(self._gpu_groups):
            self._rebuild_gpus(gpus)
            return
        for gpu, group in zip(gpus, self._gpu_groups):
            self._refresh_gpu_group(gpu, group)

    def _rebuild_gpus(self, gpus: list[GpuTelemetry]) -> None:
        # Clear existing groups.
        for group in self._gpu_groups:
            box = group["box"]
            self._gpu_layout.removeWidget(box)
            box.setParent(None)
            box.deleteLater()
        self._gpu_groups = []
        for gpu in gpus:
            group = self._build_gpu_group(gpu)
            self._gpu_groups.append(group)
            self._gpu_layout.addWidget(group["box"])

    def _build_gpu_group(self, gpu: GpuTelemetry) -> dict[str, object]:
        box = QGroupBox("GPU" + (": " + gpu.vendor if gpu.vendor else ""))
        form = QFormLayout(box)
        labels: dict[str, QLabel] = {}
        for key, pretty in (
            ("name", "Name"),
            ("core_temp", "Core temp"),
            ("hot_spot", "Hot spot"),
            ("mem_temp", "Mem temp"),
            ("power", "Power"),
            ("fan", "Fan"),
            ("core_clock", "Core clock"),
            ("mem_clock", "Mem clock"),
            ("util", "Util"),
        ):
            lbl = QLabel("—")
            labels[key] = lbl
            form.addRow(pretty, lbl)
        group: dict[str, object] = {"box": box, "labels": labels}
        self._refresh_gpu_group(gpu, group)
        return group

    def _refresh_gpu_group(self, gpu: GpuTelemetry, group: dict[str, object]) -> None:
        labels: dict[str, QLabel] = group["labels"]  # type: ignore[assignment]
        box: QGroupBox = group["box"]  # type: ignore[assignment]
        title = "GPU"
        if gpu.vendor:
            title = title + ": " + gpu.vendor
        if gpu.name:
            title = title + " — " + gpu.name
        box.setTitle(title)

        labels["name"].setText(gpu.name or "—")
        self._set_temp_label(labels["core_temp"], gpu.core_temp_c, "C")
        self._set_temp_label(labels["hot_spot"], gpu.hot_spot_c, "C")
        self._set_temp_label(labels["mem_temp"], gpu.mem_temp_c, "C")
        labels["power"].setText(_fmt_opt(gpu.power_w, " W", "{:.1f}"))
        labels["fan"].setText(_fmt_opt(gpu.fan_rpm, " RPM"))
        labels["core_clock"].setText(_fmt_opt(gpu.core_clock_mhz, " MHz"))
        labels["mem_clock"].setText(_fmt_opt(gpu.mem_clock_mhz, " MHz"))
        labels["util"].setText(_fmt_opt(gpu.util_pct, " %"))

    def _set_temp_label(self, label: QLabel, temp_c: float | None, suffix: str) -> None:
        label.setText(_fmt_opt(temp_c, " " + suffix))
        label.setStyleSheet("color: " + _temp_color(temp_c) + ";")

    def _update_memory(self, memory: MemoryInfo) -> None:
        # EXPO/XMP big coloured label.
        if memory.expo_enabled is True:
            self._mem_expo.setText((memory.expo_label or "EXPO/XMP") + ": ON")
            self._mem_expo.setStyleSheet("color: " + _COLOUR_GREEN + "; font-weight: bold;")
        elif memory.expo_enabled is False:
            self._mem_expo.setText((memory.expo_label or "EXPO/XMP") + ": OFF")
            self._mem_expo.setStyleSheet("color: " + _COLOUR_AMBER + "; font-weight: bold;")
        else:
            self._mem_expo.setText((memory.expo_label or "EXPO/XMP") + ": ?")
            self._mem_expo.setStyleSheet("color: " + _COLOUR_GREY + "; font-weight: bold;")
        self._mem_reason.setText(memory.reason or "—")
        if memory.advertised_mt or memory.configured_mt:
            speed = "configured " + str(memory.configured_mt) + " MT/s"
            if memory.advertised_mt:
                speed = speed + " / advertised " + str(memory.advertised_mt) + " MT/s"
            self._mem_speed.setText(speed)
        else:
            self._mem_speed.setText("—")
        self._mem_dimms.setText(str(len(memory.dimms)) + " DIMM(s)")

    def _update_disks(self, disks: list[DiskInfo]) -> None:
        if len(disks) != len(self._disk_rows):
            self._rebuild_disks(disks)
            return
        for disk, row in zip(disks, self._disk_rows):
            row.setText(self._format_disk(disk))

    def _rebuild_disks(self, disks: list[DiskInfo]) -> None:
        # Clear the grid.
        while self._disk_grid.count():
            item = self._disk_grid.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._disk_rows = []
        if not disks:
            empty = QLabel("—")
            empty.setStyleSheet("color: " + _COLOUR_GREY + ";")
            self._disk_grid.addWidget(empty, 0, 0)
            self._disk_rows.append(empty)
            return
        header_font = _section_header_font()
        for col, head in enumerate(("Model", "Size", "Interface", "Status", "Temp")):
            head_lbl = QLabel(head)
            head_lbl.setFont(header_font)
            head_lbl.setStyleSheet("color: " + _COLOUR_TEXT + ";")
            self._disk_grid.addWidget(head_lbl, 0, col)
        for row_idx, disk in enumerate(disks, start=1):
            row = QLabel(self._format_disk(disk))
            row.setStyleSheet("color: " + _COLOUR_TEXT + ";")
            self._disk_grid.addWidget(row, row_idx, 0, 1, 5)
            self._disk_rows.append(row)

    def _format_disk(self, disk: DiskInfo) -> str:
        size = "{:.0f} GB".format(disk.size_gb) if disk.size_gb else "—"
        temp = "{:.0f} C".format(disk.temp_c) if disk.temp_c is not None else "—"
        parts = [
            disk.model or "—",
            size,
            disk.interface or "—",
            disk.status or "—",
            temp,
        ]
        return "  ·  ".join(parts)

    def _update_fans(self, fans: list[SensorReading]) -> None:
        if len(fans) != len(self._fan_rows):
            self._rebuild_fans(fans)
            return
        for sr, row in zip(fans, self._fan_rows):
            row.setText(self._format_sensor(sr, "RPM"))

    def _rebuild_fans(self, fans: list[SensorReading]) -> None:
        self._clear_layout(self._fan_layout)
        self._fan_rows = []
        if not fans:
            empty = QLabel("—")
            empty.setStyleSheet("color: " + _COLOUR_GREY + ";")
            self._fan_layout.addWidget(empty)
            self._fan_rows.append(empty)
            return
        for sr in fans:
            row = QLabel(self._format_sensor(sr, "RPM"))
            row.setStyleSheet("color: " + _COLOUR_TEXT + ";")
            self._fan_layout.addWidget(row)
            self._fan_rows.append(row)

    def _update_voltages(self, voltages: list[SensorReading]) -> None:
        if len(voltages) != len(self._volt_rows):
            self._rebuild_voltages(voltages)
            return
        for sr, row in zip(voltages, self._volt_rows):
            row.setText(self._format_sensor(sr, "V", "{:.3f}"))

    def _rebuild_voltages(self, voltages: list[SensorReading]) -> None:
        self._clear_layout(self._volt_layout)
        self._volt_rows = []
        if not voltages:
            empty = QLabel("—")
            empty.setStyleSheet("color: " + _COLOUR_GREY + ";")
            self._volt_layout.addWidget(empty)
            self._volt_rows.append(empty)
            return
        for sr in voltages:
            row = QLabel(self._format_sensor(sr, "V", "{:.3f}"))
            row.setStyleSheet("color: " + _COLOUR_TEXT + ";")
            self._volt_layout.addWidget(row)
            self._volt_rows.append(row)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _format_sensor(self, sr: SensorReading, suffix: str, fmt: str = "{:.1f}") -> str:
        return sr.name + ": " + fmt.format(sr.value) + " " + suffix

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
