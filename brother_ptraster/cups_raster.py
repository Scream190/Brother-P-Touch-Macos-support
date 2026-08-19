"""Minimal reader for the CUPS Raster page-stream format.

Only the subset needed by this driver is implemented: 1-bit-per-pixel,
uncompressed rows, version 2/3 sync words. This is the format CUPS's own
``pdftoraster``/``pstoraster``/``rastertopwg`` filters emit by default when
the PPD declares a 1-bit ``ColorModel`` (as ``ppd/Brother_PT-P710BT.ppd``
does), so it covers the print path this driver actually uses.

Format reference: the CUPS Raster page-header layout is a stable, publicly
documented C struct (``cups_page_header2_t`` in ``cups/raster.h``). Field
offsets/sizes below mirror that struct. If a future cups-filters version
changes the on-disk layout, ``read_pages`` will raise ``RasterFormatError``
rather than silently mis-parsing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Iterator, List

SYNC_WORDS = {b"RaS2", b"RaS3", b"2SaR", b"3SaR"}  # last two: byte-swapped variant

# cups_page_header2_t (relevant prefix): 4-byte sync handled separately, then
#   char MediaClass[64], MediaColor[64], MediaType[64], OutputType[64]      (256)
#   unsigned AdvanceDistance, AdvanceMedia, Collate                         (12)
#   unsigned CutMedia, Duplex                                               (8)
#   unsigned HWResolution[2]                                                (8)
#   unsigned ImagingBoundingBox[4]                                         (16)
#   unsigned InsertSheet, Jog, LeadingEdge                                 (12)
#   unsigned Margins[2]                                                     (8)
#   unsigned ManualFeed                                                     (4)
#   unsigned MediaPosition, MediaWeight                                     (8)
#   unsigned MirrorPrint, NegativePrint, NumCopies, Orientation             (16)
#   unsigned OutputFaceUp                                                   (4)
#   unsigned PageSize[2]                                                    (8)
#   unsigned Separations, TraySwitch, Tumble                               (12)
#   unsigned cupsWidth, cupsHeight                                          (8)
#   unsigned cupsMediaType                                                  (4)
#   unsigned cupsBitsPerColor, cupsBitsPerPixel, cupsBytesPerLine           (12)
#   unsigned cupsColorOrder, cupsColorSpace                                 (8)
#   unsigned cupsCompression, cupsRowCount, cupsRowFeed, cupsRowStep        (16)
# (further v2/v3 fields follow but aren't needed here)
_HEADER_FMT = "<" + "64s" * 4 + "I" * 3 + "I" * 2 + "I" * 2 + "I" * 4 + "I" * 3 + "I" * 2 + "I" + "I" * 2 + "I" * 4 + "I" + "I" * 2 + "I" * 3 + "I" * 2 + "I" + "I" * 3 + "I" * 2 + "I" * 4
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class RasterFormatError(Exception):
    pass


@dataclass
class RasterPage:
    width: int
    height: int
    bits_per_pixel: int
    bytes_per_line: int
    rows: List[bytes]


def _read_exact(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise RasterFormatError(f"unexpected EOF: wanted {n} bytes, got {len(data)}")
    return data


def read_pages(f: BinaryIO) -> Iterator[RasterPage]:
    sync = f.read(4)
    if sync not in SYNC_WORDS:
        raise RasterFormatError(f"not a CUPS raster stream (bad sync word {sync!r})")

    first = True
    while True:
        if not first:
            # Only the very first page is preceded by the file-level sync
            # word; subsequent pages' headers follow immediately.
            pass
        first = False

        header_bytes = f.read(_HEADER_SIZE)
        if not header_bytes:
            return  # clean EOF between pages
        if len(header_bytes) != _HEADER_SIZE:
            raise RasterFormatError("truncated page header")

        fields = struct.unpack(_HEADER_FMT, header_bytes)
        # Field order per the struct layout comment above. The last 12
        # unsigned-int fields are, in order: cupsWidth, cupsHeight,
        # cupsMediaType, cupsBitsPerColor, cupsBitsPerPixel,
        # cupsBytesPerLine, cupsColorOrder, cupsColorSpace,
        # cupsCompression, cupsRowCount, cupsRowFeed, cupsRowStep.
        cups_width = fields[-12]
        cups_height = fields[-11]
        cups_bits_per_pixel = fields[-8]
        cups_bytes_per_line = fields[-7]
        cups_compression = fields[-4]

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
            rows=rows,
        )
