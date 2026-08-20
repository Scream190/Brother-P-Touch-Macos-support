"""Minimal reader for the CUPS Raster page-stream format.

Only the subset needed by this driver is implemented: 1-bit-per-pixel,
uncompressed rows, RaS2/RaS3 sync words (the ones cups-filters' own
pdftoraster/pstoraster/rastertopwg emit by default). Field layout is
transcribed verbatim from ``cups_page_header2_t`` in Apple/OpenPrinting
CUPS's ``cups/raster.h``, field by field with explicit names, rather than
hand-counted repeat groups -- an earlier version of this file used
``"I" * n`` groups sized from a written-out description of the struct and
got the total header length wrong (it stopped at ``cupsRowStep`` and
omitted the entire "Version 2 Dictionary Values" tail --
cupsNumColors..cupsPageSizeName), which both RaS2 and RaS3 streams
actually include on the wire. That silently misaligned every read after
the header, confirmed via a real print job on hardware
(``cupsBitsPerPixel`` came back 0 instead of 1). Explicit per-field names
make that class of bug structurally harder to reintroduce.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Iterator, List

SYNC_WORDS = {b"RaS2", b"RaS3", b"2SaR", b"3SaR"}  # last two: byte-swapped variant

# Verbatim field order from cups_page_header2_t (cups/raster.h). Every
# member is listed explicitly, with array members expanded into one named
# entry per element (except the two pure-string blobs, cupsString and the
# four MediaClass-style char[64] fields, which are read as a single bytes
# object each since we never need to inspect their contents).
_FIELDS = (
    [
        ("MediaClass", "64s"), ("MediaColor", "64s"), ("MediaType", "64s"), ("OutputType", "64s"),
        ("AdvanceDistance", "I"), ("AdvanceMedia", "I"), ("Collate", "I"), ("CutMedia", "I"), ("Duplex", "I"),
        ("HWResolution0", "I"), ("HWResolution1", "I"),
        ("ImagingBoundingBox0", "I"), ("ImagingBoundingBox1", "I"),
        ("ImagingBoundingBox2", "I"), ("ImagingBoundingBox3", "I"),
        ("InsertSheet", "I"), ("Jog", "I"), ("LeadingEdge", "I"),
        ("Margins0", "I"), ("Margins1", "I"),
        ("ManualFeed", "I"), ("MediaPosition", "I"), ("MediaWeight", "I"),
        ("MirrorPrint", "I"), ("NegativePrint", "I"), ("NumCopies", "I"), ("Orientation", "I"), ("OutputFaceUp", "I"),
        ("PageSize0", "I"), ("PageSize1", "I"),
        ("Separations", "I"), ("TraySwitch", "I"), ("Tumble", "I"),
        ("cupsWidth", "I"), ("cupsHeight", "I"), ("cupsMediaType", "I"),
        ("cupsBitsPerColor", "I"), ("cupsBitsPerPixel", "I"), ("cupsBytesPerLine", "I"),
        ("cupsColorOrder", "I"), ("cupsColorSpace", "I"),
        ("cupsCompression", "I"), ("cupsRowCount", "I"), ("cupsRowFeed", "I"), ("cupsRowStep", "I"),
        ("cupsNumColors", "I"),
        ("cupsBorderlessScalingFactor", "f"),
        ("cupsPageSize0", "f"), ("cupsPageSize1", "f"),
        ("cupsImagingBBox0", "f"), ("cupsImagingBBox1", "f"), ("cupsImagingBBox2", "f"), ("cupsImagingBBox3", "f"),
    ]
    + [(f"cupsInteger{i}", "I") for i in range(16)]
    + [(f"cupsReal{i}", "f") for i in range(16)]
    + [("cupsString", "1024s")]
    + [("cupsMarkerType", "64s"), ("cupsRenderingIntent", "64s"), ("cupsPageSizeName", "64s")]
)

_HEADER_FMT = "<" + "".join(tok for _name, tok in _FIELDS)
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_FIELD_NAMES = [name for name, _tok in _FIELDS]


class RasterFormatError(Exception):
    pass


@dataclass
class RasterPage:
    width: int
    height: int
    bits_per_pixel: int
    bytes_per_line: int
    hw_resolution: tuple  # (dpi_x, dpi_y), as actually used by the upstream
                           # rasterizer -- don't assume a fixed DPI (e.g. a
                           # PPD default not taking effect can silently
                           # change this; real hardware test saw 100dpi
                           # despite the PPD declaring 180dpi as the only
                           # option).
    rows: List[bytes]


def _read_exact(f: BinaryIO, n: int) -> bytes:
    """Read exactly ``n`` bytes, looping over short reads.

    ``f.read(n)`` only reliably returns exactly ``n`` bytes for regular
    files. For a pipe -- which is what stdin actually is when cupsd runs
    filters as a live pipeline, as opposed to a filter run by hand against
    a regular file -- a single read() call can return fewer bytes even
    when more are still coming, and a naive single-shot read wrongly
    treats that as EOF/corruption.
    """
    data = _read_full_or_none(f, n)
    if data is None or len(data) != n:
        got = 0 if data is None else len(data)
        raise RasterFormatError(f"unexpected EOF: wanted {n} bytes, got {got}")
    return data


def _read_full_or_none(f: BinaryIO, n: int):
    """Like _read_exact, but returns None (instead of raising) if the
    stream ends before any bytes are read at all -- i.e. a legitimate
    "nothing more to read" EOF at a boundary where that's expected (start
    of stream, between pages), as opposed to ending partway through.
    """
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = f.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if not chunks:
        return None
    return b"".join(chunks)


def read_pages(f: BinaryIO) -> Iterator[RasterPage]:
    sync = _read_full_or_none(f, 4)
    if sync not in SYNC_WORDS:
        raise RasterFormatError(f"not a CUPS raster stream (bad sync word {sync!r})")

    while True:
        header_bytes = _read_full_or_none(f, _HEADER_SIZE)
        if header_bytes is None:
            return  # clean EOF between pages
        if len(header_bytes) != _HEADER_SIZE:
            raise RasterFormatError("truncated page header")

        values = struct.unpack(_HEADER_FMT, header_bytes)
        header = dict(zip(_FIELD_NAMES, values))

        cups_width = header["cupsWidth"]
        cups_height = header["cupsHeight"]
        cups_bits_per_pixel = header["cupsBitsPerPixel"]
        cups_bytes_per_line = header["cupsBytesPerLine"]
        cups_compression = header["cupsCompression"]
        hw_resolution = (header["HWResolution0"], header["HWResolution1"])

        if cups_compression:
            raise RasterFormatError(
                "compressed CUPS raster rows are not supported; ensure the "
                "PPD/filter chain produces uncompressed 1bpp raster"
            )
        if cups_bits_per_pixel != 1:
            raise RasterFormatError(
                f"expected 1 bit per pixel (monochrome), got {cups_bits_per_pixel}"
            )

        rows = [_read_exact(f, cups_bytes_per_line) for _ in range(cups_height)]
        yield RasterPage(
            width=cups_width,
            height=cups_height,
            bits_per_pixel=cups_bits_per_pixel,
            bytes_per_line=cups_bytes_per_line,
            hw_resolution=hw_resolution,
            rows=rows,
        )
