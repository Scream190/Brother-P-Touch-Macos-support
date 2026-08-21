"""Encoder for Brother's thermal-label "raster mode" wire protocol.

Command reference (byte layout consistent across Brother's QL/PT raster
printer family; see README.md for links and validation notes):

  Invalidate               : 0x00 * 200
  Initialize               : ESC @                     (1B 40)
  Switch to raster mode    : ESC i a 01                 (1B 69 61 01)
  Print information command: ESC i z n1..n10             (1B 69 7A ...)
  Various mode settings    : ESC i M n                  (1B 69 4D n)   -- bit6 (0x40): auto-cut
  Advanced mode settings   : ESC i K n                  (1B 69 4B n)   -- bit3 (0x08): confirmed on real
                                                                           hardware to be required for the
                                                                           printer to actually cut at the
                                                                           end of a job. Without it, content
                                                                           prints and feeds correctly but
                                                                           the printer withholds the cut
                                                                           until a NEXT job's Invalidate
                                                                           sequence arrives (as if 0x00
                                                                           here means "more labels may be
                                                                           coming, don't finalize yet").
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
        mode_byte: "int | None" = None,
        advanced_byte: "int | None" = None,
        leading_cleanup: bool = False,
    ):
        self.media = media
        self.auto_cut = auto_cut
        self.high_resolution = high_resolution
        # Raw overrides for hardware bring-up: bypass auto_cut/
        # high_resolution entirely and send this exact byte for "various
        # mode settings" / "advanced mode settings" instead. Real hardware
        # test found auto_cut (bit 0x40 of the mode byte) alone doesn't
        # trigger a cut at the end of a job -- cutting only visibly
        # happens once a NEXT job starts, suggesting a "chain printing"
        # style bit (probably in the advanced settings byte) is left in
        # the wrong state by the current default of 0x00. Lets
        # tools/test_print.py --mode-byte/--advanced-byte try candidate
        # values without needing a code change per attempt.
        self.mode_byte_override = mode_byte
        self.advanced_byte_override = advanced_byte
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
        # DEFAULT OFF -- an earlier implementation (concatenating a 0-line
        # cleanup segment and the real segment into ONE transmission) was
        # confirmed on real hardware to hang the printer/USB connection,
        # needing a full Mac restart to recover (power-cycling the printer
        # and replugging the cable alone did not clear it). The intent
        # (user-requested) is unchanged: every job starts with its own tiny
        # feed+cut cycle first (0 raster lines -- just the control-command
        # overhead: feed the margin, then cut), so each label starts on a
        # freshly-cut, consistent tape edge regardless of what came before.
        #
        # This flag is now just a marker read by callers (see
        # tools/test_print.py); it does NOT change what build() returns.
        # build_cleanup_segment() returns the 0-line segment separately, and
        # the caller is responsible for sending it as a genuinely separate
        # transmission (its own connect/write/disconnect cycle) BEFORE
        # build()'s segment, with a real pause in between for the feed+cut
        # motion to physically finish -- not just concatenating the bytes,
        # which is what hung before. Still treat this as risky: test with a
        # short throwaway job first, on a machine that isn't mid-print, and
        # be ready for another restart if it locks up again.
        self.leading_cleanup = leading_cleanup
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

    def _build_segment(self, lines: List[bytes]) -> bytes:
        """Build one complete job segment: Invalidate through the final
        print-with-feed byte, for the given (already head-padded) lines.
        Shared by the real content and the optional leading cleanup
        segment (called with an empty list -- feed the margin and cut,
        with no raster data at all).
        """
        out = bytearray()

        # 1. Invalidate: clear any partial command sequence in the printer's
        #    receive buffer left over from a previous, possibly aborted job.
        out += b"\x00" * 200

        # 2. Initialize.
        out += bytes([ESC, 0x40])

        # 3. Switch to raster mode.
        out += bytes([ESC, 0x69, 0x61, 0x01])

        # 4. Print information command.
        n5_8 = len(lines).to_bytes(4, "little")
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
        if self.mode_byte_override is not None:
            mode_byte = self.mode_byte_override
        else:
            mode_byte = 0x40 if self.auto_cut else 0x00
        out += bytes([ESC, 0x69, 0x4D, mode_byte])

        # 6. Advanced mode settings: bit6 = high resolution printing, bit3
        #    = required for the printer to actually cut (see module
        #    docstring) -- always set unless explicitly overridden.
        if self.advanced_byte_override is not None:
            adv = self.advanced_byte_override
        else:
            adv = 0x08 | (0x40 if self.high_resolution else 0x00)
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
        for line in lines:
            wire_line = bytes(b ^ 0xFF for b in line) if self.invert else line
            out += bytes([0x47, len(wire_line) & 0xFF, (len(wire_line) >> 8) & 0xFF])
            out += wire_line

        # 10. Print with feeding: finalizes and (if auto-cut is on) cuts.
        out += b"\x1a"

        return bytes(out)

    def build_cleanup_segment(self) -> bytes:
        """A complete, independent 0-line job segment: feed the margin,
        then cut, with no raster data at all. Meant to be sent as a fully
        SEPARATE transmission (separate connect/write/disconnect, not just
        concatenated bytes) before build()'s segment, with a real pause in
        between for the feed+cut motion to physically finish -- see
        ``leading_cleanup`` in __init__ for why concatenating them in one
        transmission is not safe. Only meaningful when ``leading_cleanup``
        is True; callers are responsible for actually sending this
        separately (see tools/test_print.py).
        """
        return self._build_segment([])

    def build(self) -> bytes:
        out = bytearray()

        out += self._build_segment(self._lines)

        if self.trailing_invalidate:
            out += b"\x00" * 200
            out += bytes([ESC, 0x40])

        return bytes(out)


def build_status_request() -> bytes:
    """Invalidate + Initialize + Status Information Request (ESC i S).

    Clears any partial command sequence left in the printer's receive
    buffer first (same first two steps as a real print job), then asks it
    to reply with its current 32-byte status packet (see
    brother_ptraster/status.py) -- includes the currently loaded media's
    width and type. Used by tools/check_media.py for "check media"-style
    auto-detection, sent over a direct USB connection (see
    brother_ptraster/usb_transport.py) since this needs to read the
    printer's reply, which the normal CUPS print path doesn't do.
    """
    return b"\x00" * 200 + bytes([ESC, 0x40]) + bytes([ESC, 0x69, 0x53])


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
