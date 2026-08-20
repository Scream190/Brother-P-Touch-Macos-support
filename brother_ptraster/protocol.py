"""Encoder for Brother's thermal-label "raster mode" wire protocol.

Command reference (byte layout consistent across Brother's QL/PT raster
printer family; see README.md for links and validation notes):

  Invalidate               : 0x00 * 200
  Initialize               : ESC @                     (1B 40)
  Switch to raster mode    : ESC i a 01                 (1B 69 61 01)
  Print information command: ESC i z n1..n10             (1B 69 7A ...)
  Various mode settings    : ESC i M n                  (1B 69 4D n)   -- bit6 (0x40): auto-cut
  Advanced mode settings   : ESC i K n                  (1B 69 4B n)
  Feed amount              : ESC i d n1 n2               (1B 69 64 ..) -- little-endian dots
  Margin/page number, etc  : model dependent, omitted (defaults are fine)
  Select compression mode  : 'M' n                       (4D n)        -- NOT ESC-prefixed; distinct
                                                                           from "various mode settings"
                                                                           above despite sharing the 'M'
                                                                           byte. n=0x00: no compression.
                                                                           Required before raster data on
                                                                           at least some models -- omitting
                                                                           it was found (via real hardware
                                                                           test) to make the printer feed
                                                                           and cut at the right length but
                                                                           print nothing, regardless of
                                                                           pixel polarity.
  Raster graphics transfer : 'G' n1 n2 <data>            (47 ..)       -- little-endian length + n bytes
  Zero raster line         : 'Z'                         (5A)
  Print (no cut, keep buf) : 0x0C
  Print with feeding (end) : 0x1A

n1..n10 for the print information command:
  n1  : PI_KIND | PI_WIDTH | PI_LENGTH | PI_RECOVER  (0x8E - "recover on error" plus
        media type/width/length are all valid; length=0 means continuous tape)
  n2  : media type (0x01 = laminated tape)
  n3  : media width in mm
  n4  : media length in mm (0 for continuous tape)
  n5-8: total number of raster lines to be sent, 4 bytes little-endian
  n9  : starting page flag (0 = first page of the job)
  n10 : always 0
"""

from __future__ import annotations

from typing import Iterable, List

from .media import MediaSpec, HEAD_PINS, BYTES_PER_LINE, DPI

ESC = 0x1B

# print-information flags: PI_KIND(0x02) | PI_WIDTH(0x04) | PI_LENGTH(0x08) | PI_RECOVER(0x80)
PI_FLAGS = 0x02 | 0x04 | 0x08 | 0x80


class RasterJobBuilder:
    """Builds a Brother raster-mode print job for one label (one page)."""

    def __init__(
        self,
        media: MediaSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        invert: bool = False,
        feed_margin_mm: float = 25.0,
        trailing_invalidate: bool = False,
    ):
        self.media = media
        self.auto_cut = auto_cut
        self.high_resolution = high_resolution
        # Experimental: real hardware test found the printer reliably cuts
        # off whatever's hanging out of a PREVIOUS job the moment the NEXT
        # job's Invalidate+Initialize sequence arrives, but not at the end
        # of the job that's actually finishing -- as if cutting is really
        # tied to "a new job is starting" rather than our auto-cut flag.
        # This appends a second Invalidate+Initialize after the real job,
        # within the same transmission, to try to trigger that same
        # behavior without needing an actual follow-up job.
        # See tools/test_print.py --trailing-invalidate.
        self.trailing_invalidate = trailing_invalidate
        # Kept as an option after hardware testing ruled it out as the fix
        # for "nothing prints" (that turned out to be the missing
        # compression-mode-select command, see below) -- but some unit in
        # this printer family could still turn out to need it, so it's
        # cheap to leave available. See tools/test_print.py --invert.
        self.invert = invert
        # The gap between the print head and the cutter means a short job
        # can finish printing before the printed area has physically
        # reached the cutter -- confirmed on real hardware: most of a
        # ~28mm test print stayed stuck inside the printer after cutting.
        # This sets the trailing feed (in dots) applied before the final
        # cut so the printed content actually clears the cutter and ejects.
        self.feed_margin_dots = round(feed_margin_mm / 25.4 * DPI)
        self._lines: List[bytes] = []

    def add_line(self, line_bits: bytes) -> None:
        """Add one raster line.

        ``line_bits`` must be exactly ``self.media.print_bytes`` bytes, MSB
        first, 1 = print (black) dot. It is placed into the fixed 128-pin
        head buffer at the media's centered offset before being queued.
        """
        expected = self.media.print_bytes
        if len(line_bits) != expected:
            raise ValueError(f"expected {expected} bytes per line, got {len(line_bits)}")
        self._lines.append(self._pad_to_head(line_bits))

    def add_lines(self, lines: Iterable[bytes]) -> None:
        for line in lines:
            self.add_line(line)

    def _pad_to_head(self, line_bits: bytes) -> bytes:
        """Shift the media-width line into the full HEAD_PINS-wide buffer."""
        buf = bytearray(BYTES_PER_LINE)
        offset_bits = self.media.pin_offset
        byte_off, bit_off = divmod(offset_bits, 8)
        if bit_off == 0:
            buf[byte_off : byte_off + len(line_bits)] = line_bits
        else:
            carry = 0
            for i, b in enumerate(line_bits):
                shifted = (b >> bit_off) | carry
                idx = byte_off + i
                if idx < len(buf):
                    buf[idx] |= shifted & 0xFF
                carry = (b << (8 - bit_off)) & 0xFF
            tail_idx = byte_off + len(line_bits)
            if carry and tail_idx < len(buf):
                buf[tail_idx] |= carry
        return bytes(buf)

    def build(self) -> bytes:
        out = bytearray()

        # 1. Invalidate: clear any partial command sequence in the printer's
        #    receive buffer left over from a previous, possibly aborted job.
        out += b"\x00" * 200

        # 2. Initialize.
        out += bytes([ESC, 0x40])

        # 3. Switch to raster mode.
        out += bytes([ESC, 0x69, 0x61, 0x01])

        # 4. Print information command.
        n5_8 = len(self._lines).to_bytes(4, "little")
        out += bytes(
            [
                ESC,
                0x69,
                0x7A,
                PI_FLAGS,
                self.media.media_type,
                int(self.media.width_mm),
                0,  # continuous tape: length = 0
                *n5_8,
                0,  # starting page
                0,
            ]
        )

        # 5. Various mode settings (auto-cut on/off).
        out += bytes([ESC, 0x69, 0x4D, 0x40 if self.auto_cut else 0x00])

        # 6. Advanced mode settings: bit6 = high resolution printing.
        adv = 0x40 if self.high_resolution else 0x00
        out += bytes([ESC, 0x69, 0x4B, adv])

        # 7. Feed amount (margin applied after the printed content, before
        #    the cut). See __init__ for why this needs to be generous.
        margin = max(0, min(0xFFFF, self.feed_margin_dots))
        out += bytes([ESC, 0x69, 0x64, margin & 0xFF, (margin >> 8) & 0xFF])

        # 8. Select compression mode: none. NOT ESC-prefixed -- distinct
        #    from the "various mode settings" ESC i M command above despite
        #    sharing the 'M' byte. See the module docstring for why this is
        #    required, not optional.
        out += bytes([0x4D, 0x00])

        # 9. Raster data, one 'G' command per line. All-zero lines are still
        #    sent explicitly (rather than using the 'Z' shortcut) to keep
        #    the encoder simple and unambiguous; this costs a few bytes per
        #    blank line but removes a whole class of off-by-one bugs.
        for line in self._lines:
            wire_line = bytes(b ^ 0xFF for b in line) if self.invert else line
            out += bytes([0x47, len(wire_line) & 0xFF, (len(wire_line) >> 8) & 0xFF])
            out += wire_line

        # 10. Print with feeding: finalizes and (if auto-cut is on) cuts.
        out += b"\x1a"

        if self.trailing_invalidate:
            out += b"\x00" * 200
            out += bytes([ESC, 0x40])

        return bytes(out)


def pack_bitmap_row(pixels: Iterable[int], n_bytes: int) -> bytes:
    """Pack an iterable of 0/1 pixel values (MSB-first) into ``n_bytes``."""
    buf = bytearray(n_bytes)
    for i, p in enumerate(pixels):
        if not p:
            continue
        byte_idx, bit_idx = divmod(i, 8)
        if byte_idx >= n_bytes:
            break
        buf[byte_idx] |= 0x80 >> bit_idx
    return bytes(buf)
