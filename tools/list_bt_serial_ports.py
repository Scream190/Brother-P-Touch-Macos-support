#!/usr/bin/env python3
"""List paired Bluetooth serial ports on macOS, to help pick the right
device URI (``ptp710bt://<name>``) for the PT-P710BT CUPS queue.

Usage:
    python3 tools/list_bt_serial_ports.py

Pair the printer first (System Settings > Bluetooth > PT-P710BT...), then
run this script. It just lists /dev/cu.* entries; macOS only creates one for
a Bluetooth device once it has been paired at least once.
"""
import glob
import os
import sys


def main() -> int:
    if sys.platform != "darwin":
        print("This tool is only useful on macOS.", file=sys.stderr)

    entries = sorted(glob.glob("/dev/cu.*"))
    if not entries:
        print("No /dev/cu.* serial devices found.")
        print("Pair the PT-P710BT under System Settings > Bluetooth first.")
        return 1

    print("Available serial devices:\n")
    for path in entries:
        name = os.path.basename(path)[len("cu.") :]
        hint = "  <-- looks like the printer" if "PT-P710BT" in name or "Brother" in name else ""
        print(f"  {path}{hint}")
        if hint:
            print(f"      device URI: ptp710bt://{name}")

    print(
        "\nIf you don't see a 'looks like the printer' hint above, pair the "
        "printer in System Settings > Bluetooth, then re-run this script."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
