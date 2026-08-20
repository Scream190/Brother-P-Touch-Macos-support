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
# Match by installed PPD (works for both the usb:// and ptp710bt:// device
# URI schemes) rather than by device-uri scheme alone.
if command -v lpstat >/dev/null; then
  for queue in $(lpstat -p 2>/dev/null | awk '{print $2}'); do
    if grep -q 'Brother PT-P710BT' "/etc/cups/ppd/$queue.ppd" 2>/dev/null; then
      echo "    removing queue: $queue"
      lpadmin -x "$queue" || true
    fi
  done
fi

echo "==> Removing driver files"
rm -f "$FILTER" "$BACKEND" "$PPD"
rm -rf "$LIB_DIR"

echo "==> Restarting cupsd"
launchctl kickstart -k system/org.cups.cupsd

echo "Done."
