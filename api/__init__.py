"""MemScope local Telemetry API (FastAPI + uvicorn).

Exposes a combined RAM/VRAM/hardware snapshot plus best-effort actions to
local agents via a JSON HTTP API. A background daemon thread samples every
``DEFAULT_INTERVAL_S`` seconds so endpoints return fresh data cheaply.
"""

__all__: list[str] = []
