#!/usr/bin/env python3
"""Decode a Brother 32-byte status packet, e.g. one captured from the
'back-channel data' the usb backend logs when run with -v (see
tools/test_print.py send_via_usb, which sets CUPS_DEBUG_LOG=- and
CUPS_DEBUG_LEVEL=2 to get a hex dump of it).

Usage:
    python3 tools/decode_status.py <64 hex chars, spaces/colons ok>

Example:
    python3 tools/decode_status.py \\
        "80 20 42 30 30 30 00 00 00 10 0c 01 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from brother_ptraster.status import decode


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    hex_str = re.sub(r"[^0-9a-fA-F]", "", " ".join(sys.argv[1:]))
    try:
        data = bytes.fromhex(hex_str)
    except ValueError as exc:
        print(f"Could not parse hex input: {exc}", file=sys.stderr)
        return 1

    try:
        status = decode(data)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
