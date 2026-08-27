"""Unit tests for brother_ptraster.filter_core -- the logic shared by all
three per-model CUPS filter scripts (rastertoptp710bt/rastertoptp700/
rastertoptp750w). Exercises it directly (not via subprocess) with a
synthetic CUPS raster stream, so a regression here fails fast without
needing any of the three filter scripts or real hardware.
"""
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.cups_raster import _FIELDS, _HEADER_FMT
from brother_ptraster.filter_core import run
from brother_ptraster.media import DPI, build_media_table
from brother_ptraster.protocol import pack_bitmap_row


def _build_raster(width_dots: int, height_dots: int, fill: int = 0xFF) -> bytes:
    """A minimal synthetic CUPS raster stream: one page, uncommpressed
    1bpp, filled with ``fill`` for every content byte. Mirrors the field
    values a real cgpdftoraster job actually produces (see
    tests/test_cups_raster.py for the header layout this matches).
    """
    bytes_per_line = -(-width_dots // 8)
    values = []
    for name, tok in _FIELDS:
        if name == "cupsWidth":
            values.append(width_dots)
        elif name == "cupsHeight":
            values.append(height_dots)
        elif name in ("HWResolution0", "HWResolution1"):
            values.append(DPI)
        elif name == "cupsBitsPerColor":
            values.append(1)
        elif name == "cupsBitsPerPixel":
            values.append(1)
        elif name == "cupsBytesPerLine":
            values.append(bytes_per_line)
        elif name == "cupsColorSpace":
            values.append(3)
        elif name == "cupsCompression":
            values.append(0)
        elif tok.endswith("s"):
            values.append(b"")
        elif tok == "f":
            values.append(0.0)
        else:
            values.append(0)
    header = struct.pack(_HEADER_FMT, *values)
    rows = bytes([fill]) * bytes_per_line * height_dots
    return b"RaS2" + header + rows


def _run(media_table, margin_mm, raster_bytes, options="media=mm12"):
    argv = ["rastertoptest", "1", "user", "title", "1", options]
    stdin = io.BytesIO(raster_bytes)
    stdout = io.BytesIO()
    rc = run("rastertoptest", media_table, margin_mm, argv, stdin, stdout)
    return rc, stdout.getvalue()


def test_run_succeeds_for_each_models_own_media_table():
    # The three real filter scripts each build their own table via
    # build_media_table(their_trim) -- this confirms run() works
    # regardless of which table/trim is passed, not just the P710BT's.
    for trim in (0, 3, -2):
        table = build_media_table(trim)
        raster = _build_raster(width_dots=300, height_dots=85)  # ~12mm tape, 300 dots long
        rc, out = _run(table, margin_mm=5.0, raster_bytes=raster)
        assert rc == 0
        assert len(out) > 0


def test_run_rejects_wrong_resolution():
    bytes_per_line = -(-85 // 8)
    header_values = []
    for name, tok in _FIELDS:
        if name == "cupsWidth":
            header_values.append(300)
        elif name == "cupsHeight":
            header_values.append(85)
        elif name in ("HWResolution0", "HWResolution1"):
            header_values.append(100)  # wrong -- driver only supports 180dpi
        elif name == "cupsBitsPerColor":
            header_values.append(1)
        elif name == "cupsBitsPerPixel":
            header_values.append(1)
        elif name == "cupsBytesPerLine":
            header_values.append(bytes_per_line)
        elif name == "cupsColorSpace":
            header_values.append(3)
        elif name == "cupsCompression":
            header_values.append(0)
        elif tok.endswith("s"):
            header_values.append(b"")
        elif tok == "f":
            header_values.append(0.0)
        else:
            header_values.append(0)
    raster = b"RaS2" + struct.pack(_HEADER_FMT, *header_values) + bytes([0xFF]) * bytes_per_line * 300

    table = build_media_table()
    rc, out = _run(table, margin_mm=5.0, raster_bytes=raster)
    assert rc == 1
    assert out == b""


def test_run_rejects_empty_input():
    table = build_media_table()
    rc, out = _run(table, margin_mm=5.0, raster_bytes=b"")
    assert rc == 1
    assert out == b""


def test_run_honors_auto_length_off():
    # page.width (100 dots) becomes the LENGTH axis (line count) after the
    # mandatory transpose in filter_core -- so a bit pattern of 50 blank +
    # 20 ink + 30 blank bits *within each pre-transpose row* becomes 50
    # blank + 20 ink + 30 blank *lines* post-transpose. AutoLength should
    # trim the 80 blank lines down to just the 20 ink ones.
    width_dots, height_dots = 100, 85
    bytes_per_line = -(-width_dots // 8)
    row_bits = [0] * 50 + [1] * 20 + [0] * 30
    row = pack_bitmap_row(row_bits, bytes_per_line)

    values = []
    for name, tok in _FIELDS:
        if name == "cupsWidth":
            values.append(width_dots)
        elif name == "cupsHeight":
            values.append(height_dots)
        elif name in ("HWResolution0", "HWResolution1"):
            values.append(DPI)
        elif name == "cupsBitsPerColor":
            values.append(1)
        elif name == "cupsBitsPerPixel":
            values.append(1)
        elif name == "cupsBytesPerLine":
            values.append(bytes_per_line)
        elif name == "cupsColorSpace":
            values.append(3)
        elif name == "cupsCompression":
            values.append(0)
        elif tok.endswith("s"):
            values.append(b"")
        elif tok == "f":
            values.append(0.0)
        else:
            values.append(0)
    header = struct.pack(_HEADER_FMT, *values)
    raster = b"RaS2" + header + row * height_dots

    table = build_media_table()
    rc_on, out_on = _run(table, margin_mm=5.0, raster_bytes=raster, options="media=mm12 AutoLength=True")
    rc_off, out_off = _run(table, margin_mm=5.0, raster_bytes=raster, options="media=mm12 AutoLength=False")
    assert rc_on == 0 and rc_off == 0
    assert len(out_on) < len(out_off)
