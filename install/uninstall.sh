#!/bin/bash
# Removes the Brother PT-P710BT CUPS driver installed by install.sh.
#
# Usage:
#   sudo ./install/uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo $0" >&2
  exit 1
fi

LIB_DIR=/usr/local/lib/brother_ptp710bt_driver
FILTER=/usr/libexec/cups/filter/rastertoptp710bt
BACKEND=/usr/libexec/cups/backend/ptp710bt
PPD=/Library/Printers/PPDs/Contents/Resources/Brother_PT-P710BT.ppd

echo "==> Removing any print queues using this driver"
if command -v lpstat >/dev/null; then
  for queue in $(lpstat -v 2>/dev/null | grep 'ptp710bt://' | sed -E 's/device for ([^:]+):.*/\1/'); do
    echo "    removing queue: $queue"
    lpadmin -x "$queue" || true
  done
fi

echo "==> Removing driver files"
rm -f "$FILTER" "$BACKEND" "$PPD"
rm -rf "$LIB_DIR"

echo "==> Restarting cupsd"
launchctl kickstart -k system/org.cups.cupsd

echo "Done."
