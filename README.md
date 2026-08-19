# Brother PT-P710BT macOS CUPS Driver (unofficial)

An unofficial, community-written CUPS printer driver for the Brother
PT-P710BT Bluetooth label printer on macOS. It lets you print to the
PT-P710BT from any macOS application's normal Print dialog, like any other
printer.

Not affiliated with or endorsed by Brother Industries, Ltd. "Brother" and
"P-touch" are trademarks of Brother Industries, Ltd.

## How it works

The PT-P710BT is a Bluetooth Classic (SPP) label printer, not an
AirPrint/IPP printer, so macOS can't drive it out of the box. This project
adds a standard CUPS driver made of three pieces:

- **`ppd/Brother_PT-P710BT.ppd`** – describes the printer's supported tape
  widths and tells CUPS how to filter jobs for it.
- **`filter/rastertoptp710bt`** – a CUPS filter (Python) that reads the
  CUPS Raster data CUPS produces from your document and re-encodes it as
  Brother's raster-mode printer command protocol (`brother_ptraster/`).
- **`backend/ptp710bt`** – a CUPS backend (Python) that streams those
  command bytes to the printer over the Bluetooth serial ("SPP") connection
  macOS creates once you pair the printer — no IOBluetooth/CoreBluetooth
  code needed, it just writes to the `/dev/cu.*` device macOS exposes for
  the pairing.

```
Your app --print--> macOS print system --> CUPS's own PDF/PS-to-raster filters
   --> rastertoptp710bt (this project) --> ptp710bt backend (this project)
   --> /dev/cu.<paired-name> --> Bluetooth SPP --> PT-P710BT
```

## ⚠️ Important: protocol validation status

`brother_ptraster/protocol.py` implements Brother's raster-mode command
set (Invalidate / Initialize / raster mode / print-information / raster
transfer / print-and-feed) based on the publicly documented command
structure that Brother uses consistently across its QL and PT thermal
label printer families. **It has not been tested against a physical
PT-P710BT** in the environment this was written in.

Before trusting it with real labels:
1. Run the unit tests (`python3 -m pytest tests/`) — they check the byte
   framing logic without needing hardware.
2. Do a supervised first print on scrap tape, watching for: wrong tape
   width detected, image shifted/mirrored, missing/extra cut.
3. If something's off, the most likely culprits are the print-information
   command flags/media-type byte in `protocol.py`'s `RasterJobBuilder.build()`
   or the head pin count/DPI in `brother_ptraster/media.py` — compare
   against Brother's official Raster Command Reference if you can get a
   copy, or against another open-source Brother label printer driver.

## Requirements

- macOS with Python 3 available at `/usr/bin/env python3` (present by
  default on all supported macOS versions; no extra pip packages needed —
  everything here uses only the standard library).
- The PT-P710BT paired over Bluetooth (System Settings > Bluetooth).

## Install

```sh
sudo ./install/install.sh
```

This copies:
- `brother_ptraster/` to `/usr/local/lib/brother_ptp710bt_driver/`
- `filter/rastertoptp710bt` to `/usr/libexec/cups/filter/`
- `backend/ptp710bt` to `/usr/libexec/cups/backend/`
- `ppd/Brother_PT-P710BT.ppd` to `/Library/Printers/PPDs/Contents/Resources/`

and restarts `cupsd`. These paths were verified writable via `sudo` on a
current macOS release (Sonoma, Apple Silicon) despite the system volume
being sealed (SIP/SSV) — only `/usr/share` is off-limits, and this driver
doesn't need it (the filter is wired up via the PPD's `cupsFilter2` line,
not the global `/usr/share/cups/mime.types`).

To remove everything: `sudo ./install/uninstall.sh`.

## Pair the printer and add the queue

1. Pair the PT-P710BT: System Settings > Bluetooth > (select PT-P710BT...).
2. Find its serial device name:
   ```sh
   python3 tools/list_bt_serial_ports.py
   ```
   Look for an entry hinting it's the printer, e.g. `PT-P710BT-SerialPort`.
3. Add the CUPS queue:
   ```sh
   sudo lpadmin -p PT-P710BT -E \
     -v ptp710bt://PT-P710BT-SerialPort \
     -P /Library/Printers/PPDs/Contents/Resources/Brother_PT-P710BT.ppd
   ```
   (replace `PT-P710BT-SerialPort` with whatever step 2 found).
4. The printer should now show up in System Settings > Printers & Scanners
   and in every app's Print dialog.

## Printing

- In the Print dialog, pick the **Tape Width** matching the cassette
  currently loaded (3.5/6/9/12/18/24 mm). The filter reads the actual page
  width from the job to select the tape width, so this also works if you
  define a custom paper size via "Manage Custom Sizes..." for a specific
  label length — just set the width to match your tape.
- **Cut Each Label** toggles auto-cut after each label.
- From the command line: `lp -d PT-P710BT -o media=mm12 file.pdf`.

## Known limitations

- **Continuous tape only** in the tape-width presets; die-cut label
  cassettes aren't specifically modeled (they'd need their own PPD entries
  with fixed label lengths and gap-detection behavior, which this project
  doesn't attempt).
- **No status feedback**: the backend doesn't read the printer's status
  responses (e.g. "out of tape", "cover open"), so such errors won't be
  reported back into macOS's print queue — check the printer itself if a
  job seems to vanish without printing.
- **Uncompressed raster only**: the CUPS raster reader
  (`brother_ptraster/cups_raster.py`) doesn't implement CUPS's row
  compression, which is fine for the standard `cupsFilter2` chain this PPD
  uses (it produces uncompressed 1-bit rows), but would need extending if
  you changed the filter chain.
- **Width detection tolerance**: `nearest_media()` snaps the job's page
  width to the closest supported tape width within 1.5mm; a print job with
  a very wrong page width fails loudly instead of printing off-tape.

## Repository layout

```
brother_ptraster/       Protocol library (no CUPS/macOS dependency; unit-testable)
  media.py               Tape width table, print-head geometry
  protocol.py             Brother raster-mode command encoder
  cups_raster.py          Minimal CUPS Raster page-stream reader
filter/rastertoptp710bt   CUPS filter entrypoint
backend/ptp710bt          CUPS backend entrypoint (Bluetooth SPP transport)
ppd/Brother_PT-P710BT.ppd PPD describing the printer to CUPS/macOS
install/                  install.sh / uninstall.sh
tools/list_bt_serial_ports.py  Helper to find the paired device's /dev/cu.* name
tests/                    Unit tests (no hardware required)
```

## Development

```sh
python3 -m pip install pytest
python3 -m pytest tests/ -v
```

The filter and backend also run fine straight from a git checkout (without
`install.sh`) for local testing — they fall back to importing
`brother_ptraster` via a relative path when the installed copy under
`/usr/local/lib/brother_ptp710bt_driver` isn't present.

If you have `cupstestppd` (ships with CUPS), sanity-check the PPD:
```sh
cupstestppd ppd/Brother_PT-P710BT.ppd
```

## License

MIT — see [LICENSE](LICENSE).
