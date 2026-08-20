#!/bin/bash
# Installs the Brother PT-P710BT CUPS driver (filter, PPD, the Bluetooth
# backend, and the brother_ptraster Python library the filter/backend
# depend on).
#
# USB is the recommended/confirmed-working transport: it uses macOS's own
# built-in 'usb' CUPS backend, so no custom backend is needed for it. The
# custom ptp710bt Bluetooth backend is still installed for anyone whose
# unit does pair correctly, but Bluetooth SPP was confirmed NON-functional
# on at least one PT-P710BT (it only pairs with phones); see README.md.
#
# Verified writable on modern macOS (SIP/Signed System Volume enabled) as of
# Sonoma on Apple Silicon: /usr/libexec/cups/{filter,backend} and /usr/local
# remain writable via sudo -- only /usr/share is part of the sealed system
# volume, and this driver doesn't need to touch it (it registers its filter
# via the PPD's cupsFilter2 line, not via /usr/share/cups/mime.*).
#
# Usage:
#   sudo ./install/install.sh
#
# After installing, add the printer queue with lpadmin (see README.md), e.g.:
#   sudo lpadmin -p PT-P710BT -E \
#     -v 'usb://Brother/PT-P710BT?serial=XXXXXXXXX' \
#     -P /Library/Printers/PPDs/Contents/Resources/Brother_PT-P710BT.ppd
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This driver only supports macOS." >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo $0" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LIB_DIR=/usr/local/lib/brother_ptp710bt_driver
FILTER_DIR=/usr/libexec/cups/filter
BACKEND_DIR=/usr/libexec/cups/backend
PPD_DIR=/Library/Printers/PPDs/Contents/Resources

echo "==> Installing brother_ptraster library to $LIB_DIR"
mkdir -p "$LIB_DIR"
rm -rf "$LIB_DIR/brother_ptraster"
cp -R "$REPO_DIR/brother_ptraster" "$LIB_DIR/brother_ptraster"
chown -R root:wheel "$LIB_DIR"
find "$LIB_DIR" -type f -name '*.py' -exec chmod 644 {} \;
find "$LIB_DIR" -type d -exec chmod 755 {} \;

echo "==> Installing CUPS filter to $FILTER_DIR/rastertoptp710bt"
install -o root -g wheel -m 755 "$REPO_DIR/filter/rastertoptp710bt" "$FILTER_DIR/rastertoptp710bt"

echo "==> Installing CUPS backend to $BACKEND_DIR/ptp710bt"
install -o root -g wheel -m 755 "$REPO_DIR/backend/ptp710bt" "$BACKEND_DIR/ptp710bt"

echo "==> Installing PPD to $PPD_DIR/Brother_PT-P710BT.ppd"
mkdir -p "$PPD_DIR"
install -o root -g wheel -m 644 "$REPO_DIR/ppd/Brother_PT-P710BT.ppd" "$PPD_DIR/Brother_PT-P710BT.ppd"

echo "==> Restarting cupsd"
launchctl kickstart -k system/org.cups.cupsd

cat <<EOF

Driver files installed. Next steps (USB, recommended):

1. Connect the PT-P710BT via USB and power it on.
2. Find its USB device URI:
     sudo lpinfo -v | grep -i usb
3. Add the print queue (replace the -v value with what step 2 found):
     sudo lpadmin -p PT-P710BT -E \\
       -v 'usb://Brother/PT-P710BT?serial=XXXXXXXXX' \\
       -P "$PPD_DIR/Brother_PT-P710BT.ppd"
4. Print a test label:
     lp -d PT-P710BT -o media=mm12 /path/to/some/file.pdf

Bluetooth is also supported (custom ptp710bt:// backend) but was confirmed
NOT to work on at least one PT-P710BT unit -- see README.md before relying
on it.

See README.md for troubleshooting and protocol validation notes.
EOF
