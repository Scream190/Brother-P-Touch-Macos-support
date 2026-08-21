#!/usr/bin/env python3
"""Query the Brother PT-P710BT for its currently loaded tape -- like the
"check media" button in Brother's own P-touch software.

Sends a status request directly over USB (bypassing CUPS entirely -- see
brother_ptraster/usb_transport.py for why the normal CUPS print path can't
be reused for this) and decodes the printer's 32-byte status reply, which
includes the loaded tape's width and type.

Requires (only for this tool -- normal printing via CUPS is unaffected):
    pip3 install pyusb
    brew install libusb

Usage:
    python3 tools/check_media.py
    python3 tools/check_media.py --serial 000J4G980818

Pass --serial (the same serial number visible in `sudo lpinfo -v`'s
usb://Brother/PT-P710BT?serial=... URI) if you have more than one Brother
USB device attached and need to disambiguate.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from brother_ptraster.media import nearest_media
from brother_ptraster.protocol import build_status_request
from brother_ptraster.status import decode
from brother_ptraster.usb_transport import UsbTransportError, query_status


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--serial",
        help="USB serial number to disambiguate if more than one Brother "
        "USB device is attached (see 'sudo lpinfo -v')",
    )
    args = parser.parse_args()

    try:
        reply = query_status(build_status_request(), serial=args.serial)
    except UsbTransportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        status = decode(reply)
    except ValueError as exc:
        print(f"error decoding status packet: {exc}", file=sys.stderr)
        print(f"raw bytes: {reply.hex()}", file=sys.stderr)
        return 1

    print(status)

    if status.media_width_mm:
        try:
            media = nearest_media(float(status.media_width_mm), tolerance_mm=0.5)
        except ValueError:
            print(
                f"\nnote: reported width {status.media_width_mm}mm doesn't "
                f"exactly match a supported preset -- check media.py"
            )
        else:
            print(f"\n-> use: lp -d PT-P710BT -o media={media.name} ...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
