"""Unit tests for brother_ptraster.cups_raster.

Builds a synthetic, minimal CUPS Raster v2 stream in memory (rather than
depending on cups-filters being installed) to check the header field
offsets are being read correctly.

_make_page_header sets fields BY NAME against the real _FIELDS/_FIELD_NAMES
that cups_raster.py itself derives from the verbatim cups_page_header2_t
layout -- deliberately not a second, independently-hand-counted offset
scheme. An earlier version of both this file and cups_raster.py computed
matching-but-wrong offsets via hand-counted repeat groups, which let this
test pass while failing against a real print job (cupsBitsPerPixel came
back 0 instead of 1). Building test headers from the same authoritative
field list the parser uses is what actually would have failed loudly.
"""
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.cups_raster import read_pages, _HEADER_FMT, _HEADER_SIZE, _FIELDS


def _make_page_header(width, height, bytes_per_line, bits_per_pixel=1, compression=0):
    overrides = {
        "cupsWidth": width,
        "cupsHeight": height,
        "cupsBytesPerLine": bytes_per_line,
        "cupsBitsPerPixel": bits_per_pixel,
        "cupsCompression": compression,
    }
    values = [overrides.get(name, (b"" if tok.endswith("s") else 0)) for name, tok in _FIELDS]
    return struct.pack(_HEADER_FMT, *values)


def test_header_size_matches_real_cups_page_header2_t():
    # sizeof(cups_page_header2_t) on a real system (verified against
    # Apple/OpenPrinting CUPS's cups/raster.h): 4x64-byte strings + 81
    # 4-byte int/float fields + 1024-byte cupsString blob + 3x64-byte
    # trailing strings = 1796 bytes. A hard-coded expected value here
    # means a miscounted field list fails loudly instead of just being
    # internally self-consistent with a same-shaped bug in this test file.
    assert _HEADER_SIZE == 1796


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


def test_read_matches_real_cgpdftoraster_job_values():
    # Exact header field values observed in /var/log/cups/error_log for a
    # real print job on real hardware (cgpdftoraster's own debug output):
    # cupsWidth=47, cupsHeight=157, cupsBitsPerColor=1, cupsBitsPerPixel=1,
    # cupsBytesPerLine=6. The old (buggy) header-size handling read
    # cupsBitsPerPixel back as 0 against this exact shape of input.
    width, height, bpl = 47, 157, 6
    rows = [bytes([0x00]) * bpl for _ in range(height)]

    stream = io.BytesIO()
    stream.write(b"RaS3")
    stream.write(_make_page_header(width, height, bpl, bits_per_pixel=1))
    for row in rows:
        stream.write(row)
    stream.seek(0)

    pages = list(read_pages(stream))
    assert len(pages) == 1
    assert pages[0].width == 47
    assert pages[0].height == 157
    assert pages[0].bits_per_pixel == 1
    assert pages[0].bytes_per_line == 6


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
