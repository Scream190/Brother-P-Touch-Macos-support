"""Test patterns for bringing up the raster protocol against real hardware.

These are deliberately geometric (no font rendering needed) because simple
shapes are the most reliable way to catch bit-packing/centering bugs by eye:

- ``diagonal`` immediately reveals any bit-order, byte-order, or off-by-one
  error as a broken/discontinuous line instead of a straight one.
- ``ruler`` prints solid vertical lines at fixed dot intervals plus lines
  exactly at the tape's left/right edges, so you can visually confirm the
  active print area is centered and the width matches what was requested.
- ``border``/``checkerboard``/``stripes``/``solid`` are simpler sanity
  checks for coverage, clipping, and line-to-line handling.

Each function returns a list of raster lines (bytes, ``media.print_bytes``
long each) ready to hand to ``RasterJobBuilder.add_lines``.
"""

from __future__ import annotations

from typing import List

from .media import MediaSpec
from .protocol import pack_bitmap_row

PATTERNS = (
    "solid",
    "stripes",
    "checkerboard",
    "diagonal",
    "border",
    "ruler",
)


def _row(media: MediaSpec, black_columns) -> bytes:
    pixels = [1 if x in black_columns else 0 for x in range(media.print_dots)]
    return pack_bitmap_row(pixels, media.print_bytes)


def solid(media: MediaSpec, length: int) -> List[bytes]:
    row = _row(media, set(range(media.print_dots)))
    return [row] * length


def stripes(media: MediaSpec, length: int, period: int = 4) -> List[bytes]:
    black = _row(media, set(range(media.print_dots)))
    blank = _row(media, set())
    return [black if (y // period) % 2 == 0 else blank for y in range(length)]


def checkerboard(media: MediaSpec, length: int, cell: int = 8) -> List[bytes]:
    lines = []
    for y in range(length):
        cols = {x for x in range(media.print_dots) if ((x // cell) + (y // cell)) % 2 == 0}
        lines.append(_row(media, cols))
    return lines


def diagonal(media: MediaSpec, length: int, thickness: int = 2) -> List[bytes]:
    lines = []
    max_x = media.print_dots - 1
    for y in range(length):
        center = round(y * max_x / max(1, length - 1))
        cols = set(range(max(0, center - thickness), min(media.print_dots, center + thickness + 1)))
        lines.append(_row(media, cols))
    return lines


def border(media: MediaSpec, length: int, thickness: int = 2) -> List[bytes]:
    lines = []
    for y in range(length):
        if y < thickness or y >= length - thickness:
            cols = set(range(media.print_dots))
        else:
            cols = set(range(0, thickness)) | set(range(media.print_dots - thickness, media.print_dots))
        lines.append(_row(media, cols))
    return lines


def ruler(media: MediaSpec, length: int, major: int = 50, thickness: int = 2) -> List[bytes]:
    cols = set()
    for x in range(0, media.print_dots, major):
        cols |= set(range(x, min(media.print_dots, x + thickness)))
    # Always mark the exact left/right edges of the active print area.
    cols |= set(range(0, thickness))
    cols |= set(range(max(0, media.print_dots - thickness), media.print_dots))
    row = _row(media, cols)
    return [row] * length


_GENERATORS = {
    "solid": solid,
    "stripes": stripes,
    "checkerboard": checkerboard,
    "diagonal": diagonal,
    "border": border,
    "ruler": ruler,
}


def generate(name: str, media: MediaSpec, length: int) -> List[bytes]:
    try:
        func = _GENERATORS[name]
    except KeyError as exc:
        raise ValueError(f"unknown pattern {name!r}; valid options: {', '.join(PATTERNS)}") from exc
    return func(media, length)
