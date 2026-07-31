"""Network / port inspector (phase 3): lists listening + established sockets
and per-NIC byte-rate counters via psutil.

All public functions degrade gracefully: any failure returns an empty list
so the sampler loop, UI, and API never crash on a permissions or transient
psutil error.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

import psutil


@dataclass(slots=True)
class ConnRow:
    pid: int = 0
    name: str = ""
    proto: str = ""
    family: str = ""
    local_addr: str = ""
    local_port: int = 0
    remote_addr: str = ""
    remote_port: int = 0
    status: str = ""


@dataclass(slots=True)
class NetInterface:
    name: str = ""
    addresses: list[str] = field(default_factory=list)
    is_up: bool = True
    bytes_sent: int = 0
    bytes_recv: int = 0
    send_bps: float = 0.0
    recv_bps: float = 0.0


# Module-level rate state for interface_stats(). Persisted across calls so a
# second invocation can compute a bytes/sec delta from the first.
_prev_io: dict[str, tuple[int, int]] = {}
_prev_ts: float = 0.0


_PROTO_MAP: dict[int, str] = {
    int(socket.SOCK_STREAM): "TCP",
    int(socket.SOCK_DGRAM): "UDP",
}

_FAMILY_MAP: dict[int, str] = {
    int(socket.AF_INET): "IPv4",
    int(socket.AF_INET6): "IPv6",
}


def _addr_ip(addr: object) -> str:
    """Pull the IP string out of a psutil address (namedtuple or 2-tuple)."""
    if not addr:
        return ""
    ip = getattr(addr, "ip", None)
    if ip is None and isinstance(addr, tuple) and len(addr) >= 1:
        ip = addr[0]
    return str(ip or "")


def _addr_port(addr: object) -> int:
    """Pull the port int out of a psutil address (namedtuple or 2-tuple)."""
    if not addr:
        return 0
    port = getattr(addr, "port", None)
    if port is None and isinstance(addr, tuple) and len(addr) >= 2:
        port = addr[1]
    try:
        return int(port or 0)
    except Exception:
        return 0


def _proc_name(pid: int) -> str:
    """Resolve a pid to a process name; "" when inaccessible (e.g. pid 0)."""
    if not pid:
        return ""
    try:
        return psutil.Process(pid).name() or ""
    except Exception:
        return ""


def sample_connections(kind: str = "inet") -> list[ConnRow]:
    """Snapshot all network connections of the given address family kind.

    Seeing every pid requires admin; non-elevated callers simply see fewer
    rows (psutil raises AccessDenied for the system-owned sockets, which we
    swallow per-row so partial results still come through).
    """
    rows: list[ConnRow] = []
    try:
        conns = psutil.net_connections(kind=kind)
    except Exception:
        return rows
    for conn in conns:
        try:
            pid = int(getattr(conn, "pid", 0) or 0)
            rows.append(
                ConnRow(
                    pid=pid,
                    name=_proc_name(pid),
                    proto=_PROTO_MAP.get(int(getattr(conn, "type", 0) or 0), ""),
                    family=_FAMILY_MAP.get(int(getattr(conn, "family", 0) or 0), ""),
                    local_addr=_addr_ip(getattr(conn, "laddr", None)),
                    local_port=_addr_port(getattr(conn, "laddr", None)),
                    remote_addr=_addr_ip(getattr(conn, "raddr", None)),
                    remote_port=_addr_port(getattr(conn, "raddr", None)),
                    status=str(getattr(conn, "status", "") or ""),
                )
            )
        except Exception:
            continue
    return rows


def listening_ports(kind: str = "inet") -> list[ConnRow]:
    """Listening TCP sockets plus bound (connectionless) UDP ports."""
    out: list[ConnRow] = []
    for c in sample_connections(kind):
        if c.status == "LISTEN":
            out.append(c)
        elif c.proto == "UDP" and not c.remote_port and c.local_port:
            out.append(c)
    return out


def interface_stats() -> list[NetInterface]:
    """Per-NIC addresses + cumulative byte counts + instantaneous bps rates.

    send_bps / recv_bps are computed from the delta vs the previous call's
    counters (stored in module globals). The first call always yields 0.0
    rates since there is no prior sample to diff against.
    """
    global _prev_io, _prev_ts
    out: list[NetInterface] = []
    try:
        per_nic = psutil.net_io_counters(pernic=True)
    except Exception:
        return out
    try:
        addrs_all = psutil.net_if_addrs()
    except Exception:
        addrs_all = {}
    try:
        stats_all = psutil.net_if_stats()
    except Exception:
        stats_all = {}

    now = time.monotonic()
    elapsed = now - _prev_ts if _prev_ts > 0.0 else 0.0

    for name, io in per_nic.items():
        sent = int(getattr(io, "bytes_sent", 0) or 0)
        recv = int(getattr(io, "bytes_recv", 0) or 0)

        send_bps = 0.0
        recv_bps = 0.0
        if elapsed > 0.0:
            prev = _prev_io.get(name)
            if prev is not None:
                ps, pr = prev
                send_bps = max(0.0, (sent - ps) / elapsed)
                recv_bps = max(0.0, (recv - pr) / elapsed)

        addrs: list[str] = []
        for snic in addrs_all.get(name, []):
            fam = getattr(snic, "family", 0)
            if fam in (socket.AF_INET, socket.AF_INET6):
                a = getattr(snic, "address", "")
                if a:
                    addrs.append(str(a))

        is_up = True
        st = stats_all.get(name)
        if st is not None:
            is_up = bool(getattr(st, "isup", True))

        out.append(
            NetInterface(
                name=name,
                addresses=addrs,
                is_up=is_up,
                bytes_sent=sent,
                bytes_recv=recv,
                send_bps=send_bps,
                recv_bps=recv_bps,
            )
        )

    _prev_io = {
        n: (int(getattr(io, "bytes_sent", 0) or 0), int(getattr(io, "bytes_recv", 0) or 0))
        for n, io in per_nic.items()
    }
    _prev_ts = now
    return out
