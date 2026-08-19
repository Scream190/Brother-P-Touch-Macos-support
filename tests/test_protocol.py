"""Unit tests for brother_ptraster.protocol and .media.

These test the byte-level command framing against the documented Brother
raster-mode protocol; they do not require a physical printer. See
README.md for how to validate against real hardware.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.media import get_media, nearest_media, HEAD_PINS, BYTES_PER_LINE
from brother_ptraster.protocol import RasterJobBuilder, pack_bitmap_row, ESC


def test_media_table_widths_are_centered_within_head():
    for media in get_media("12mm"), get_media("24mm"), get_media("3.5mm"):
        assert media.print_dots <= HEAD_PINS
        assert media.pin_offset + media.print_dots <= HEAD_PINS
        # symmetric (or off-by-one for odd remainders) centering
        remaining = HEAD_PINS - media.print_dots
        assert media.pin_offset in (remaining // 2, remaining - remaining // 2)


def test_24mm_uses_full_head():
    media = get_media("24mm")
    assert media.print_dots == HEAD_PINS
    assert media.pin_offset == 0
    assert media.print_bytes == BYTES_PER_LINE


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
    builder = RasterJobBuilder(media)
    builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()

    assert data[:200] == b"\x00" * 200
    assert data[200:202] == bytes([ESC, 0x40])  # Initialize
    assert data[202:206] == bytes([ESC, 0x69, 0x61, 0x01])  # raster mode


def test_print_information_command_encodes_line_count():
    media = get_media("12mm")
    builder = RasterJobBuilder(media)
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


def test_raster_line_rejects_wrong_length():
    media = get_media("12mm")
    builder = RasterJobBuilder(media)
    try:
        builder.add_line(b"\x00" * (media.print_bytes + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a mis-sized raster line")


def test_g_command_framing_and_length():
    media = get_media("6mm")  # width < full head, exercises padding path
    builder = RasterJobBuilder(media)
    # Only the media's actual print_dots are meaningful pixels; any trailing
    # bits within print_bytes are byte-alignment padding a real CUPS raster
    # row would leave as 0, so build the line the same way.
    line = pack_bitmap_row([1] * media.print_dots, media.print_bytes)
    builder.add_line(line)
    data = builder.build()

    # Find the 'G' raster transfer command after the fixed-size preamble:
    # 200 invalidate + 2 initialize + 4 raster-mode + 13 print-info-command
    # (3-byte header + 10 data bytes) + 4 mode-settings + 4 advanced-settings.
    preamble_len = 200 + 2 + 4 + 13 + 4 + 4
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


def test_pack_bitmap_row():
    packed = pack_bitmap_row([1, 0, 1, 1, 0, 0, 0, 0, 1], n_bytes=2)
    assert packed == bytes([0b10110000, 0b10000000])


def test_multiple_lines_produce_multiple_g_commands():
    media = get_media("12mm")
    builder = RasterJobBuilder(media, auto_cut=False)
    for _ in range(3):
        builder.add_line(b"\x00" * media.print_bytes)
    data = builder.build()
    assert data.count(b"\x47") >= 3  # at least 3 'G' bytes (could coincide with data too)
