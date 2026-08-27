#!/usr/bin/env python3
"""Verify the loaded tape, THEN print -- as two fully separate steps.

Runs the same status query as tools/check_media.py (direct USB, bypassing
CUPS) to confirm the printer's actually-loaded tape width matches what
you're about to tell CUPS to print at, and only THEN invokes `lp` to
submit the real job. If the widths don't match, it refuses to print and
tells you what's actually loaded instead.

This is deliberately two SEPARATE steps, run one after the other, not
interleaved: the status query's USB connection is fully closed before
`lp`/the CUPS backend ever touches the device. Checking media WHILE a
print job's own USB transmission is in flight was considered and
rejected -- this printer's USB stack has repeatedly shown itself prone to
hangs/error states when two things try to use it at once (see the
leading_cleanup saga in git history), and this tool avoids that risk
entirely by never doing both at the same time.

Requires (only for the check step): pip3 install pyusb libusb-package

Usage:
    python3 tools/print_with_check.py --media mm12 label.pdf
    python3 tools/print_with_check.py --media mm18 --serial 000J4G980818 \\
        --queue PT-P710BT --option AutoCut=False label.pdf
    python3 tools/print_with_check.py --media mm12 --skip-check label.pdf
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from brother_ptraster.media import get_media_by_ppd_option
from brother_ptraster.protocol import build_status_request
from brother_ptraster.status import decode
from brother_ptraster.usb_transport import UsbTransportError, query_status


def check_media(ppd_media: str, serial: "str | None", tolerance_mm: float) -> None:
    """Raise SystemExit with a clear message if the loaded tape doesn't
    match ``ppd_media`` (a PPD ``-o media=...`` value, e.g. "mm12").
    """
    expected = get_media_by_ppd_option(ppd_media)

    try:
        reply = query_status(build_status_request(), serial=serial)
    except UsbTransportError as exc:
        raise SystemExit(
            f"Could not verify the loaded tape ({exc}).\n"
            f"Pass --skip-check to print anyway without verifying."
        )

    status = decode(reply)
    if abs(status.media_width_mm - expected.width_mm) > tolerance_mm:
        raise SystemExit(
            f"Refusing to print: you asked for {ppd_media} ({expected.width_mm}mm) "
            f"but the printer reports {status.media_width_mm}mm "
            f"({status.media_type}) actually loaded.\n"
            f"Either reload the correct tape, pass --media mm{status.media_width_mm:g} "
            f"instead, or pass --skip-check to print anyway."
        )
    print(f"Verified: {status.media_width_mm}mm {status.media_type} loaded, matches --media {ppd_media}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="file to print (PDF, etc.)")
    parser.add_argument("--media", required=True, help="expected PPD media option, e.g. mm12 (see brother_ptraster.media.MEDIA_TABLE)")
    parser.add_argument("--queue", default="PT-P710BT", help="CUPS queue name (default: PT-P710BT)")
    parser.add_argument("--serial", help="USB serial number to disambiguate for the check step, if more than one Brother USB device is attached")
    parser.add_argument("--tolerance-mm", type=float, default=1.0, help="allowed difference between requested and actual tape width before refusing to print (default 1.0mm)")
    parser.add_argument("--skip-check", action="store_true", help="skip the media verification step entirely and just print")
    parser.add_argument("--option", action="append", default=[], metavar="KEY=VALUE", help="extra CUPS option, passed through as -o KEY=VALUE to lp (repeatable)")
    parser.add_argument("--copies", type=int, default=1, help="number of copies (default 1)")
    args = parser.parse_args()

    if not args.skip_check:
        check_media(args.media, args.serial, args.tolerance_mm)

    lp_argv = ["lp", "-d", args.queue, "-n", str(args.copies), "-o", f"media={args.media}"]
    for opt in args.option:
        lp_argv += ["-o", opt]
    lp_argv.append(args.file)

    print(f"Printing: {' '.join(lp_argv)}")
    result = subprocess.run(lp_argv)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
