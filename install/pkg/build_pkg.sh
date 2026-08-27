#!/bin/bash
# Builds a double-click .pkg installer for the Brother PT-P710BT driver, so
# installing doesn't need the Terminal at all (beyond running this build
# script once, on a Mac -- that part can't be done from this Linux
# environment, since pkgbuild/productbuild are macOS-only tools).
#
# Must be run on macOS. Uses Apple's own pkgbuild/productbuild, which ship
# with the Xcode Command Line Tools (not full Xcode) -- if missing, run
# `xcode-select --install` once first.
#
# Usage:
#   ./install/pkg/build_pkg.sh
#
# Produces Brother_PT-P710BT_Driver.pkg in the repo root. From then on,
# installing is just: double-click the .pkg, click through the standard
# macOS Installer (which prompts for the admin password itself, via its
# own GUI, not Terminal), then add the printer via System Settings ->
# Printers & Scanners -> Add Printer -- no lpadmin needed, since the
# installed PPD shows up there by name for you to pick.
#
# It's unsigned (no paid Apple Developer ID certificate), so Gatekeeper
# will refuse to open it the first time -- right-click the .pkg -> Open
# (or System Settings > Privacy & Security > "Open Anyway" after the
# first blocked attempt) to allow it, same as any other indie/open-source
# installer.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This must be run on macOS (it uses pkgbuild/productbuild)." >&2
  exit 1
fi

for tool in pkgbuild productbuild; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool not found. Install the Xcode Command Line Tools first:" >&2
    echo "    xcode-select --install" >&2
    exit 1
  fi
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

ROOT_DIR="$BUILD_DIR/root"
FILTER_DIR="$ROOT_DIR/usr/libexec/cups/filter"
BACKEND_DIR="$ROOT_DIR/usr/libexec/cups/backend"
PPD_DIR="$ROOT_DIR/Library/Printers/PPDs/Contents/Resources"

mkdir -p "$FILTER_DIR" "$BACKEND_DIR" "$PPD_DIR"

echo "==> Staging payload"
cp -R "$REPO_DIR/brother_ptraster" "$FILTER_DIR/brother_ptraster"
find "$FILTER_DIR/brother_ptraster" -type f -name '*.py' -exec chmod 644 {} \;
find "$FILTER_DIR/brother_ptraster" -type d -exec chmod 755 {} \;
for model in rastertoptp710bt rastertoptp700 rastertoptp750w; do
  install -m 755 "$REPO_DIR/filter/$model" "$FILTER_DIR/$model"
done
install -m 755 "$REPO_DIR/backend/ptp710bt" "$BACKEND_DIR/ptp710bt"
for ppd in Brother_PT-P710BT.ppd Brother_PT-P700.ppd Brother_PT-P750W.ppd; do
  install -m 644 "$REPO_DIR/ppd/$ppd" "$PPD_DIR/$ppd"
done

VERSION="$(date +%Y.%m.%d)"
COMPONENT_PKG="$BUILD_DIR/component.pkg"

echo "==> Building component package (pkgbuild)"
pkgbuild \
  --root "$ROOT_DIR" \
  --identifier "com.github.brother-ptp710bt-driver" \
  --version "$VERSION" \
  --ownership recommended \
  --scripts "$REPO_DIR/install/pkg/scripts" \
  --install-location / \
  "$COMPONENT_PKG"

OUT_PKG="$REPO_DIR/Brother_PT-P710BT_Driver.pkg"

echo "==> Building installer (productbuild)"
productbuild \
  --distribution "$REPO_DIR/install/pkg/Distribution.xml" \
  --resources "$REPO_DIR/install/pkg/resources" \
  --package-path "$BUILD_DIR" \
  "$OUT_PKG"

echo
echo "Built: $OUT_PKG"
echo "Double-click it to install. Since it's unsigned, the first time you'll"
echo "need to right-click it and choose Open (Gatekeeper otherwise blocks"
echo "unsigned installers from a plain double-click)."
