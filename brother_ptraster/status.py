"""Decoder for Brother's 32-byte raster-printer status packet.

Brother's QL/PT raster printer family sends this fixed-size status packet
back over the same link after a print job (and in reply to an explicit
status request, ESC i S / 0x1B 0x69 0x53 -- not currently sent by this
driver). Field layout is best-effort from the publicly documented/commonly
referenced structure for this printer family; treat unexpected/reserved
byte values with suspicion and cross-check against a real capture if
something here doesn't add up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

MEDIA_TYPES = {
    0x00: "no media",
    0x01: "laminated tape",
    0x03: "non-laminated tape",
    0x04: "fabric tape",
    0x11: "heat-shrink tube",
    0xFF: "incompatible tape",
}

STATUS_TYPES = {
    0x00: "reply to status request",
    0x01: "printing completed",
    0x02: "error occurred",
    0x03: "turned off",
    0x04: "notification",
    0x05: "phase change",
    0x06: "advanced mode",
}

PHASE_TYPES = {
    0x00: "waiting to receive",
    0x01: "printing",
}

ERROR1_BITS = {
    0x01: "no media",
    0x02: "end of media",
    0x04: "cutter jam",
    0x08: "weak batteries",
    0x20: "high-voltage adapter",
    0x80: "fan malfunction",
}

ERROR2_BITS = {
    0x01: "replace media",
    0x02: "expansion buffer full",
    0x04: "communication error",
    0x08: "communication buffer full",
    0x10: "cover open",
    0x20: "cancel key pressed",
    0x40: "media cannot be fed / jam",
    0x80: "system error",
}

# Tape (background) color, byte 24. NOT hardware-confirmed yet -- like the
# rest of this best-effort layout, cross-check against a real capture
# (tools/check_media.py) against tape whose actual color you know, and
# correct here if it doesn't match.
TAPE_COLORS = {
    0x01: "white",
    0x02: "other",
    0x03: "clear",
    0x04: "red",
    0x05: "blue",
    0x06: "yellow",
    0x07: "green",
    0x08: "black",
    0x09: "clear (white text)",
    0x20: "matte white",
    0x21: "matte clear",
    0x22: "matte silver",
    0x23: "satin gold",
    0x24: "satin silver",
    0x30: "blue (D)",
    0x31: "red (D)",
    0x40: "fluorescent orange",
    0x41: "fluorescent yellow",
    0x50: "berry pink (S)",
    0x51: "light gray (S)",
    0x52: "lime green (S)",
    0x60: "yellow (fabric)",
    0x61: "pink (fabric)",
    0x62: "blue (fabric)",
    0x70: "heat-shrink tube",
    0x90: "white (flex ID)",
    0xF0: "cleaning",
    0xF1: "stencil",
    0xFF: "incompatible",
}

# Text (print) color, byte 25. Same hardware-unconfirmed caveat as above.
TEXT_COLORS = {
    0x01: "white",
    0x02: "other",
    0x04: "red",
    0x08: "black",
    0x0A: "gold",
    0x62: "blue (fabric)",
    0xF0: "cleaning",
    0xFF: "incompatible",
}


@dataclass
class StatusPacket:
    raw: bytes
    media_width_mm: int
    media_type: str
    media_length_mm: int
    status_type: str
    phase_type: str
    phase_number: int
    tape_color: str
    text_color: str
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"media: {self.media_type} ({self.media_width_mm}mm"
            + (f" x {self.media_length_mm}mm" if self.media_length_mm else ", continuous")
            + ")",
            f"colors: {self.text_color} text on {self.tape_color} tape",
            f"status: {self.status_type}",
            f"phase: {self.phase_type} (#{self.phase_number})",
        ]
        if self.errors:
            lines.append("ERRORS: " + ", ".join(self.errors))
        else:
            lines.append("errors: none reported")
        return "\n".join(lines)


def decode(data: bytes) -> StatusPacket:
    if len(data) != 32:
        raise ValueError(f"expected a 32-byte status packet, got {len(data)} bytes")

    err1, err2 = data[8], data[9]
    errors = [name for bit, name in ERROR1_BITS.items() if err1 & bit]
    errors += [name for bit, name in ERROR2_BITS.items() if err2 & bit]

    return StatusPacket(
        raw=data,
        media_width_mm=data[10],
        media_type=MEDIA_TYPES.get(data[11], f"unknown (0x{data[11]:02x})"),
        media_length_mm=data[16],
        status_type=STATUS_TYPES.get(data[17], f"unknown (0x{data[17]:02x})"),
        phase_type=PHASE_TYPES.get(data[18], f"unknown (0x{data[18]:02x})"),
        phase_number=int.from_bytes(data[19:21], "big"),
        tape_color=TAPE_COLORS.get(data[24], f"unknown (0x{data[24]:02x})"),
        text_color=TEXT_COLORS.get(data[25], f"unknown (0x{data[25]:02x})"),
        errors=errors,
    )
