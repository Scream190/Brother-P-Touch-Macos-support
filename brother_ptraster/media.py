"""Media (tape cassette) tables for the Brother PT-P710BT.

The PT-P710BT uses Brother's "TZe" laminated tape cassettes in the widths
below. Each cassette reports its width to the printer via the mechanical
cassette-detection pins; the "print information command" in the raster
protocol still needs the nominal width in millimetres and the usable print
area in dots so the raster filter can center/pad each line correctly.

Print head: 128 pins (this is the pin count Brother uses across the whole
PT-7xx/8xx/9xx "128-dot head" family, matching the widest supported
24 mm tape at 180 dpi). Only the pins that fall within the current tape's
width are meaningful; unused pins must be sent as 0 (blank) bits.

Values below are taken from Brother's published PT-P710BT specifications
(supported tape widths, 180 dpi print resolution). The per-mm dot counts are
derived (180 dpi / 25.4 mm/in), then centered within the 128-pin head. If
Brother's official reference documents different centering offsets for a
given width, adjust PIN_OFFSET for that entry before relying on this for
production prints.
"""

from dataclasses import dataclass

DPI = 180
HEAD_PINS = 128
BYTES_PER_LINE = HEAD_PINS // 8  # 16


@dataclass(frozen=True)
class MediaSpec:
    name: str
    width_mm: float
    # Brother's "media type" byte for the print-information command.
    # 0x01 = laminated tape (the only cassette type this printer supports).
    media_type: int
    # Usable print width in dots for this tape (<=128).
    print_dots: int
    # Offset (in pins, from pin 0) where the usable area starts, so the
    # active area is centered on the fixed 128-pin head.
    pin_offset: int

    @property
    def print_bytes(self) -> int:
        return -(-self.print_dots // 8)  # ceil div

    @property
    def ppd_option(self) -> str:
        """The CUPS/PPD ``media=`` option value for this tape, e.g.
        ``mm12`` for the "12mm" entry. NOT the same string as ``name``
        (display-oriented, "12mm") -- the PPD's ``*PageSize`` choice names
        are prefixed the other way around (``mm12``, ``mm3.5``, ...)
        because PostScript/PPD option names can't start with a digit.
        """
        return f"mm{self.width_mm:g}"



# Fine-tune constant for the print head <-> tape alignment, CONFIRMED on
# real PT-P710BT hardware: full-width solid fill on 12mm tape found a
# small but consistent asymmetry with the plain 50/50 centering split
# (~0mm margin on one edge, ~0.5mm on the other) -- the printer's real
# head-to-tape alignment is slightly off from perfectly centered, not a
# centering-formula bug. Found via incremental testing (2 dots visibly
# improved it, 3 dots looked perfect) -- positive shifts pin_offset up,
# toward higher-numbered pins.
#
# This is a mechanical property of one specific physical unit, not
# necessarily shared even by other units of the same model, let alone
# other models (PT-P700/PT-P750W) -- build_media_table() lets each
# model's filter supply its own value once tuned the same way; this
# module-level constant (and the MEDIA_TABLE built from it) exists only
# for the PT-P710BT and code that doesn't care about the distinction.
PIN_ALIGNMENT_TRIM_DOTS = 3


def build_media_table(pin_alignment_trim_dots: int = PIN_ALIGNMENT_TRIM_DOTS) -> dict:
    """Build a name -> MediaSpec table for the given centering trim.

    The supported tape widths, 128-pin head, and 180dpi resolution are the
    same across the whole PT-P700/PT-P750W/PT-P710BT family (confirmed:
    Brother documents P750W and P710BT's raster protocol in one combined
    reference; P700 is treated as a standard member of the same PT-series
    raster family by third-party drivers, though not itself named in
    Brother's own doc). Only the pin-alignment trim is expected to differ
    per physical unit/model, since it's a mechanical property of that
    specific printer's head-to-tape alignment, not something the shared
    protocol determines -- see PIN_ALIGNMENT_TRIM_DOTS.
    """

    def _centered(width_mm: float) -> MediaSpec:
        print_dots = round(width_mm / 25.4 * DPI)
        print_dots = min(print_dots, HEAD_PINS)
        max_offset = HEAD_PINS - print_dots
        pin_offset = max_offset // 2 + pin_alignment_trim_dots
        pin_offset = max(0, min(max_offset, pin_offset))
        return MediaSpec(
            name=f"{width_mm:g}mm",
            width_mm=width_mm,
            media_type=0x01,
            print_dots=print_dots,
            pin_offset=pin_offset,
        )

    return {
        spec.name: spec
        for spec in (
            _centered(3.5),
            _centered(6),
            _centered(9),
            _centered(12),
            _centered(18),
            _centered(24),
        )
    }


# Continuous-length TZe tape widths supported by the PT-P710BT specifically
# (PIN_ALIGNMENT_TRIM_DOTS above). Other models should build their own via
# build_media_table(their_own_trim) -- see filter/rastertoptp700 and
# filter/rastertoptp750w.
MEDIA_TABLE = build_media_table()


def get_media(name: str, table: dict = MEDIA_TABLE) -> MediaSpec:
    try:
        return table[name]
    except KeyError as exc:
        valid = ", ".join(sorted(table))
        raise ValueError(f"Unknown media {name!r}; valid options: {valid}") from exc


def get_media_by_ppd_option(ppd_option: str, table: dict = MEDIA_TABLE) -> MediaSpec:
    """Reverse lookup of ``MediaSpec.ppd_option`` (e.g. ``"mm12"``), for
    tools that work with the same ``-o media=...`` value a CUPS job uses
    rather than the display-oriented ``name`` (see ``ppd_option`` on
    ``MediaSpec`` for why these differ).
    """
    for media in table.values():
        if media.ppd_option == ppd_option:
            return media
    valid = ", ".join(sorted(m.ppd_option for m in table.values()))
    raise ValueError(f"Unknown PPD media option {ppd_option!r}; valid options: {valid}")


def nearest_media(width_mm: float, tolerance_mm: float = 1.5, table: dict = MEDIA_TABLE) -> MediaSpec:
    """Return the MediaSpec whose width is closest to ``width_mm``.

    Used by the CUPS filter to pick the tape width from the raster page's
    actual dot width rather than from a PPD option name, so it works
    whether the user picked one of our named PageSize presets or defined a
    macOS "Custom Size". Raises ValueError if nothing is within tolerance,
    since printing at the wrong width would misalign the label.
    """
    best = min(table.values(), key=lambda m: abs(m.width_mm - width_mm))
    if abs(best.width_mm - width_mm) > tolerance_mm:
        valid = ", ".join(sorted(table))
        raise ValueError(
            f"page width {width_mm:.1f}mm doesn't match any supported tape "
            f"width within {tolerance_mm}mm; supported widths: {valid}"
        )
    return best
