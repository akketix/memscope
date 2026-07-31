"""DXGI adapter enumeration via ctypes — the cross-vendor way to get the
*true* total VRAM for AMD, NVIDIA, and Intel GPUs.

Win32_VideoController.AdapterRAM is a 32-bit value and caps at 4 GB, which
broke on your 16 GB AMD RX 7900 GRE. DXGI's DXGI_ADAPTER_DESC.
DedicatedVideoMemory is a SIZE_T (64-bit) and is correct for all vendors.

Each adapter carries an LUID we use to join the live usage perf counters
(see perf_counters.enumerate_gpu_adapter_usage).
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

# --- COM / DXGI plumbing ----------------------------------------------------

_dxgi = ctypes.windll.dxgi
_ole32 = ctypes.windll.ole32


def _ensure_com() -> None:
    """Initialize COM on this thread. Required for DXGI; ignore if already init."""
    # COINIT_APARTMENTTHREADED = 0x2. S_FALSE / RPC_E_CHANGED_MODE are benign.
    _ole32.CoInitializeEx(None, 0x2)


_VENDORS = {
    0x1002: "AMD",
    0x10DE: "NVIDIA",
    0x8086: "Intel",
    0x1414: "Microsoft",  # Basic Render Driver / WARP — filtered out
}


class _IID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


# IID_IDXGIFactory = {7b7166ec-21c7-44ae-b21a-c9ae321ae369}
_IID_IDXGIFactory = _IID(
    0x7B7166EC,
    0x21C7,
    0x44AE,
    (ctypes.c_ubyte * 8)(0xB2, 0x1A, 0xC9, 0xAE, 0x32, 0x1A, 0xE3, 0x69),
)


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]


class _DXGI_ADAPTER_DESC(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
    ]


# stdcall (WINFUNCTYPE) prototypes; first arg is always the COM `this` pointer.
_ULONG = ctypes.c_ulong
_HRESULT = ctypes.c_long
_Release = ctypes.WINFUNCTYPE(_ULONG, ctypes.c_void_p)
_EnumAdapters = ctypes.WINFUNCTYPE(
    _HRESULT, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
)
_GetDesc = ctypes.WINFUNCTYPE(
    _HRESULT, ctypes.c_void_p, ctypes.POINTER(_DXGI_ADAPTER_DESC)
)


def _vtable(obj: int | ctypes.c_void_p, index: int):
    """Return a callable for vtable slot `index` of COM object pointer `obj`."""
    ptr = int(ctypes.cast(obj, ctypes.c_void_p).value or 0)
    table = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    return ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p))[index]


@dataclass(slots=True)
class GpuAdapterInfo:
    name: str
    vendor: str
    vendor_id: int
    total_bytes: int  # DedicatedVideoMemory (real VRAM)
    shared_total_bytes: int  # SharedSystemMemory (system RAM the GPU can use)
    luid_key: str  # "luid_0xHHHHHHHH_0xLLLLLLLL" — joins perf counters

    @property
    def is_software(self) -> bool:
        # Microsoft Basic Render Driver / WARP — not a real GPU.
        return self.vendor_id == 0x1414 or "Microsoft Basic" in self.name


def _luid_key(low: int, high: int) -> str:
    """Build the LUID key as Windows formats it in GPU perf-counter instance
    names: `luid_0x{HighPart:08x}_0x{LowPart:08x}`."""
    return f"luid_0x{high & 0xFFFFFFFF:08x}_0x{low & 0xFFFFFFFF:08x}"


def enumerate_adapters() -> list[GpuAdapterInfo]:
    """Enumerate real hardware GPU adapters (AMD/NVIDIA/Intel).

    Software adapters (Microsoft Basic Render Driver) are skipped.
    """
    _ensure_com()
    factory = ctypes.c_void_p()
    hr = _dxgi.CreateDXGIFactory(ctypes.byref(_IID_IDXGIFactory), ctypes.byref(factory))
    if hr != 0 or not factory:
        return []

    try:
        enum = _EnumAdapters(_vtable(factory, 7))

        adapters: list[GpuAdapterInfo] = []
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            hr = enum(factory, index, ctypes.byref(adapter))
            if hr != 0 or not adapter:
                # S_OK = 0; DXGI_ERROR_NOT_FOUND (= 0x887A0002 & 0xFFFFFFFF)
                # shows up negative; treat any non-zero as end of list.
                break
            try:
                desc = _DXGI_ADAPTER_DESC()
                hr = -1
                # GetDesc's vtable slot varies by DXGI interface version across
                # builds; probe the likely slots and take the first that fills
                # the description. (Empirically slot 8 on this box.)
                for slot in (8, 7, 9):
                    get_desc = _GetDesc(_vtable(adapter, slot))
                    hr = get_desc(adapter, ctypes.byref(desc))
                    if hr == 0 and desc.Description:
                        break
                if hr == 0 and desc.Description:
                    info = GpuAdapterInfo(
                        name=desc.Description,
                        vendor=_VENDORS.get(desc.VendorId, "Unknown"),
                        vendor_id=desc.VendorId,
                        total_bytes=int(desc.DedicatedVideoMemory),
                        shared_total_bytes=int(desc.SharedSystemMemory),
                        luid_key=_luid_key(
                            desc.AdapterLuid.LowPart, desc.AdapterLuid.HighPart
                        ),
                    )
                    if not info.is_software:
                        adapters.append(info)
            finally:
                _Release(_vtable(adapter, 2))(adapter)
            index += 1
        return adapters
    finally:
        _Release(_vtable(factory, 2))(factory)
