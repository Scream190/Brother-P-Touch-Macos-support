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


@dataclass
class StatusPacket:
    raw: bytes
    media_width_mm: int
    media_type: str
    media_length_mm: int
    status_type: str
    phase_type: str
    phase_number: int
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"media: {self.media_type} ({self.media_width_mm}mm"
            + (f" x {self.media_length_mm}mm" if self.media_length_mm else ", continuous")
            + ")",
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
        errors=errors,
    )
