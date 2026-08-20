# Brother PT-P710BT macOS CUPS Driver (unofficial)

An unofficial, community-written CUPS printer driver for the Brother
PT-P710BT label printer on macOS. It lets you print to the PT-P710BT from
any macOS application's normal Print dialog, like any other printer.

Not affiliated with or endorsed by Brother Industries, Ltd. "Brother" and
"P-touch" are trademarks of Brother Industries, Ltd.

**Transport status (from real hardware testing):** **USB works** and is
the recommended/supported transport. **Bluetooth (SPP) was confirmed
non-functional** on at least one PT-P710BT unit — macOS reported it as
"Connected", but no data was actually exchanged (verified with both this
driver and a plain `echo` to the serial device); that unit's Bluetooth
only pairs with phones/tablets, not a Mac. The Bluetooth backend is kept
in this repo in case it works for your unit or a future firmware update,
but treat it as experimental and try USB first.

**Protocol status:** confirmed printing real content over USB. Getting
there took two hardware-tested fixes beyond the initial implementation:
a missing "select compression mode" command (required before the printer
will treat raster data as valid image data at all -- without it, feed/cut
timing looked right but nothing printed) and a `feed_margin_mm` trailing
feed before the cut (there's a physical gap between the print head and
the cutter; a short job without enough trailing feed prints fine but the
printed area doesn't clear the cutter, so most of it stays stuck inside
the printer). Both are implemented now; alignment/width/cut-position
details are still being refined against real prints.

## How it works

This project adds a standard CUPS driver made of three pieces:

- **`ppd/Brother_PT-P710BT.ppd`** – describes the printer's supported tape
  widths and tells CUPS how to filter jobs for it.
- **`filter/rastertoptp710bt`** – a CUPS filter (Python) that reads the
  CUPS Raster data CUPS produces from your document and re-encodes it as
  Brother's raster-mode printer command protocol (`brother_ptraster/`).
  This part is transport-independent — the same command bytes go out over
  USB or Bluetooth.
- **Transport (delivers those bytes to the printer):**
  - **USB (recommended):** uses macOS's own built-in `usb` CUPS backend —
    nothing to install for this, just add the queue with a `usb://` device
    URI (see below).
  - **Bluetooth (experimental):** `backend/ptp710bt`, a CUPS backend
    (Python) that streams the command bytes over the Bluetooth serial
    ("SPP") connection macOS creates once you pair the printer, by writing
    to the `/dev/cu.*` device macOS exposes for the pairing.

```
Your app --print--> macOS print system --> CUPS's own PDF/PS-to-raster filters
   --> rastertoptp710bt (this project)
   --> usb backend (built into macOS)        --> USB --> PT-P710BT   [recommended]
   --> ptp710bt backend (this project) --> /dev/cu.<paired-name> --> Bluetooth SPP --> PT-P710BT   [experimental]
```

## ⚠️ Important: protocol validation status

`brother_ptraster/protocol.py` implements Brother's raster-mode command
set (Invalidate / Initialize / raster mode / print-information / raster
transfer / print-and-feed) based on the publicly documented command
structure that Brother uses consistently across its QL and PT thermal
label printer families. It has been confirmed to at least reach the
printer correctly over USB (Bluetooth SPP was confirmed to not deliver
data at all on the tested unit, unrelated to this protocol code); exact
print output (alignment, width, cut behavior) still needs visual
confirmation per pattern — see "Testing against real hardware" below.

If print output looks wrong, the most likely culprits are the
print-information command flags/media-type byte in `protocol.py`'s
`RasterJobBuilder.build()` or the head pin count/DPI in
`brother_ptraster/media.py` — compare against Brother's official Raster
Command Reference if you can get a copy, or against another open-source
Brother label printer driver.

## Requirements

- macOS with Python 3 available at `/usr/bin/env python3` (present by
  default on all supported macOS versions; no extra pip packages needed —
  everything here uses only the standard library).
- The PT-P710BT connected via USB (recommended) and/or paired over
  Bluetooth (experimental, System Settings > Bluetooth).

## Install

```sh
sudo ./install/install.sh
```

This copies:
- `brother_ptraster/` to `/usr/local/lib/brother_ptp710bt_driver/`
- `filter/rastertoptp710bt` to `/usr/libexec/cups/filter/`
- `backend/ptp710bt` to `/usr/libexec/cups/backend/` (only needed if you
  end up using the experimental Bluetooth path)
- `ppd/Brother_PT-P710BT.ppd` to `/Library/Printers/PPDs/Contents/Resources/`

and restarts `cupsd`. These paths were verified writable via `sudo` on a
current macOS release (Sonoma, Apple Silicon) despite the system volume
being sealed (SIP/SSV) — only `/usr/share` is off-limits, and this driver
doesn't need it (the filter is wired up via the PPD's `cupsFilter2` line,
not the global `/usr/share/cups/mime.types`).

To remove everything: `sudo ./install/uninstall.sh`.

## Add the print queue (USB, recommended)

1. Connect the PT-P710BT via USB and power it on.
2. Find its USB device URI (needs sudo to see USB printers):
   ```sh
   sudo lpinfo -v | grep -i usb
   ```
   Look for something like `direct usb://Brother/PT-P710BT?serial=XXXXXXXXX`.
3. Add the CUPS queue:
   ```sh
   sudo lpadmin -p PT-P710BT -E \
     -v 'usb://Brother/PT-P710BT?serial=XXXXXXXXX' \
     -P /Library/Printers/PPDs/Contents/Resources/Brother_PT-P710BT.ppd
   ```
   (replace the `-v` value with whatever step 2 found).
4. The printer should now show up in System Settings > Printers & Scanners
   and in every app's Print dialog.

## Add the print queue (Bluetooth, experimental)

Only try this if USB isn't an option and you want to test whether your
particular unit's Bluetooth actually works (unlike the unit this was
tested on).

1. Pair the PT-P710BT: System Settings > Bluetooth > (select PT-P710BT...).
2. Find its serial device name:
   ```sh
   python3 tools/list_bt_serial_ports.py
   ```
   Look for an entry hinting it's the printer, e.g. `PT-P710BT-SerialPort`.
3. Add the CUPS queue:
   ```sh
   sudo lpadmin -p PT-P710BT-BT -E \
     -v ptp710bt://PT-P710BT-SerialPort \
     -P /Library/Printers/PPDs/Contents/Resources/Brother_PT-P710BT.ppd
   ```
   (replace `PT-P710BT-SerialPort` with whatever step 2 found).
4. Test with `tools/test_print.py --device NAME` first (see below) before
   trusting the full CUPS queue — if that doesn't print, the CUPS queue
   won't either.

## Testing against real hardware

**Claude (this project's author) runs in an isolated cloud environment and
has no access to your physical Mac or printer** — there's no way to grant
it access by pairing the printer locally, so hardware testing has to be
done by you, on your Mac, using the standalone tool below. Paste the
output (or describe what printed) back into the conversation and the
protocol code can be corrected from that.

`tools/test_print.py` sends a test pattern directly to the printer,
bypassing CUPS entirely — this isolates protocol bugs (in this driver)
from CUPS/PPD configuration issues. It supports both transports.

```sh
# 1. Inspect the generated bytes without needing a printer:
python3 tools/test_print.py --media 12mm --pattern ruler --dry-run \
    --out /tmp/job.bin -v

# 2a. USB (recommended): find the device URI, then send (needs sudo):
sudo lpinfo -v | grep -i usb
sudo python3 tools/test_print.py --media 12mm --pattern solid \
    --usb-uri 'usb://Brother/PT-P710BT?serial=XXXXXXXXX'

# 2b. Bluetooth (experimental): find the paired device name, then send:
python3 tools/list_bt_serial_ports.py
python3 tools/test_print.py --media 12mm --pattern solid --device NAME

# 3. Once one pattern prints, run through the rest in this order:
#    solid        -- prints at all, full width?
#    ruler         -- tape width detected & centered correctly?
#    diagonal      -- any bit/byte-order bugs? (line should be straight)
#    checkerboard  -- fine black/white transitions clean?
#    border        -- edges clipped?
#    stripes       -- consecutive raster lines handled correctly?
```

Swap `--media` to whatever cassette you actually have loaded, and `--usb-uri`
or `--device` to whichever transport you're testing. Run
`python3 tools/test_print.py --help` for all options (label length, auto-cut
toggle, `--verbose` byte breakdown, etc.).

Once the raw protocol prints correctly, test the full CUPS path (install
the driver, add the queue, `lp -d PT-P710BT ...`) to confirm the CUPS
raster parsing/filter chain is also correct.

## Printing

- In the Print dialog, pick the **Tape Width** matching the cassette
  currently loaded (3.5/6/9/12/18/24 mm). The filter reads the actual page
  width from the job to select the tape width, so this also works if you
  define a custom paper size via "Manage Custom Sizes..." for a specific
  label length — just set the width to match your tape.
- **Cut Each Label** toggles auto-cut after each label.
- From the command line: `lp -d PT-P710BT -o media=mm12 file.pdf`.

## Known limitations

- **Bluetooth confirmed non-functional on at least one unit.** macOS
  showed the printer as "Connected" but no data was actually exchanged
  over the SPP serial port (confirmed both with this driver and a plain
  `echo` to the device) — that unit's Bluetooth appears to only pair with
  phones/tablets. Use USB. The Bluetooth backend remains in the repo for
  units where it might work.
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
  patterns.py              Test patterns (ruler/diagonal/etc.) for hardware bring-up
filter/rastertoptp710bt   CUPS filter entrypoint
backend/ptp710bt          CUPS backend entrypoint (Bluetooth SPP transport, experimental)
ppd/Brother_PT-P710BT.ppd PPD describing the printer to CUPS/macOS
install/                  install.sh / uninstall.sh
tools/list_bt_serial_ports.py  Helper to find the paired Bluetooth device's /dev/cu.* name
tools/test_print.py       Standalone hardware test tool (bypasses CUPS; supports USB and Bluetooth)
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
