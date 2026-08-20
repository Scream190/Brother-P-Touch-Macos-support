"""Geometric transforms (rotate/mirror) for CUPS raster page content.

macOS's cgpdftoraster applies its own internal rotation heuristic for
narrow/tall PageSize geometries (like continuous label tape) -- observed
on real hardware as "PreferredRotation = -90" in its debug log, and
confirmed on a printed label to come out both rotated *and* mirrored
relative to the intended reading direction. A combined
rotate-90-and-mirror is exactly what a simple transpose (swap rows/
columns) produces, which is the leading hypothesis for why this happens,
but the exact composition (which of the 4 rotations, with or without an
extra mirror) needs to be confirmed empirically against the real printer
-- hence every combination being exposed as an independent, cheap-to-try
print option (see ppd's *ImageRotate / *ImageMirror) rather than betting
everything on one guess.

Rotation is defined clockwise, as seen looking at the label with its
leading (first-printed) edge at the top.
"""

from __future__ import annotations

from typing import List, Tuple

from .protocol import pack_bitmap_row


def _unpack_row(row: bytes, width: int) -> List[int]:
    bits = []
    for byte in row:
        for i in range(8):
            bits.append((byte >> (7 - i)) & 1)
    return bits[:width]


def transform_page(rows: List[bytes], width: int, *, rotate: int = 0, mirror: bool = False) -> Tuple[List[bytes], int]:
    """Apply an optional horizontal mirror, then a clockwise rotation.

    ``rows`` are the original CUPS raster rows (MSB-first, ``width`` bits
    of real content each, byte-aligned). ``rotate`` must be 0, 90, 180, or
    270. Returns ``(new_rows, new_width)`` -- rotation by 90 or 270
    swaps the width/height roles, so the caller needs the new width to
    know how to interpret/pad the result (e.g. for tape-width matching).
    """
    if rotate not in (0, 90, 180, 270):
        raise ValueError(f"rotate must be 0, 90, 180, or 270, got {rotate}")

    height = len(rows)
    grid = [_unpack_row(row, width) for row in rows]

    if mirror:
        grid = [r[::-1] for r in grid]

    if rotate == 0:
        new_grid = grid
        new_width = width
    elif rotate == 180:
        new_grid = [r[::-1] for r in reversed(grid)]
        new_width = width
    elif rotate == 90:
        new_width = height
        new_grid = [[0] * new_width for _ in range(width)]
        for y in range(height):
            for x in range(width):
                new_grid[x][height - 1 - y] = grid[y][x]
    else:  # 270
        new_width = height
        new_grid = [[0] * new_width for _ in range(width)]
        for y in range(height):
            for x in range(width):
                new_grid[width - 1 - x][y] = grid[y][x]

    n_bytes = -(-new_width // 8)  # ceil div
    new_rows = [pack_bitmap_row(r, n_bytes) for r in new_grid]
    return new_rows, new_width
