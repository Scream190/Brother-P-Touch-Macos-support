#!/bin/bash
# Removes the Brother PT-P710BT / PT-P700 / PT-P750W CUPS drivers
# installed by install.sh.
#
# Usage:
#   sudo ./install/uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo $0" >&2
  exit 1
fi

FILTER_DIR=/usr/libexec/cups/filter
FILTER_LIB="$FILTER_DIR/brother_ptraster"
BACKEND=/usr/libexec/cups/backend/ptp710bt
PPD_DIR=/Library/Printers/PPDs/Contents/Resources
# Older installs (before the library moved out of /usr/local due to
# cupsd's filter sandbox not allowing it) may still have this; clean it up
# too if present.
OLD_LIB_DIR=/usr/local/lib/brother_ptp710bt_driver

echo "==> Removing any print queues using these drivers"
# Match by installed PPD (works for both the usb:// and ptp710bt:// device
# URI schemes) rather than by device-uri scheme alone.
if command -v lpstat >/dev/null; then
  for queue in $(lpstat -p 2>/dev/null | awk '{print $2}'); do
    if grep -qE 'Brother PT-P710BT|Brother PT-P700|Brother PT-P750W' "/etc/cups/ppd/$queue.ppd" 2>/dev/null; then
      echo "    removing queue: $queue"
      lpadmin -x "$queue" || true
    fi
  done
fi

echo "==> Removing driver files"
rm -f "$FILTER_DIR/rastertoptp710bt" "$FILTER_DIR/rastertoptp700" "$FILTER_DIR/rastertoptp750w" "$BACKEND"
rm -f "$PPD_DIR/Brother_PT-P710BT.ppd" "$PPD_DIR/Brother_PT-P700.ppd" "$PPD_DIR/Brother_PT-P750W.ppd"
rm -rf "$FILTER_LIB" "$OLD_LIB_DIR"

echo "==> Restarting cupsd"
launchctl kickstart -k system/org.cups.cupsd

echo "Done."
