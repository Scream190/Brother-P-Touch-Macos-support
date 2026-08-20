#!/usr/bin/env python3
"""Standalone hardware bring-up tool for the Brother PT-P710BT driver.

Sends a raster-mode print job STRAIGHT to the printer, bypassing CUPS
entirely. This is deliberately separate from the CUPS filter/backend so a
print made with this tool tells you whether the *protocol* is right,
without CUPS's own PDF/PostScript rasterization in the loop too.

Examples:
    # Just look at what would be sent, without a printer:
    python3 tools/test_print.py --media 12mm --pattern ruler --dry-run --out /tmp/job.bin

    # Find the paired device name first:
    python3 tools/list_bt_serial_ports.py

    # Then send a real test print:
    python3 tools/test_print.py --media 12mm --pattern diagonal \\
        --device PT-P710BT-SerialPort

Run through the patterns in this rough order, since each isolates a
different class of bug:
    1. solid        -- does it print at all, full width, no gaps?
    2. ruler         -- is the tape width detected correctly & centered?
    3. diagonal      -- any bit/byte-order or off-by-one errors?
    4. checkerboard  -- fine-grained black/white transitions clean?
    5. border        -- edges crisp, nothing clipped?
    6. stripes       -- consecutive raster lines handled correctly?

After each print, note what you see (or paste the --dry-run hex dump) back
into the conversation with Claude so protocol.py/media.py can be corrected
against what the real printer actually did.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from brother_ptraster.media import MEDIA_TABLE, get_media
from brother_ptraster.patterns import PATTERNS, generate
from brother_ptraster.protocol import RasterJobBuilder


def send_to_device(device_path: str, data: bytes, verbose: bool) -> None:
    if not os.path.exists(device_path):
        raise SystemExit(
            f"{device_path} not found. Is the printer paired (System Settings > "
            f"Bluetooth) and powered on? Run tools/list_bt_serial_ports.py to check."
        )

    fd = os.open(device_path, os.O_WRONLY | os.O_NOCTTY)
    try:
        try:
            import tty

            tty.setraw(fd)
        except Exception as exc:
            if verbose:
                print(f"(could not set raw tty mode, continuing anyway: {exc})", file=sys.stderr)

        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--media", choices=sorted(MEDIA_TABLE), default="12mm", help="tape width loaded in the printer")
    parser.add_argument("--pattern", choices=PATTERNS, default="ruler", help="test pattern to print")
    parser.add_argument("--length", type=int, default=200, help="label length in dots (180 dots ~= 25.4mm at 180dpi)")
    parser.add_argument("--no-cut", action="store_true", help="disable auto-cut after printing")
    parser.add_argument("--device", help="paired Bluetooth serial device name, e.g. PT-P710BT-SerialPort (from tools/list_bt_serial_ports.py)")
    parser.add_argument("--device-path", help="full path override instead of --device, e.g. /dev/cu.PT-P710BT-SerialPort")
    parser.add_argument("--dry-run", action="store_true", help="don't send anything; just build the job")
    parser.add_argument("--out", help="write the raw command bytes to this file (useful with --dry-run, or to double-check a real send)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print a byte-level summary of the generated job")
    args = parser.parse_args()

    media = get_media(args.media)
    lines = generate(args.pattern, media, args.length)

    builder = RasterJobBuilder(media, auto_cut=not args.no_cut)
    builder.add_lines(lines)
    data = builder.build()

    print(f"Pattern: {args.pattern}  Media: {media.name} ({media.print_dots} dots, "
          f"{media.print_bytes} bytes/line)  Lines: {len(lines)}  Job size: {len(data)} bytes")

    if args.verbose:
        print(f"  invalidate+init+raster-mode preamble: {data[:206].hex()}")
        print(f"  print-information command:            {data[206:219].hex()}")
        print(f"  mode settings:                        {data[219:223].hex()}")
        print(f"  advanced settings:                    {data[223:227].hex()}")
        print(f"  first raster line ('G' + len + data):  {data[227:227 + 3 + media.print_bytes].hex()}")
        print(f"  last byte (should be 0x1a):            {data[-1:].hex()}")

    if args.out:
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"Wrote {len(data)} bytes to {args.out}")

    if args.dry_run:
        print("--dry-run set: not sending anything to a printer.")
        return 0

    if args.device_path:
        device_path = args.device_path
    elif args.device:
        device_path = f"/dev/cu.{args.device}"
    else:
        raise SystemExit("Specify --device NAME (see tools/list_bt_serial_ports.py) or --device-path, or pass --dry-run.")

    print(f"Sending to {device_path} ...")
    send_to_device(device_path, data, args.verbose)
    print("Sent. Check the printer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
