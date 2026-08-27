"""Unit tests for brother_ptraster.orient.transform_page.

Uses a small, hand-verified asymmetric grid (checked against the standard
clockwise matrix-rotation formula: result[r][c] = original[rows-1-c][r]
for 90 deg, etc.) so a wrong rotation direction or an accidental extra
mirror fails a test instead of only showing up as unreadable text on a
real label.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.orient import transform_page, trim_blank_rows
from brother_ptraster.protocol import pack_bitmap_row

# 2 rows x 3 cols "L"-ish shape:
#   1 0 0
#   1 1 1
_WIDTH = 3
_ROWS = [pack_bitmap_row([1, 0, 0], 1), pack_bitmap_row([1, 1, 1], 1)]


def _grid(rows, width):
    from brother_ptraster.orient import _unpack_row

    return [_unpack_row(r, width) for r in rows]


def test_rotate_0_no_mirror_is_identity():
    new_rows, new_width = transform_page(_ROWS, _WIDTH, rotate=0, mirror=False)
    assert new_width == 3
    assert _grid(new_rows, new_width) == [[1, 0, 0], [1, 1, 1]]


def test_mirror_only_flips_each_row_left_right():
    new_rows, new_width = transform_page(_ROWS, _WIDTH, rotate=0, mirror=True)
    assert new_width == 3
    assert _grid(new_rows, new_width) == [[0, 0, 1], [1, 1, 1]]


def test_rotate_90_clockwise():
    new_rows, new_width = transform_page(_ROWS, _WIDTH, rotate=90, mirror=False)
    assert new_width == 2  # was height
    assert _grid(new_rows, new_width) == [[1, 1], [1, 0], [1, 0]]


def test_rotate_180():
    new_rows, new_width = transform_page(_ROWS, _WIDTH, rotate=180, mirror=False)
    assert new_width == 3
    assert _grid(new_rows, new_width) == [[1, 1, 1], [0, 0, 1]]


def test_rotate_270_clockwise():
    new_rows, new_width = transform_page(_ROWS, _WIDTH, rotate=270, mirror=False)
    assert new_width == 2  # was height
    assert _grid(new_rows, new_width) == [[0, 1], [0, 1], [1, 1]]


def test_rotate_180_is_two_rotate_90s():
    once, w1 = transform_page(_ROWS, _WIDTH, rotate=90, mirror=False)
    twice, w2 = transform_page(once, w1, rotate=90, mirror=False)
    direct, w3 = transform_page(_ROWS, _WIDTH, rotate=180, mirror=False)
    assert w2 == w3
    assert _grid(twice, w2) == _grid(direct, w3)


def test_invalid_rotate_raises():
    try:
        transform_page(_ROWS, _WIDTH, rotate=45, mirror=False)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a non-90-multiple rotate")


_BLANK = b"\x00"
_INK = b"\x80"


def test_trim_blank_rows_strips_leading_and_trailing_blank_only():
    rows = [_BLANK, _BLANK, _INK, _BLANK, _INK, _BLANK, _BLANK]
    assert trim_blank_rows(rows) == [_INK, _BLANK, _INK]


def test_trim_blank_rows_leaves_fully_inked_content_unchanged():
    rows = [_INK, _INK, _INK]
    assert trim_blank_rows(rows) == rows


def test_trim_blank_rows_returns_empty_for_an_all_blank_page():
    assert trim_blank_rows([_BLANK, _BLANK, _BLANK]) == []


def test_trim_blank_rows_handles_an_empty_list():
    assert trim_blank_rows([]) == []
