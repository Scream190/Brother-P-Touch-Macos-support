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



# Fine-tune constant for the assumed print head <-> tape alignment. Real
# hardware test (12mm tape, full-width solid fill) found a small but
# consistent asymmetry: ~0.5mm margin on one edge, ~0mm (right at the
# edge) on the other -- meaning the printer's real head-to-tape alignment
# is slightly off from perfectly centered, not centering-formula-wrong,
# just a small mechanical/measurement offset. Positive shifts pin_offset
# up (toward higher-numbered pins); the actual physical direction (which
# edge that corresponds to) isn't known yet -- this value is a trial
# guess, to be corrected based on whether the next real-hardware test
# shows the asymmetry improve or worsen. 0 = no adjustment (previous
# behavior).
PIN_ALIGNMENT_TRIM_DOTS = 3


def _centered(width_mm: float) -> MediaSpec:
    print_dots = round(width_mm / 25.4 * DPI)
    print_dots = min(print_dots, HEAD_PINS)
    max_offset = HEAD_PINS - print_dots
    pin_offset = max_offset // 2 + PIN_ALIGNMENT_TRIM_DOTS
    pin_offset = max(0, min(max_offset, pin_offset))
    return MediaSpec(
        name=f"{width_mm:g}mm",
        width_mm=width_mm,
        media_type=0x01,
        print_dots=print_dots,
        pin_offset=pin_offset,
    )


# Continuous-length TZe tape widths supported by the PT-P710BT.
MEDIA_TABLE = {
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


def get_media(name: str) -> MediaSpec:
    try:
        return MEDIA_TABLE[name]
    except KeyError as exc:
        valid = ", ".join(sorted(MEDIA_TABLE))
        raise ValueError(f"Unknown media {name!r}; valid options: {valid}") from exc


def nearest_media(width_mm: float, tolerance_mm: float = 1.5) -> MediaSpec:
    """Return the MediaSpec whose width is closest to ``width_mm``.

    Used by the CUPS filter to pick the tape width from the raster page's
    actual dot width rather than from a PPD option name, so it works
    whether the user picked one of our named PageSize presets or defined a
    macOS "Custom Size". Raises ValueError if nothing is within tolerance,
    since printing at the wrong width would misalign the label.
    """
    best = min(MEDIA_TABLE.values(), key=lambda m: abs(m.width_mm - width_mm))
    if abs(best.width_mm - width_mm) > tolerance_mm:
        valid = ", ".join(sorted(MEDIA_TABLE))
        raise ValueError(
            f"page width {width_mm:.1f}mm doesn't match any supported tape "
            f"width within {tolerance_mm}mm; supported widths: {valid}"
        )
    return best
