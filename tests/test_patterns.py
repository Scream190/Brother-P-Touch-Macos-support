import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.media import get_media
from brother_ptraster.patterns import PATTERNS, generate
from brother_ptraster.protocol import RasterJobBuilder


def test_all_patterns_generate_correctly_sized_lines():
    media = get_media("12mm")
    for name in PATTERNS:
        lines = generate(name, media, length=30)
        assert len(lines) == 30
        assert all(len(line) == media.print_bytes for line in lines)


def test_all_patterns_are_buildable_into_a_job():
    media = get_media("24mm")
    for name in PATTERNS:
        lines = generate(name, media, length=10)
        builder = RasterJobBuilder(media)
        builder.add_lines(lines)
        data = builder.build()
        assert data[-1:] == b"\x1a"


def test_solid_pattern_is_all_black_within_print_area():
    # Pattern lines are media-width (print_dots wide, padded to a byte
    # boundary), not yet shifted into the full head buffer -- that
    # centering happens later, inside RasterJobBuilder.add_line.
    media = get_media("12mm")
    lines = generate("solid", media, length=5)
    for line in lines:
        bits = "".join(f"{b:08b}" for b in line)
        assert set(bits[: media.print_dots]) == {"1"}


def test_unknown_pattern_raises():
    media = get_media("12mm")
    try:
        generate("not-a-real-pattern", media, 10)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown pattern name")


def test_diagonal_first_and_last_rows_at_opposite_edges():
    media = get_media("24mm")  # full head width, offset 0, simplest to reason about
    lines = generate("diagonal", media, length=50)
    first_bits = "".join(f"{b:08b}" for b in lines[0])
    last_bits = "".join(f"{b:08b}" for b in lines[-1])
    assert first_bits[:3] == "111"
    assert last_bits[-3:] == "111"
