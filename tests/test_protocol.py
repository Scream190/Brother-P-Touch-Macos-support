"""Unit tests for brother_ptraster.protocol and .media.

These test the byte-level command framing against the documented Brother
raster-mode protocol; they do not require a physical printer. See
README.md for how to validate against real hardware.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.media import get_media, nearest_media, HEAD_PINS, BYTES_PER_LINE, PIN_ALIGNMENT_TRIM_DOTS
from brother_ptraster.protocol import RasterJobBuilder, build_status_request, pack_bitmap_row, ESC


def test_media_table_widths_are_centered_within_head():
    # "Centered" here allows for PIN_ALIGNMENT_TRIM_DOTS -- a small,
    # real-hardware-CONFIRMED fine-tune shift off perfect centering (see
    # media.py) -- clamped so it never pushes the active area off either
    # edge of the head.
    for media in get_media("12mm"), get_media("24mm"), get_media("3.5mm"):
        assert media.print_dots <= HEAD_PINS
        assert media.pin_offset + media.print_dots <= HEAD_PINS
        assert media.pin_offset >= 0
        remaining = HEAD_PINS - media.print_dots
        expected = max(0, min(remaining, remaining // 2 + PIN_ALIGNMENT_TRIM_DOTS))
        assert media.pin_offset == expected


def test_24mm_uses_full_head():
    media = get_media("24mm")
    assert media.print_dots == HEAD_PINS
    assert media.pin_offset == 0
    assert media.print_bytes == BYTES_PER_LINE


def test_ppd_option_matches_the_ppds_pagesize_choice_names():
    # The PPD's *PageSize choice names are "mmN" (mm3.5, mm6, mm9, mm12,
    # mm18, mm24) -- the reverse of MediaSpec.name ("3.5mm", "12mm", ...).
    # A tool reporting a "-o media=..." value to the user must use this
    # form, not .name, or `lp` will reject/ignore the option.
    expected = {
        "3.5mm": "mm3.5", "6mm": "mm6", "9mm": "mm9",
        "12mm": "mm12", "18mm": "mm18", "24mm": "mm24",
    }
    for name, ppd_option in expected.items():
        assert get_media(name).ppd_option == ppd_option


def test_nearest_media_matches_exact_widths():
    for name in ("3.5mm", "6mm", "9mm", "12mm", "18mm", "24mm"):
        media = get_media(name)
        assert nearest_media(media.width_mm).name == name


def test_nearest_media_snaps_within_tolerance():
    media = nearest_media(12.3)
    assert media.name == "12mm"


def test_nearest_media_rejects_far_off_widths():
    try:
        nearest_media(50)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unsupported width")


def test_build_starts_with_invalidate_and_initialize():
    media = get_media("12mm")
    builder = RasterJobBuilder(media, leading_cleanup=False)
    builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()

    assert data[:200] == b"\x00" * 200
    assert data[200:202] == bytes([ESC, 0x40])  # Initialize
    assert data[202:206] == bytes([ESC, 0x69, 0x61, 0x01])  # raster mode


def test_print_information_command_encodes_line_count():
    media = get_media("12mm")
    builder = RasterJobBuilder(media, leading_cleanup=False)
    for _ in range(5):
        builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()

    pic_start = 206
    assert data[pic_start : pic_start + 3] == bytes([ESC, 0x69, 0x7A])
    n1, n2, n3, n4 = data[pic_start + 3 : pic_start + 7]
    assert n1 == 0x8E
    assert n2 == media.media_type
    assert n3 == int(media.width_mm)
    assert n4 == 0
    raster_count = int.from_bytes(data[pic_start + 7 : pic_start + 11], "little")
    assert raster_count == 5


def test_job_ends_with_print_and_feed():
    media = get_media("12mm")
    builder = RasterJobBuilder(media)
    builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()
    assert data[-1:] == b"\x1a"


def test_leading_cleanup_defaults_off():
    # Confirmed on real hardware to hang the printer/USB connection (see
    # __init__ for details) -- must default to False.
    media = get_media("12mm")
    assert RasterJobBuilder(media).leading_cleanup is False


def test_build_never_bakes_in_the_cleanup_segment():
    # A same-transmission "0-line segment + real segment" concatenation was
    # confirmed on real hardware to hang the printer/USB connection -- see
    # __init__. build() must never do that itself, regardless of
    # leading_cleanup; callers send build_cleanup_segment() as a fully
    # separate transmission instead (see tools/test_print.py).
    media = get_media("12mm")
    with_cleanup = RasterJobBuilder(media, leading_cleanup=True)
    with_cleanup.add_line(b"\x00" * media.print_bytes)
    with_data = with_cleanup.build()

    without_cleanup = RasterJobBuilder(media, leading_cleanup=False)
    without_cleanup.add_line(b"\x00" * media.print_bytes)
    without_data = without_cleanup.build()

    assert with_data == without_data


def test_build_cleanup_segment_uses_real_blank_lines_not_a_zero_count():
    # Two variants declaring raster_count=0 both hung the printer on real
    # hardware (see __init__/build_cleanup_segment docstrings) -- this
    # variant must never declare 0, to test the hypothesis that 0 itself
    # is what the firmware chokes on.
    media = get_media("12mm")
    builder = RasterJobBuilder(media)
    builder.add_line(b"\x00" * media.print_bytes)  # should not affect the cleanup segment
    cleanup_segment = builder.build_cleanup_segment(blank_lines=5)

    assert cleanup_segment[:200] == b"\x00" * 200
    assert cleanup_segment[200:202] == bytes([ESC, 0x40])
    assert cleanup_segment.endswith(b"\x1a")
    pic_start = 206
    raster_count = int.from_bytes(cleanup_segment[pic_start + 7 : pic_start + 11], "little")
    assert raster_count == 5
    assert cleanup_segment.count(b"\x47") == 5  # one 'G' command per blank line


def test_mode_and_advanced_byte_overrides():
    media = get_media("12mm")
    builder = RasterJobBuilder(media, mode_byte=0x48, advanced_byte=0x08, leading_cleanup=False)
    builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()

    mode_start = 200 + 2 + 4 + 13  # right after print-information command
    assert data[mode_start : mode_start + 4] == bytes([ESC, 0x69, 0x4D, 0x48])
    adv_start = mode_start + 4
    assert data[adv_start : adv_start + 4] == bytes([ESC, 0x69, 0x4B, 0x08])


def test_trailing_invalidate_appends_second_invalidate_and_init():
    media = get_media("12mm")
    without = RasterJobBuilder(media)
    without.add_line(b"\x00" * media.print_bytes)
    without_data = without.build()

    builder = RasterJobBuilder(media, trailing_invalidate=True)
    builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()

    assert len(data) == len(without_data) + 202
    assert data[: len(without_data)] == without_data
    assert data[len(without_data) : len(without_data) + 200] == b"\x00" * 200
    assert data[-2:] == bytes([ESC, 0x40])


def test_raster_line_rejects_wrong_length():
    media = get_media("12mm")
    builder = RasterJobBuilder(media)
    try:
        builder.add_line(b"\x00" * (media.print_bytes + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a mis-sized raster line")


def test_feed_amount_command_encodes_margin_in_dots():
    media = get_media("12mm")
    builder = RasterJobBuilder(media, feed_margin_mm=25.0, leading_cleanup=False)
    builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()

    feed_cmd_start = 200 + 2 + 4 + 13 + 4 + 4  # right after advanced settings
    assert data[feed_cmd_start : feed_cmd_start + 3] == bytes([ESC, 0x69, 0x64])
    margin_dots = int.from_bytes(data[feed_cmd_start + 3 : feed_cmd_start + 5], "little")
    assert margin_dots == round(25.0 / 25.4 * 180)


def test_feed_margin_defaults_to_a_generous_nonzero_value():
    # Confirmed on real hardware: without an explicit trailing feed, most of
    # a short print job stayed physically stuck between the print head and
    # the cutter after "cutting". The default must not be 0.
    media = get_media("12mm")
    builder = RasterJobBuilder(media)
    assert builder.feed_margin_dots > 0


def test_g_command_framing_and_length():
    media = get_media("6mm")  # width < full head, exercises padding path
    builder = RasterJobBuilder(media, leading_cleanup=False)
    # Only the media's actual print_dots are meaningful pixels; any trailing
    # bits within print_bytes are byte-alignment padding a real CUPS raster
    # row would leave as 0, so build the line the same way.
    line = pack_bitmap_row([1] * media.print_dots, media.print_bytes)
    builder.add_line(line)
    data = builder.build()

    # Find the 'G' raster transfer command after the fixed-size preamble:
    # 200 invalidate + 2 initialize + 4 raster-mode + 13 print-info-command
    # (3-byte header + 10 data bytes) + 4 mode-settings + 4 advanced-settings
    # + 5 feed-amount + 2 compression-mode-select.
    preamble_len = 200 + 2 + 4 + 13 + 4 + 4 + 5 + 2
    assert data[preamble_len] == 0x47  # 'G'
    length = int.from_bytes(data[preamble_len + 1 : preamble_len + 3], "little")
    assert length == BYTES_PER_LINE
    payload = data[preamble_len + 3 : preamble_len + 3 + length]
    assert len(payload) == BYTES_PER_LINE
    # The black input line should show up as set bits exactly within the
    # media's centered window and zero bits outside it.
    covered_bits = "".join(f"{b:08b}" for b in payload)
    start = media.pin_offset
    end = media.pin_offset + media.print_dots
    assert set(covered_bits[start:end]) == {"1"}
    assert set(covered_bits[:start] + covered_bits[end:]) <= {"0"}


def test_invert_flips_only_the_raster_line_bytes():
    media = get_media("24mm")  # full head width, offset 0, simplest to reason about
    line = bytes([0b10110000]) + bytes([0x00] * (BYTES_PER_LINE - 1))

    normal = RasterJobBuilder(media, leading_cleanup=False)
    normal.add_line(line)
    normal_data = normal.build()

    inverted = RasterJobBuilder(media, invert=True, leading_cleanup=False)
    inverted.add_line(line)
    inverted_data = inverted.build()

    # Everything except the raster line payloads should be identical.
    assert normal_data[:234] == inverted_data[:234]
    assert normal_data[-1:] == inverted_data[-1:]

    preamble_len = 234
    normal_payload = normal_data[preamble_len + 3 : preamble_len + 3 + BYTES_PER_LINE]
    inverted_payload = inverted_data[preamble_len + 3 : preamble_len + 3 + BYTES_PER_LINE]
    assert inverted_payload == bytes(b ^ 0xFF for b in normal_payload)


def test_pack_bitmap_row():
    packed = pack_bitmap_row([1, 0, 1, 1, 0, 0, 0, 0, 1], n_bytes=2)
    assert packed == bytes([0b10110000, 0b10000000])


def test_build_status_request_is_invalidate_initialize_then_status_query():
    data = build_status_request()
    assert data[:200] == b"\x00" * 200
    assert data[200:202] == bytes([ESC, 0x40])  # Initialize
    assert data[202:205] == bytes([ESC, 0x69, 0x53])  # ESC i S
    assert len(data) == 205


def test_multiple_lines_produce_multiple_g_commands():
    media = get_media("12mm")
    builder = RasterJobBuilder(media, auto_cut=False, leading_cleanup=False)
    for _ in range(3):
        builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()
    assert data.count(b"\x47") >= 3  # at least 3 'G' bytes (could coincide with data too)
