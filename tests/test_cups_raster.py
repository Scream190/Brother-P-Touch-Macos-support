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


class _ChunkyPipe:
    """A file-like object that hands back at most 1 byte per read() call,
    like a real OS pipe can, to catch code that assumes a single read()
    returns everything requested. This reproduces the real-world failure:
    cupsd pipes filter stdout/stdin together as live pipes between
    concurrently-running processes, unlike a filter run by hand against a
    regular (buffered, single-read-satisfies-everything) file.
    """

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n):
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + 1]
        self._pos += len(chunk)
        return chunk


def test_read_pages_handles_short_reads_from_a_pipe():
    width, height, bpl = 128, 2, 16
    rows = [bytes([0xAA]) * bpl, bytes([0x55]) * bpl]

    stream = io.BytesIO()
    stream.write(b"RaS2")
    stream.write(_make_page_header(width, height, bpl))
    for row in rows:
        stream.write(row)

    pipe = _ChunkyPipe(stream.getvalue())
    pages = list(read_pages(pipe))
    assert len(pages) == 1
    assert pages[0].rows == rows


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
