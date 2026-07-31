"""Hardware telemetry: temperatures, power, fans, clocks, voltages, plus CPU,
memory (EXPO/XMP detection) and disk info.

Two layers:
  1. LibreHardwareMonitor in-process via pythonnet (cross-vendor temps /
     power / fans / voltages / SSD temps). Requires the app to run elevated
     so LHM can load its kernel drivers. OPTIONAL — degrades gracefully.
  2. WMI fallbacks (no elevation): CPU vendor/cores/clock, memory + EXPO/XMP
     best-effort heuristic, disk list, GPU engine utilization via win32pdh.

Everything is optional and never raises to the caller; if a layer is missing
the returned HardwareSample simply has fewer populated fields and
`source` reflects what's available.
"""

from __future__ import annotations

import ctypes
import importlib
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any


def _lhm_dir() -> str:
    """Resolve the LibreHardwareMonitor folder, frozen-aware.

    When packaged by PyInstaller the LHM DLLs are bundled under `lhm/` in the
    extraction dir (sys._MEIPASS). Otherwise fall back to the installed path
    or the LHM_DIR env var.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and os.path.isdir(os.path.join(meipass, "lhm")):
        return os.path.join(meipass, "lhm")
    return os.environ.get("LHM_DIR", r"C:\Program Files\LibreHardwareMonitor")


# Default install location of the bundled/installed LibreHardwareMonitor.
LHM_DIR = _lhm_dir()
LHM_LIB = os.path.join(LHM_DIR, "LibreHardwareMonitorLib.dll")

# DDR type by SMBIOSMemoryType (subset).
_DDR_TYPE = {24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "DDR5"}


@dataclass(slots=True)
class SensorReading:
    name: str
    value: float


@dataclass(slots=True)
class CpuInfo:
    name: str = ""
    vendor: str = ""  # AuthenticAMD / GenuineIntel / ...
    vendor_label: str = ""  # "AMD" / "Intel" / "Unknown"
    cores: int = 0
    threads: int = 0
    max_clock_mhz: int = 0
    temps: list[SensorReading] = field(default_factory=list)
    powers: list[SensorReading] = field(default_factory=list)
    clocks: list[SensorReading] = field(default_factory=list)
    loads: list[SensorReading] = field(default_factory=list)


@dataclass(slots=True)
class GpuTelemetry:
    name: str = ""
    vendor: str = ""  # AMD / NVIDIA / Intel
    luid_key: str = ""
    total_bytes: int = 0
    used_bytes: int = 0
    core_temp_c: float | None = None
    hot_spot_c: float | None = None
    mem_temp_c: float | None = None
    power_w: float | None = None
    fan_rpm: float | None = None
    core_clock_mhz: float | None = None
    mem_clock_mhz: float | None = None
    util_pct: float | None = None


@dataclass(slots=True)
class MemoryDimm:
    bank: str = ""
    capacity_gb: float = 0.0
    rated_mt: int = 0  # configured speed as Windows reports it
    configured_mt: int = 0
    manufacturer: str = ""
    part_number: str = ""
    ddr_type: str = ""
    voltage_mv: int = 0


@dataclass(slots=True)
class MemoryInfo:
    dimms: list[MemoryDimm] = field(default_factory=list)
    expo_enabled: bool | None = None  # True/False/None(inconclusive)
    expo_label: str = ""  # "EXPO" (AMD) / "XMP" (Intel)
    advertised_mt: int = 0  # XMP/EXPO speed parsed from P/N
    configured_mt: int = 0
    reason: str = ""


@dataclass(slots=True)
class DiskInfo:
    model: str = ""
    size_gb: float = 0.0
    status: str = ""
    interface: str = ""
    temp_c: float | None = None


@dataclass(slots=True)
class HardwareSample:
    source: str = "none"  # "librehardwaremonitor" | "wmi" | "none"
    elevated: bool = False
    cpu: CpuInfo = field(default_factory=CpuInfo)
    gpus: list[GpuTelemetry] = field(default_factory=list)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    disks: list[DiskInfo] = field(default_factory=list)
    fans: list[SensorReading] = field(default_factory=list)
    voltages: list[SensorReading] = field(default_factory=list)
    controller_temps: list[SensorReading] = field(default_factory=list)


# --- elevation ---------------------------------------------------------------


def is_elevated() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


# --- LibreHardwareMonitor in-process reader ---------------------------------

_LHM_AVAILABLE: bool | None = None
_LHM_COMPUTER: Any = None


def _lhm_try_init() -> bool:
    """Try to initialise the LHM Computer once. Cached for the process."""
    global _LHM_AVAILABLE, _LHM_COMPUTER
    if _LHM_AVAILABLE is not None:
        return _LHM_AVAILABLE
    if not is_elevated() or not os.path.isfile(LHM_LIB):
        _LHM_AVAILABLE = False
        return False
    try:
        import pythonnet  # type: ignore

        pythonnet.load("netfx")
        import clr  # type: ignore  # noqa: F401

        os.chdir(LHM_DIR)
        getattr(clr, "AddReference")(LHM_LIB)
        lhm_hw: Any = importlib.import_module("LibreHardwareMonitor.Hardware")
        Computer = getattr(lhm_hw, "Computer")

        comp: Any = Computer()
        comp.IsCpuEnabled = True
        comp.IsGpuEnabled = True
        comp.IsMotherboardEnabled = True
        comp.IsControllerEnabled = True
        comp.IsStorageEnabled = True
        comp.IsMemoryEnabled = True
        comp.Open()
        _LHM_COMPUTER = comp
        _LHM_AVAILABLE = True
    except Exception:
        _LHM_AVAILABLE = False
    return _LHM_AVAILABLE


def _read_lhm() -> HardwareSample | None:
    if not _lhm_try_init():
        return None
    comp = _LHM_COMPUTER
    out = HardwareSample(source="librehardwaremonitor", elevated=True)

    # Multiple update rounds: power/temp are derived and read 0 on first tick.
    for _ in range(3):
        for hw in comp.Hardware:
            hw.Update()
            for sub in hw.SubHardware:
                sub.Update()

    # Now collect per-hardware.
    for hw in comp.Hardware:
        htype = str(hw.HardwareType)
        name = hw.Name or ""
        temps: list[SensorReading] = []
        powers: list[SensorReading] = []
        clocks: list[SensorReading] = []
        loads: list[SensorReading] = []
        fans: list[SensorReading] = []
        volts: list[SensorReading] = []
        for s in hw.Sensors:
            val = s.Value
            if val is None:
                continue
            sr = SensorReading(s.Name, float(val))
            stype = str(s.SensorType)
            if stype == "Temperature":
                temps.append(sr)
            elif stype == "Power":
                powers.append(sr)
            elif stype == "Clock":
                clocks.append(sr)
            elif stype == "Load":
                loads.append(sr)
            elif stype == "Fan":
                fans.append(sr)
            elif stype == "Voltage":
                volts.append(sr)
        # Also collect subhardware sensors (e.g. SuperIO fans/voltages,
        # storage sub-sensors).
        for sub in hw.SubHardware:
            sub.Update()
            for s in sub.Sensors:
                val = s.Value
                if val is None:
                    continue
                stype = str(s.SensorType)
                sr = SensorReading(s.Name, float(val))
                if stype == "Temperature":
                    temps.append(sr)
                elif stype == "Fan":
                    fans.append(sr)
                elif stype == "Voltage":
                    volts.append(sr)
                elif stype == "Power":
                    powers.append(sr)
                elif stype == "Clock":
                    clocks.append(sr)
                elif stype == "Load":
                    loads.append(sr)

        if htype == "Cpu":
            out.cpu.temps = temps
            out.cpu.powers = powers
            out.cpu.clocks = clocks
            out.cpu.loads = loads
        elif htype in ("GpuNvidia", "GpuAmd", "GpuIntel"):
            g = GpuTelemetry(
                name=name,
                vendor={"GpuNvidia": "NVIDIA", "GpuAmd": "AMD", "GpuIntel": "Intel"}.get(
                    htype, "Unknown"
                ),
            )
            for sr in temps:
                low = sr.name.lower()
                if "hot spot" in low or "hotspot" in low:
                    g.hot_spot_c = sr.value
                elif "memory" in low:
                    g.mem_temp_c = sr.value
                elif g.core_temp_c is None or "core" in low:
                    g.core_temp_c = sr.value
            for sr in powers:
                if g.power_w is None or "package" in sr.name.lower():
                    g.power_w = sr.value
            for sr in fans:
                g.fan_rpm = sr.value
            for sr in clocks:
                low = sr.name.lower()
                if "memory" in low:
                    g.mem_clock_mhz = sr.value
                elif g.core_clock_mhz is None or "core" in low:
                    g.core_clock_mhz = sr.value
            for sr in loads:
                if g.util_pct is None or "core" in sr.name.lower():
                    g.util_pct = sr.value
            out.gpus.append(g)
        elif htype == "SuperIO":
            out.fans.extend(fans)
            out.voltages.extend(volts)
            out.controller_temps.extend(temps)
        elif htype == "Motherboard":
            out.controller_temps.extend(temps)
        elif htype == "Storage":
            # Match SSD temps to disks by name (filled later in WMI step).
            for sr in temps:
                out.controller_temps.append(SensorReading("Storage: " + sr.name, sr.value))

    # Merge WMI data (CPU identity, memory EXPO, disks) into the LHM sample.
    _fill_wmi(out)
    return out


# --- WMI fallbacks -----------------------------------------------------------


def _wmi_cpu(out: HardwareSample) -> None:
    try:
        import win32com  # type: ignore  # noqa: F401
    except Exception:
        pass
    try:
        c = _cim("Win32_Processor")[0]
        out.cpu.name = c.Name or ""
        out.cpu.vendor = c.Manufacturer or ""
        out.cpu.vendor_label = (
            "AMD"
            if "AMD" in out.cpu.vendor.upper()
            else "Intel"
            if "Intel" in out.cpu.vendor.upper()
            else "Unknown"
        )
        out.cpu.cores = int(c.NumberOfCores or 0)
        out.cpu.threads = int(c.NumberOfLogicalProcessors or 0)
        out.cpu.max_clock_mhz = int(c.MaxClockSpeed or 0)
    except Exception:
        pass


def _cim(cls):
    # Lazy WMI via wmi or win32com; prefer win32com (already a pywin32 dep).
    import win32com.client  # type: ignore

    wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", r"root\cimv2")
    return list(wmi.ExecQuery("Select * from " + cls))


def _wmi_memory(out: HardwareSample) -> None:
    info = out.memory
    try:
        for d in _cim("Win32_PhysicalMemory"):
            info.dimms.append(
                MemoryDimm(
                    bank=str(getattr(d, "BankLabel", "") or ""),
                    capacity_gb=round(int(getattr(d, "Capacity", 0) or 0) / 1e9, 1),
                    rated_mt=int(getattr(d, "Speed", 0) or 0),
                    configured_mt=int(getattr(d, "ConfiguredClockSpeed", 0) or 0),
                    manufacturer=str(getattr(d, "Manufacturer", "") or "").strip(),
                    part_number=str(getattr(d, "PartNumber", "") or "").strip(),
                    ddr_type=_DDR_TYPE.get(int(getattr(d, "SMBIOSMemoryType", 0) or 0), ""),
                    voltage_mv=int(getattr(d, "ConfiguredVoltage", 0) or 0),
                )
            )
    except Exception:
        pass
    _infer_expo(info)


def _infer_expo(info: MemoryInfo) -> None:
    """Best-effort EXPO/XMP detection from the part number + configured speed.

    Win32_PhysicalMemory.Speed on DDR5 reports the *configured* speed, not the
    XMP/EXPO max, so we parse the advertised speed from the part number (e.g.
    AX5U6000 -> 6000) and compare. Inconclusive if no advertised speed found.
    """
    info.expo_label = "EXPO" if out_cpu_is_amd() else "XMP"
    if not info.dimms:
        return
    pn = info.dimms[0].part_number
    info.configured_mt = info.dimms[0].configured_mt or info.dimms[0].rated_mt
    m = re.search(r"(\d{4})", pn)
    if not m:
        info.expo_enabled = None
        info.reason = "no advertised speed in part number"
        return
    adv = int(m.group(1))
    info.advertised_mt = adv
    cfg = info.configured_mt
    if adv < 2000:  # not a plausible DDR speed token
        info.expo_enabled = None
        info.reason = "part-number digit run not a memory speed"
        return
    if cfg >= adv:
        info.expo_enabled = True
        info.reason = f"configured {cfg} MT/s >= advertised {adv} MT/s"
    else:
        info.expo_enabled = False
        info.reason = f"configured {cfg} MT/s < advertised {adv} MT/s (XMP/EXPO off)"


def out_cpu_is_amd() -> bool:
    try:
        v = _cim("Win32_Processor")[0].Manufacturer or ""
        return "AMD" in v.upper()
    except Exception:
        return False


def _wmi_disks(out: HardwareSample) -> None:
    try:
        for d in _cim("Win32_DiskDrive"):
            model = str(getattr(d, "Model", "") or "").strip()
            disk = DiskInfo(
                model=model,
                size_gb=round(int(getattr(d, "Size", 0) or 0) / 1e9, 1),
                status=str(getattr(d, "Status", "") or ""),
                interface=str(getattr(d, "InterfaceType", "") or ""),
            )
            # Match a storage temp recorded as "Storage: <name> <temp>".
            for sr in out.controller_temps:
                if model and model.lower() in sr.name.lower():
                    disk.temp_c = sr.value
            out.disks.append(disk)
    except Exception:
        pass


def _wmi_gpu_util() -> None:
    # GPU util is attached in vram layer; here we could add per-GPU util.
    pass


def _fill_wmi(out: HardwareSample) -> None:
    _wmi_cpu(out)
    _wmi_memory(out)
    _wmi_disks(out)


# --- public API --------------------------------------------------------------


def is_hardware_available() -> bool:
    return _lhm_try_init()


def sample_hardware() -> HardwareSample:
    """Return a hardware snapshot. Uses LHM if available/elevated, else WMI."""
    lhm = _read_lhm()
    if lhm is not None:
        return lhm
    out = HardwareSample(source="wmi", elevated=is_elevated())
    _fill_wmi(out)
    return out


if __name__ == "__main__":
    h = sample_hardware()
    print("source:", h.source, "| elevated:", h.elevated)
    print("CPU:", h.cpu.name, "| vendor:", h.cpu.vendor_label, "| cores:", h.cpu.cores)
    print(
        "memory EXPO:", h.memory.expo_enabled, "| label:", h.memory.expo_label, "|", h.memory.reason
    )
    for g in h.gpus:
        print(
            "GPU:",
            g.vendor,
            g.name,
            "| core",
            g.core_temp_c,
            "C | power",
            g.power_w,
            "W | fan",
            g.fan_rpm,
            "RPM",
        )
    for d in h.disks:
        print("disk:", d.model, d.size_gb, "GB | temp", d.temp_c)
