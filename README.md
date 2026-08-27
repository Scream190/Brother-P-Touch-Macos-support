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

**Protocol status:** confirmed printing correctly, cutting correctly, and
with correct polarity over USB, via the full real CUPS print path (not
just the direct test tool). Getting there took several hardware-tested
fixes beyond the initial implementation:
- a missing "select compression mode" command (required before the
  printer will treat raster data as valid image data at all -- without
  it, feed/cut timing looked right but nothing printed)
- a `feed_margin_mm` trailing feed before the cut (there's a physical gap
  between the print head and the cutter; a short job without enough
  trailing feed prints fine but the printed area doesn't clear the
  cutter, so most of it stays stuck inside the printer). Confirmed on real
  hardware that 5mm (the current default) is enough to fully eject and
  cut cleanly -- the original 25mm default was an untested, overly
  generous guess
- bit 0x08 of the "advanced mode settings" byte, required for the printer
  to actually cut at the end of a job -- without it, the printer would
  print/feed correctly but only cut once a *next* job's Invalidate
  sequence arrived, as if 0x00 there means "more labels may be coming"
- the PPD's ColorModel used `cupsColorSpace 0` (CUPS_CSPACE_W, a
  luminance/"0=black" convention) instead of `3` (CUPS_CSPACE_K, an ink
  convention where 1=black) -- printed output was a photo negative of the
  intended content (e.g. a solid black label with the actual text
  showing through as unprinted gaps) until this was fixed
- a bug in the CUPS Raster header parser: it stopped at `cupsRowStep`
  (matching the shorter, legacy v1 page header) instead of reading the
  full ~1796-byte v2 header real RaS2/RaS3 streams actually use, which
  misaligned every field read after the header
- the filter's Python library (`brother_ptraster/`) had to be vendored
  next to the filter script under `/usr/libexec/cups/filter/` rather than
  under `/usr/local`: cupsd runs filters under a filesystem sandbox that
  doesn't allow reading `/usr/local`, even as root
- printed text came out both rotated and mirrored. Root cause: the PPD
  declared pages narrow-tall (width = tape width, height = a default
  label length), so macOS's `cgpdftoraster` applied its own
  `PreferredRotation` to fit text using the long axis as line-length
  instead of squeezing it into the narrow width. Fixed by declaring pages
  WIDE instead (width = label length, height = tape width) so
  cgpdftoraster renders normal horizontal text directly; the filter now
  always transposes the resulting raster grid (CUPS's rows run along the
  now-swapped length axis, but the printer needs lines along the
  tape-width axis) and applies an additional confirmed-correct mirror on
  top (see the PPD's `*ImageRotate`/`*ImageMirror` options, still
  adjustable if you want the old vertical-reading orientation instead)
- the print area was consistently off-center across the tape width by
  about 0.5mm (~0mm margin on one edge, ~0.5mm on the other) -- the
  print head's real alignment to the tape isn't perfectly centered on
  this unit. Fixed with a small, hardware-confirmed trim
  (`media.PIN_ALIGNMENT_TRIM_DOTS`)
- the PPD's `*CustomPageSize True` PostScript snippet was missing the
  standard `pop pop pop` prefix required by the CUPS custom-page-size
  protocol (see cups' PPD spec) -- without it, any *Custom* page size
  (as opposed to a named preset like mm12) got badly corrupted page
  geometry, confirmed on real hardware as content coming out
  scaled/positioned as if rotated. Named presets were never affected,
  since they declare `PageSize` directly without this code path.

All fixed and covered by regression tests.

**Minimum label length:** the printer enforces a minimum total length per
label (content + trailing margin) of roughly 24mm -- asking for less just
makes it pad the difference with extra blank feed before the cut, rather
than actually printing a shorter label. Only matters for very short
prints/labels; real-world content (logos, multi-line text, QR codes) is
almost always longer than this already.

**Leading cleanup (every job starting with its own feed+cut cycle) was
tried and abandoned.** Three structurally different implementations were
tested on real hardware, all failed:
1. a 0-line cleanup segment concatenated with the real job into one
   transmission -- hung the printer/USB connection, needed a full Mac
   restart to recover
2. the same 0-line segment sent as a genuinely separate transmission with
   a pause before the real job -- still hung (recovered with just an
   unplug/replug that time)
3. real blank raster lines instead of declaring 0 (to rule out
   `raster_count=0` as the trigger) -- didn't hang, but put the printer
   into an error state (blinking red LED) without feeding or cutting

Three different failure modes across three different framings is a real
pattern: this printer's firmware doesn't handle a standalone feed+cut job
preceding a real one, at least not in any of the ways tried here. Not
being pursued further. Off by default; the CUPS filter doesn't use it,
and the code (`RasterJobBuilder.leading_cleanup` /
`build_cleanup_segment()`, `tools/test_print.py --leading-cleanup`) is
kept only as a record of what was tried.

The practical goal behind it — minimizing blank tape at the start of a
label — is instead addressed by reducing `feed_margin_mm`: the "leading"
blank tape on a print is really the *previous* job's trailing margin,
left attached at wherever that job's cut landed. Shrinking the trailing
margin shrinks both ends at once, safely.

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
- Optional, only for `tools/check_media.py` (auto media-width detection —
  see below): `pip3 install pyusb libusb-package`. `libusb-package` bundles
  prebuilt libusb binaries, so Homebrew isn't required. Not needed for
  printing itself.

## Install

```sh
sudo ./install/install.sh
```

This copies:
- `filter/rastertoptp710bt` to `/usr/libexec/cups/filter/`
- `brother_ptraster/` to `/usr/libexec/cups/filter/brother_ptraster/` (the
  filter's Python dependency, vendored right next to it rather than under
  `/usr/local` -- real hardware test found cupsd runs filters under a
  filesystem sandbox that raised `ModuleNotFoundError` trying to read
  `/usr/local/lib`, even running as root)
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
  currently loaded (3.5/6/9/12/18/24 mm).
- **Cut Each Label** toggles auto-cut after each label.
- From the command line: `lp -d PT-P710BT -o media=mm12 file.pdf`.

### Custom label length

The 6 Tape Width presets each carry a fixed default length (~40mm) --
that's just a convenient starting point, not a hard limit: continuous
tape has no fixed length, and the filter prints however much content it
actually receives, regardless of the preset's nominal size.

To set your own length: **Paper Size → Manage Custom Sizes... → +** (in
the Print dialog's paper size dropdown), then set **Width** to your
desired label length and **Height** to match your loaded tape width --
this PPD declares pages WIDE (Width = label length, Height = tape width),
which is why it's Width you change here, not Height. Give it a name and
click OK; it then shows up as a regular entry in the Paper Size list for
this and future print jobs, without needing to redo this each time.

There's no separate "automatic length" option: the driver doesn't
truncate or pad based on the page size you picked, so a custom size just
needs to be *long enough* for your content -- some extra blank space at
the end simply becomes a slightly longer trailing margin, not wasted
effort. There is a real hardware floor, though -- see "Minimum label
length" above.

**Match the Custom size to your PDF's actual page size, not just "long
enough".** CUPS scales a PDF to fit whatever page size you tell it to
print at -- if your PDF's own page size doesn't match, the content gets
scaled and/or cropped instead of printing at its intended size (confirmed
on real hardware: a PDF with page size 156×34pt = 55×12mm printed with
`-o media=mm12`, which defaults to a ~40mm-long page, came out visibly
wrong/incomplete). Check your PDF's actual page size (e.g. its MediaBox
in points) and set the Custom size's Width to match, converting to mm if
needed (`points / 72 * 25.4`).

## Checking the loaded media (auto-detection)

Like the "check media" button in Brother's own P-touch software,
`tools/check_media.py` queries the printer directly and reports what tape
is actually loaded right now (width, type, and any errors like "cover
open" or "no media"), so you don't have to guess or remember what's in it.

This is a standalone tool, separate from the CUPS print path — it needs to
*read* the printer's reply, which the normal CUPS `usb` backend doesn't
support (see `brother_ptraster/usb_transport.py` for why: it talks to the
USB device directly via `pyusb`/`libusb` instead). It requires the extra
`pyusb`/`libusb` install from Requirements above; nothing else does.

```sh
pip3 install pyusb libusb-package   # libusb-package needs no Homebrew
python3 tools/check_media.py
# or, with more than one Brother USB device attached:
python3 tools/check_media.py --serial 000J4G980818
```

It prints the decoded status (media width/type, tape/text color, errors)
and, if the width matches one of this driver's supported presets, the
`-o media=...` value to pass to `lp`.

**Tape/text color is not hardware-confirmed yet** (unlike width, which was
tested and matched exactly) — the byte offsets/value tables come from the
generally-documented Brother status packet layout used across their QL/PT
printer family, but haven't been checked against this unit. If the color
`check_media.py` reports doesn't match your tape's actual color, say so
(and ideally what the actual color is) so `brother_ptraster/status.py`'s
`TAPE_COLORS`/`TEXT_COLORS` tables can be corrected.

**Not wired into the CUPS print path itself, deliberately.** CUPS runs a
job's filter and backend concurrently (piped together), and the backend
often opens its USB connection before any data has even arrived --
adding our own direct USB status query into that same window risked a
conflict over the device. This printer's USB stack has shown itself
prone to hangs/error states under much smaller provocations (see the
leading_cleanup saga in git history), so this check intentionally stays
completely separate from any real print job's own USB transmission.

For a one-command "check, then print" workflow that keeps that
separation, use `tools/print_with_check.py` instead of `lp` directly --
it runs the same check as `check_media.py` to completion (fully closing
that connection) and only afterwards, as a separate step, calls `lp`:

```sh
python3 tools/print_with_check.py --media mm12 label.pdf
# skip the check (e.g. if pyusb/libusb isn't installed):
python3 tools/print_with_check.py --media mm12 --skip-check label.pdf
# pass extra CUPS options through to lp, and/or disambiguate by serial:
python3 tools/print_with_check.py --media mm18 --serial 000J4G980818 \
    --option AutoCut=False label.pdf
# a PDF sized for something other than a preset's default ~40mm length
# (see "Custom label length" above) needs --tape-width-mm too, since the
# width can't be inferred from a non-preset --media value:
python3 tools/print_with_check.py --media Custom.55x12mm --tape-width-mm 12 label.pdf
```

It refuses to print (before anything is sent to the printer at all) if
the loaded tape's width doesn't match, telling you what's actually
loaded instead.

If it fails with a "busy"/"access" error: something else (a stale print
job, or macOS's own generic USB-printing support) currently holds the USB
interface open. Try unplugging and replugging the printer immediately
before running the query, with no print job in progress.

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
- **No status feedback during printing**: the CUPS backend itself doesn't
  read the printer's status responses (e.g. "out of tape", "cover open"),
  so such errors won't be reported back into macOS's print queue — check
  the printer itself if a job seems to vanish without printing. You *can*
  query status manually, separately from printing, with
  `tools/check_media.py` (see "Checking the loaded media" above) — it's
  just not wired into the print path yet.
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
  orient.py                Raster page rotate/mirror transforms
  status.py                Decoder for the printer's 32-byte status packet
  usb_transport.py         Direct (bidirectional) USB transport, for status queries only
  patterns.py              Test patterns (ruler/diagonal/etc.) for hardware bring-up
filter/rastertoptp710bt   CUPS filter entrypoint
backend/ptp710bt          CUPS backend entrypoint (Bluetooth SPP transport, experimental)
ppd/Brother_PT-P710BT.ppd PPD describing the printer to CUPS/macOS
install/                  install.sh / uninstall.sh
tools/list_bt_serial_ports.py  Helper to find the paired Bluetooth device's /dev/cu.* name
tools/test_print.py       Standalone hardware test tool (bypasses CUPS; supports USB and Bluetooth)
tools/check_media.py      Standalone "check media" tool (queries loaded tape over direct USB)
tools/print_with_check.py Check media, then lp -- as two separate steps, never concurrent
tools/decode_status.py    Decode a hex-dumped 32-byte status packet by hand
tests/                    Unit tests (no hardware required)
```

## Development

```sh
python3 -m pip install pytest
python3 -m pytest tests/ -v
```

The filter and backend also run fine straight from a git checkout (without
`install.sh`) for local testing — they fall back to importing
`brother_ptraster` via a relative path when there's no sibling
`brother_ptraster/` directory next to the installed filter script.

If you have `cupstestppd` (ships with CUPS), sanity-check the PPD:
```sh
cupstestppd ppd/Brother_PT-P710BT.ppd
```

## License

MIT — see [LICENSE](LICENSE).
