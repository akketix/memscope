"""Headless CLI launcher for the MemScope telemetry API.

Runs the FastAPI app from ``memscope.api.server`` under uvicorn. No Qt
dependency — safe to run from the project venv in a plain terminal.

Usage:
    python -m memscope.serve
    python -m memscope.serve --host 0.0.0.0 --port 8765 --log-level info
"""

from __future__ import annotations

import argparse


def main(host: str = "127.0.0.1", port: int = 8765) -> int:
    """Start the telemetry API server and block until it stops.

    Returns 0 on a clean exit. uvicorn.run() raises SystemExit on parse
    errors, which propagates to the caller.
    """
    import uvicorn

    uvicorn.run(
        "memscope.api.server:app",
        host=host,
        port=port,
        log_level="info",
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memscope.serve",
        description="Headless launcher for the MemScope telemetry API.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for the API server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port for the API server (default: 8765).",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        help="uvicorn log level: debug|info|warning|error|critical (default: info).",
    )
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(main(host=args.host, port=args.port))
