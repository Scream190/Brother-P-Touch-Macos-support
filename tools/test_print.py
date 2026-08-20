#!/usr/bin/env python3
"""Standalone hardware bring-up tool for the Brother PT-P710BT driver.

Sends a raster-mode print job STRAIGHT to the printer, bypassing CUPS
entirely. This is deliberately separate from the CUPS filter/backend so a
print made with this tool tells you whether the *protocol* is right,
without CUPS's own PDF/PostScript rasterization in the loop too. Brother's
raster-mode command protocol is the same regardless of transport, so this
works for USB or Bluetooth -- only the last step (how the bytes physically
reach the printer) differs.

USB (recommended -- confirmed working transport for at least one PT-P710BT
unit; Bluetooth SPP was confirmed non-functional on the same unit, pairing
only with phones):

    # Find the USB device URI (needs sudo to see USB printers):
    sudo lpinfo -v | grep -i usb

    # Send a test print over USB (also needs sudo, since talking to the raw
    # USB device requires it, same as the real CUPS 'usb' backend does):
    sudo python3 tools/test_print.py --media 12mm --pattern ruler \\
        --usb-uri 'usb://Brother/PT-P710BT?serial=XXXXXXXXX'

Bluetooth (experimental / may not work on your unit):

    python3 tools/list_bt_serial_ports.py
    python3 tools/test_print.py --media 12mm --pattern diagonal \\
        --device PT-P710BT-SerialPort

Dry run (no printer needed):

    python3 tools/test_print.py --media 12mm --pattern ruler --dry-run --out /tmp/job.bin

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
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from brother_ptraster.media import MEDIA_TABLE, get_media
from brother_ptraster.patterns import PATTERNS, generate
from brother_ptraster.protocol import RasterJobBuilder

USB_BACKEND = "/usr/libexec/cups/backend/usb"


def send_to_device(device_path: str, data: bytes, verbose: bool, connect_delay: float = 0.5) -> None:
    if not os.path.exists(device_path):
        raise SystemExit(
            f"{device_path} not found. Is the printer paired (System Settings > "
            f"Bluetooth) and powered on? Run tools/list_bt_serial_ports.py to check."
        )

    # O_RDWR (not O_WRONLY): some macOS Bluetooth SPP virtual serial ports
    # only fully bring up the RFCOMM connection when opened for both
    # reading and writing.
    fd = os.open(device_path, os.O_RDWR | os.O_NOCTTY)
    try:
        try:
            import termios
            import tty

            tty.setraw(fd)
            attrs = termios.tcgetattr(fd)
            attrs[2] &= ~termios.CRTSCTS  # disable hardware flow control
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception as exc:
            if verbose:
                print(f"(could not configure raw/flow-control tty mode, continuing anyway: {exc})", file=sys.stderr)

        if connect_delay:
            if verbose:
                print(f"(waiting {connect_delay}s for the Bluetooth SPP connection to come up...)", file=sys.stderr)
            time.sleep(connect_delay)

        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.fsync(fd)

        if verbose:
            import select

            readable, _, _ = select.select([fd], [], [], 1.0)
            if readable:
                reply = os.read(fd, 256)
                print(f"(printer replied with {len(reply)} bytes: {reply.hex()})", file=sys.stderr)
            else:
                print("(no reply bytes from printer within 1s -- normal if it doesn't send status unprompted)", file=sys.stderr)
    finally:
        os.close(fd)


def build_usb_backend_argv(job_id: str, user: str, title: str, tmp_path: str) -> list:
    """Construct the argv CUPS itself would use to invoke the usb backend.

    Split out from send_via_usb() so the argument construction can be
    tested without actually invoking the (root-only, macOS-only) backend.
    """
    return [USB_BACKEND, job_id, user, title, "1", "", tmp_path]


def send_via_usb(usb_uri: str, data: bytes, verbose: bool) -> None:
    """Send a job by directly invoking macOS's own signed CUPS usb backend.

    This reuses Apple's backend for the actual USB I/O (which macOS doesn't
    expose through a simple writable /dev node the way it does Bluetooth
    serial ports) instead of reimplementing USB printer access. It's the
    same binary a real CUPS queue would use, just invoked by hand with our
    raw command bytes instead of a rasterized job from CUPS.
    """
    if not os.path.exists(USB_BACKEND):
        raise SystemExit(f"{USB_BACKEND} not found -- unexpected on macOS.")
    if os.geteuid() != 0:
        raise SystemExit("Talking to the USB backend directly needs root: re-run with sudo.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(data)
        tmp_path = f.name

    debug_log_path = None
    try:
        argv = build_usb_backend_argv("1", os.environ.get("USER", "user"), "test-print", tmp_path)
        env = dict(os.environ)
        env["DEVICE_URI"] = usb_uri
        if verbose:
            # Unlocks full CUPS backend debug logging when run standalone
            # (outside cupsd) -- in particular this should hex-dump any
            # "back-channel data" the printer sends back (e.g. Brother's
            # 32-byte status packet), not just how many bytes arrived. Use
            # an explicit file rather than "-" for stderr: that shorthand
            # isn't reliably honored by every CUPS build, and an explicit
            # path lets us just read it back ourselves either way.
            debug_log_path = tempfile.mktemp(suffix=".cups-debug.log")
            env["CUPS_DEBUG_LOG"] = debug_log_path
            env["CUPS_DEBUG_LEVEL"] = "2"
            print(f"(running: DEVICE_URI={usb_uri} {' '.join(argv)})", file=sys.stderr)
        result = subprocess.run(argv, env=env, capture_output=True, text=True)
        if result.stdout and verbose:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if debug_log_path and os.path.exists(debug_log_path):
            print(f"\n--- backend debug log ({debug_log_path}) ---", file=sys.stderr)
            with open(debug_log_path, "r", errors="replace") as f:
                print(f.read(), file=sys.stderr)
            print("--- end debug log ---", file=sys.stderr)
        elif verbose:
            print("(no debug log file was created -- CUPS_DEBUG_LOG may not be honored on this macOS version)", file=sys.stderr)
        if result.returncode != 0:
            raise SystemExit(f"usb backend exited with code {result.returncode}")
    finally:
        os.unlink(tmp_path)
        if debug_log_path and os.path.exists(debug_log_path):
            os.unlink(debug_log_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--media", choices=sorted(MEDIA_TABLE), default="12mm", help="tape width loaded in the printer")
    parser.add_argument("--pattern", choices=PATTERNS, default="ruler", help="test pattern to print")
    parser.add_argument("--length", type=int, default=200, help="label length in dots (180 dots ~= 25.4mm at 180dpi)")
    parser.add_argument("--no-cut", action="store_true", help="disable auto-cut after printing")
    parser.add_argument("--feed-margin-mm", type=float, default=25.0, help="trailing feed before the cut, in mm (default 25; raise this if the printed area doesn't fully eject/get cut)")
    parser.add_argument("--invert", action="store_true", help="flip pixel polarity (try this if feed/cut work but nothing visibly prints)")
    parser.add_argument("--trailing-invalidate", action="store_true", help="append a second Invalidate+Initialize after the job (try this if the printer only cuts when the NEXT job starts, not at the end of the current one)")
    parser.add_argument("--mode-byte", type=lambda s: int(s, 0), default=None, help="raw override for the 'various mode settings' (ESC i M) byte, e.g. 0x40 or 0x48 -- bypasses --no-cut")
    parser.add_argument("--advanced-byte", type=lambda s: int(s, 0), default=None, help="raw override for the 'advanced mode settings' (ESC i K) byte, e.g. 0x08 -- for testing candidate 'no chain printing' bits")
    parser.add_argument("--usb-uri", help="USB device URI from 'sudo lpinfo -v', e.g. usb://Brother/PT-P710BT?serial=XXXX (recommended transport; needs sudo)")
    parser.add_argument("--device", help="paired Bluetooth serial device name, e.g. PT-P710BT-SerialPort (from tools/list_bt_serial_ports.py) -- experimental, may not work on your printer")
    parser.add_argument("--device-path", help="full path override instead of --device, e.g. /dev/cu.PT-P710BT-SerialPort")
    parser.add_argument("--dry-run", action="store_true", help="don't send anything; just build the job")
    parser.add_argument("--out", help="write the raw command bytes to this file (useful with --dry-run, or to double-check a real send)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print a byte-level summary of the generated job")
    args = parser.parse_args()

    media = get_media(args.media)
    lines = generate(args.pattern, media, args.length)

    builder = RasterJobBuilder(
        media,
        auto_cut=not args.no_cut,
        invert=args.invert,
        feed_margin_mm=args.feed_margin_mm,
        trailing_invalidate=args.trailing_invalidate,
        mode_byte=args.mode_byte,
        advanced_byte=args.advanced_byte,
    )
    builder.add_lines(lines)
    data = builder.build()

    print(f"Pattern: {args.pattern}  Media: {media.name} ({media.print_dots} dots, "
          f"{media.print_bytes} bytes/line)  Lines: {len(lines)}  Job size: {len(data)} bytes"
          f"{'  [INVERTED]' if args.invert else ''}")

    if args.verbose:
        print(f"  invalidate+init+raster-mode preamble: {data[:206].hex()}")
        print(f"  print-information command:            {data[206:219].hex()}")
        print(f"  mode settings:                        {data[219:223].hex()}")
        print(f"  advanced settings:                    {data[223:227].hex()}")
        print(f"  feed amount (margin):                 {data[227:232].hex()}")
        print(f"  compression mode select:              {data[232:234].hex()}")
        print(f"  first raster line ('G' + len + data):  {data[234:234 + 3 + media.print_bytes].hex()}")
        expected_last = "0x40 (trailing invalidate+init)" if args.trailing_invalidate else "0x1a"
        print(f"  last byte (should be {expected_last}): {data[-1:].hex()}")

    if args.out:
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"Wrote {len(data)} bytes to {args.out}")

    if args.dry_run:
        print("--dry-run set: not sending anything to a printer.")
        return 0

    if args.usb_uri:
        print(f"Sending to {args.usb_uri} via the system usb backend...")
        send_via_usb(args.usb_uri, data, args.verbose)
        print("Sent. Check the printer.")
        return 0

    if args.device_path:
        device_path = args.device_path
    elif args.device:
        device_path = f"/dev/cu.{args.device}"
    else:
        raise SystemExit(
            "Specify --usb-uri (recommended, see 'sudo lpinfo -v'), or "
            "--device/--device-path for Bluetooth, or pass --dry-run."
        )

    print(f"Sending to {device_path} ...")
    send_to_device(device_path, data, args.verbose)
    print("Sent. Check the printer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
