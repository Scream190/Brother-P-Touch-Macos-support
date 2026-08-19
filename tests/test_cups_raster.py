"""Unit tests for brother_ptraster.cups_raster.

Builds a synthetic, minimal CUPS Raster v2 stream in memory (rather than
depending on cups-filters being installed) to check the header field
offsets are being read correctly.
"""
import io
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.cups_raster import read_pages, _HEADER_FMT, _HEADER_SIZE

_FIELD_TOKENS = re.findall(r"\d*[sI]", _HEADER_FMT[1:])  # skip the "<" prefix


def _make_page_header(width, height, bytes_per_line, bits_per_pixel=1, compression=0):
    values = [b"" if tok.endswith("s") else 0 for tok in _FIELD_TOKENS]

    # Re-derive field positions the same way cups_raster.py does, and patch
    # in the values we actually care about for this test.
    values[-12] = width
    values[-11] = height
    values[-8] = bits_per_pixel
    values[-7] = bytes_per_line
    values[-4] = compression
    return struct.pack(_HEADER_FMT, *values)


def test_read_single_uncompressed_page():
    width, height, bpl = 128, 3, 16
    rows = [bytes([i % 256]) * bpl for i in range(height)]

    stream = io.BytesIO()
    stream.write(b"RaS2")
    stream.write(_make_page_header(width, height, bpl))
    for row in rows:
        stream.write(row)
    stream.seek(0)

    pages = list(read_pages(stream))
    assert len(pages) == 1
    page = pages[0]
    assert page.width == width
    assert page.height == height
    assert page.bytes_per_line == bpl
    assert page.rows == rows


def test_read_rejects_bad_sync_word():
    stream = io.BytesIO(b"NOPE" + b"\x00" * _HEADER_SIZE)
    try:
        list(read_pages(stream))
    except Exception as exc:
        assert "sync word" in str(exc)
    else:
        raise AssertionError("expected an error for a bad sync word")


def test_read_rejects_compressed_rows():
    stream = io.BytesIO()
    stream.write(b"RaS2")
    stream.write(_make_page_header(8, 1, 1, compression=1))
    stream.seek(0)
    try:
        list(read_pages(stream))
    except Exception as exc:
        assert "compressed" in str(exc)
    else:
        raise AssertionError("expected an error for compressed rows")
