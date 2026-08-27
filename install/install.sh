#!/bin/bash
# Installs the Brother PT-P710BT / PT-P700 / PT-P750W CUPS drivers (one
# filter per model, a shared PPD per model, and the brother_ptraster
# Python library all three filters depend on). The PT-P710BT's Bluetooth
# backend is also installed, since only that model has Bluetooth.
#
# USB is the recommended/confirmed-working transport for all three models:
# it uses macOS's own built-in 'usb' CUPS backend, so no custom backend is
# needed for it. See README.md's "Other Brother P-touch models" section
# for what's confirmed on real hardware for PT-P700/PT-P750W (as of
# writing: only the PT-P710BT's protocol/tuning values are hardware-
# confirmed; the other two start from the same values as a reasonable
# guess, pending their own testing).
#
# Verified writable on modern macOS (SIP/Signed System Volume enabled) as of
# Sonoma on Apple Silicon: /usr/libexec/cups/{filter,backend} and /usr/local
# remain writable via sudo -- only /usr/share is part of the sealed system
# volume, and this driver doesn't need to touch it (it registers its filter
# via the PPD's cupsFilter2 line, not via /usr/share/cups/mime.*).
#
# The brother_ptraster Python library is vendored directly into
# /usr/libexec/cups/filter/ (next to the filter scripts) rather than under
# /usr/local: real hardware test found cupsd's filter processes run under a
# filesystem sandbox that raised ModuleNotFoundError trying to read
# /usr/local/lib, even running as root. The filter directory itself is
# provably readable (cupsd already executes filter scripts from there), so
# that's where its Python dependencies need to live too.
#
# Usage:
#   sudo ./install/install.sh
#
# After installing, add the printer queue -- either via System Settings >
# Printers & Scanners > Add Printer (no Terminal needed), or with lpadmin
# (see README.md), e.g. for the PT-P710BT:
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

FILTER_DIR=/usr/libexec/cups/filter
BACKEND_DIR=/usr/libexec/cups/backend
PPD_DIR=/Library/Printers/PPDs/Contents/Resources

echo "==> Installing brother_ptraster library to $FILTER_DIR/brother_ptraster"
rm -rf "$FILTER_DIR/brother_ptraster"
cp -R "$REPO_DIR/brother_ptraster" "$FILTER_DIR/brother_ptraster"
chown -R root:wheel "$FILTER_DIR/brother_ptraster"
find "$FILTER_DIR/brother_ptraster" -type f -name '*.py' -exec chmod 644 {} \;
find "$FILTER_DIR/brother_ptraster" -type d -exec chmod 755 {} \;

for model in rastertoptp710bt rastertoptp700 rastertoptp750w; do
  echo "==> Installing CUPS filter to $FILTER_DIR/$model"
  install -o root -g wheel -m 755 "$REPO_DIR/filter/$model" "$FILTER_DIR/$model"
done

echo "==> Installing CUPS backend to $BACKEND_DIR/ptp710bt"
install -o root -g wheel -m 755 "$REPO_DIR/backend/ptp710bt" "$BACKEND_DIR/ptp710bt"

mkdir -p "$PPD_DIR"
for ppd in Brother_PT-P710BT.ppd Brother_PT-P700.ppd Brother_PT-P750W.ppd; do
  echo "==> Installing PPD to $PPD_DIR/$ppd"
  install -o root -g wheel -m 644 "$REPO_DIR/ppd/$ppd" "$PPD_DIR/$ppd"
done

echo "==> Restarting cupsd"
launchctl kickstart -k system/org.cups.cupsd

cat <<EOF

Driver files installed for the PT-P710BT, PT-P700, and PT-P750W. Next
steps (USB, recommended):

1. Connect the printer via USB and power it on.
2. Add the print queue -- either:
   a) System Settings > Printers & Scanners > Add Printer (no Terminal),
      selecting the matching "Brother PT-..." entry; or
   b) via Terminal:
        sudo lpinfo -v | grep -i usb
      then (example for the PT-P710BT; swap the model name/PPD for a
      PT-P700 or PT-P750W):
        sudo lpadmin -p PT-P710BT -E \\
          -v 'usb://Brother/PT-P710BT?serial=XXXXXXXXX' \\
          -P "$PPD_DIR/Brother_PT-P710BT.ppd"
3. Print a test label:
     lp -d PT-P710BT -o media=mm12 /path/to/some/file.pdf

Bluetooth is also supported for the PT-P710BT specifically (custom
ptp710bt:// backend) but was confirmed NOT to work on at least one unit --
see README.md before relying on it. The PT-P700 has no Bluetooth/WiFi;
the PT-P750W's WiFi isn't supported by this project (USB only).

PT-P700/PT-P750W support is UNCONFIRMED on real hardware beyond initial
protocol research -- see README.md's "Other Brother P-touch models"
section before relying on it for production prints.

See README.md for troubleshooting and protocol validation notes.
EOF
