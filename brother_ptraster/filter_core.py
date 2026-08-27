"""Shared CUPS filter logic for the whole PT-P700/PT-P750W/PT-P710BT family.

Brother documents the raster command protocol for P750W and P710BT in one
combined reference, and third-party drivers treat P700 as a standard
member of the same PT-series raster family (see README.md's "Other
Brother P-touch models" section) -- so this logic (CUPS Raster parsing,
orientation, automatic length, the raster-mode command framing) is
genuinely shared across all three.

What ISN'T shared: the pin-alignment trim and feed/leading margins are
mechanical properties of one specific physical unit, confirmed only via
real hardware testing (see media.PIN_ALIGNMENT_TRIM_DOTS and
filter/rastertoptp710bt's DEFAULT_MARGIN_MM for how that was done for the
PT-P710BT) -- there is no reason to assume they transfer exactly to a
different unit, let alone a different model. Each model gets its own thin
filter script (filter/rastertoptp710bt, filter/rastertoptp700,
filter/rastertoptp750w) supplying its own name, media table (via
media.build_media_table), and margin, then calling run() here -- so each
model's tuning lives in one small, obviously-model-specific place, while
bugfixes to the shared logic (like the orientation transpose, or
Automatic Length) only need to happen once.
"""

from __future__ import annotations

import sys
from typing import BinaryIO, List

from .cups_raster import read_pages, RasterFormatError
from .media import DPI, nearest_media
from .orient import transform_page, trim_blank_rows
from .protocol import RasterJobBuilder

# PPD *ImageRotate choice names -> degrees clockwise.
ROTATE_CHOICES = {"None": 0, "Rotate90": 90, "Rotate180": 180, "Rotate270": 270}


def parse_options(options_str: str) -> dict:
    """Parse CUPS's space-separated ``key=value`` option string.

    CUPS quotes values containing spaces with single quotes, e.g.
    ``media=mm12 title='My Label'``.
    """
    opts = {}
    token = ""
    in_quotes = False
    tokens = []
    for ch in options_str:
        if ch == "'":
            in_quotes = not in_quotes
            token += ch
        elif ch == " " and not in_quotes:
            if token:
                tokens.append(token)
            token = ""
        else:
            token += ch
    if token:
        tokens.append(token)

    for tok in tokens:
        if "=" in tok:
            key, _, value = tok.partition("=")
            opts[key] = value.strip("'")
        else:
            opts[tok] = "True"
    return opts


def run(
    filter_name: str,
    media_table: dict,
    default_margin_mm: float,
    argv: List[str],
    stdin: BinaryIO,
    stdout: BinaryIO,
) -> int:
    """Run the CUPS filter's main logic. See the per-model filter scripts
    for the standard ``if __name__ == "__main__"`` wiring that calls this
    with ``sys.argv``/``sys.stdin.buffer``/``sys.stdout.buffer``.
    """

    def log(level: str, message: str) -> None:
        sys.stderr.write(f"{level}: [{filter_name}] {message}\n")
        sys.stderr.flush()

    if len(argv) not in (6, 7):
        log("ERROR", f"usage: {argv[0]} job-id user title copies options [file]")
        return 1

    _job_id, _user, _title, copies_str, options_str = argv[1:6]
    infile = argv[6] if len(argv) == 7 else None

    try:
        copies = max(1, int(copies_str))
    except ValueError:
        copies = 1

    opts = parse_options(options_str)
    auto_cut = opts.get("AutoCut", "True") != "False"
    rotate = ROTATE_CHOICES.get(opts.get("ImageRotate", "None"), 0)
    mirror = opts.get("ImageMirror", "False") == "True"
    auto_length = opts.get("AutoLength", "True") != "False"

    log("INFO", f"auto_cut={auto_cut} rotate={rotate} mirror={mirror} auto_length={auto_length} copies={copies}")

    src = open(infile, "rb") if infile else stdin

    try:
        pages = list(read_pages(src))
    except RasterFormatError as exc:
        log("ERROR", f"failed to parse CUPS raster input: {exc}")
        return 1
    finally:
        if infile:
            src.close()

    if not pages:
        log("ERROR", "input contained no pages")
        return 1

    for copy in range(copies):
        for page_num, page in enumerate(pages, start=1):
            # Use the resolution the rasterizer actually used, not an
            # assumed constant: real hardware test found cgpdftoraster
            # used 100dpi despite the PPD declaring 180dpi as the only
            # resolution (a missing *OpenUI/*CloseUI wrapper around
            # *Resolution meant CUPS wasn't recognizing it as a real
            # option). We only know how to send raster data dot-for-dot to
            # the printer's fixed 180dpi head, so if the actual resolution
            # doesn't match, the safe thing is to refuse rather than print
            # at the wrong physical size.
            dpi_x, dpi_y = page.hw_resolution
            if dpi_x != DPI or dpi_y != DPI:
                log(
                    "ERROR",
                    f"page {page_num}: job was rasterized at {dpi_x}x{dpi_y}dpi, "
                    f"but this driver only supports {DPI}dpi (the printer's native "
                    f"resolution) -- check the PPD's Resolution option/CUPS config",
                )
                return 1

            # Mandatory structural transpose + mirror: the PPD declares
            # pages WIDE (Width = label length, Height = tape width) so
            # cgpdftoraster renders normal horizontal text instead of
            # auto-rotating for vertical reading (see the PPD's comment on
            # *PageSize for why). But that means CUPS hands us rows that
            # run along the LENGTH axis (page.width, potentially thousands
            # of dots) with only page.height (tens of dots) of them -- the
            # opposite of what the printer needs (many lines, each
            # spanning the tape width). Transposing unconditionally fixes
            # that; it is not a user preference, just how this page
            # geometry has to be unpacked. The mirror is baked in here
            # (not left to the PPD's *ImageMirror default) because that
            # default was found, on real hardware, not to reliably take
            # effect: cupsd/lpadmin can leave a stale cached copy of the
            # queue's PPD (a different *DefaultImageMirror than the
            # current source PPD file) even after `lpadmin -p ... -P ...`
            # on an existing queue -- confirmed by inspecting
            # /etc/cups/ppd/<queue>.ppd directly. Baking the fix into the
            # filter's own logic sidesteps that entirely.
            rows, width = transform_page(page.rows, page.width, rotate=90, mirror=True)

            # User-selectable rotate/mirror (see PPD *ImageRotate/
            # *ImageMirror) apply ON TOP of the above, e.g. to flip back to
            # vertical-reading orientation. Off by default, so this is a
            # no-op unless the job's options explicitly ask for it.
            if rotate or mirror:
                rows, width = transform_page(rows, width, rotate=rotate, mirror=mirror)

            # "Automatic length": a job's PageSize is an upper bound on
            # how much tape a label CAN use, not how much it actually
            # uses -- most apps place content at the top of the page and
            # leave the rest blank rather than stretching it to fill an
            # oversized size. Trimming that unused canvas here means
            # picking a big, generous Custom size (see README.md) and
            # getting a label sized to the actual content, without CUPS
            # ever needing to know the real length up front. On by
            # default; disable (PPD *AutoLength/Automatic Length) if you
            # deliberately want the full page size printed, blank space
            # included.
            if auto_length:
                rows = trim_blank_rows(rows)
                if not rows:
                    log("ERROR", f"page {page_num}: page is entirely blank, nothing to print")
                    return 1

            width_mm = width / dpi_x * 25.4
            try:
                media = nearest_media(width_mm, table=media_table)
            except ValueError as exc:
                log("ERROR", f"page {page_num}: {exc}")
                return 1

            # Symmetric leading/trailing blank around the content: without
            # an explicit leading_margin_mm, the blank tape before a label
            # is purely accidental (whatever the PREVIOUS job's own margin
            # happened to leave attached at its cut point) -- confirmed on
            # real hardware to be visibly off-center (~10mm leading vs
            # ~5mm trailing on one test). Matching it to the trailing
            # margin makes every label self-centered regardless of print
            # history. See RasterJobBuilder.leading_margin_mm.
            builder = RasterJobBuilder(
                media,
                auto_cut=auto_cut,
                feed_margin_mm=default_margin_mm,
                leading_margin_mm=default_margin_mm,
            )
            for row in rows:
                if len(row) >= media.print_bytes:
                    line = row[: media.print_bytes]
                else:
                    line = row + b"\x00" * (media.print_bytes - len(row))
                builder.add_line(line)
            stdout.write(builder.build())
            log(
                "DEBUG",
                f"copy {copy + 1}/{copies} page {page_num}/{len(pages)}: "
                f"media={media.name} {len(rows)} lines",
            )

    stdout.flush()
    return 0
