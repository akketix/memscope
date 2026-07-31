"""Generate the MemScope application icon (a pressure-gauge motif).

Output: memscope/assets/icon.ico (multi-size) and icon.png (256).
Run:  memscope/.venv/Scripts/python.exe memscope/assets/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
BG = (15, 22, 32, 255)  # dark navy
BG_BORDER = (40, 56, 76, 255)
GREEN = (58, 125, 58, 255)
AMBER = (217, 164, 65, 255)
RED = (217, 83, 79, 255)
NEEDLE = (235, 238, 245, 255)
HUB = (235, 238, 245, 255)
HUB_DARK = (20, 28, 40, 255)


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _arc_segment(draw, cx, cy, r, start_deg, end_deg, color, width):
    # PIL arcs draw 0 at 3 o'clock, going counterclockwise; we use the gauge
    # opening at the bottom, sweeping 270 degrees from 225 -> -45 (i.e. 315).
    bbox = [cx - r, cy - r, cx + r, cy + r]
    draw.arc(bbox, start_deg, end_deg, fill=color, width=width)


def render(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(2, size // 32)
    _rounded(
        draw,
        [pad, pad, size - pad, size - pad],
        radius=size // 6,
        fill=BG,
        outline=BG_BORDER,
        width=max(1, size // 128),
    )

    cx = cy = size // 2
    r = int(size * 0.34)
    lw = max(3, size // 22)

    # Gauge sweeps 270 deg, opening at the bottom.
    # Segment map (start, end) in PIL degrees (CCW, 0 = east):
    #   green 135 -> 45, amber 45 -> -15, red -15 -> -45 (== 315)
    # We express as three arcs.
    _arc_segment(draw, cx, cy, r, 135, 225, GREEN, lw)  # left/lower-left
    _arc_segment(draw, cx, cy, r, 45, 135, AMBER, lw)  # top
    _arc_segment(draw, cx, cy, r, 315, 45, RED, lw)  # right (wraps via 315->360)

    # Needle pointing into the green zone (~22% load).
    angle = math.radians(225 - 22 * 2.7)  # sweep within 270 deg
    nx = cx + int(r * 0.82 * math.cos(angle))
    ny = cy - int(r * 0.82 * math.sin(angle))
    draw.line([cx, cy, nx, ny], fill=NEEDLE, width=max(2, size // 64))
    hub = max(3, size // 40)
    draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=HUB)
    draw.ellipse(
        [cx - hub // 2, cy - hub // 2, cx + hub // 2, cy + hub // 2], fill=HUB_DARK
    )
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    big = render(256)
    big.save(OUT / "icon.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    # Single high-res image + sizes= lets Pillow auto-resize into one ICO.
    big.save(OUT / "icon.ico", format="ICO", sizes=sizes)
    print("wrote", OUT / "icon.ico", "and", OUT / "icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
