import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brother_ptraster.status import decode


def _packet(media_width=12, media_type=0x01, media_length=0, status_type=0x01,
            phase_type=0x00, phase_number=0, err1=0x00, err2=0x00,
            tape_color=0x01, text_color=0x08):
    data = bytearray(32)
    data[8] = err1
    data[9] = err2
    data[10] = media_width
    data[11] = media_type
    data[16] = media_length
    data[17] = status_type
    data[18] = phase_type
    data[19:21] = phase_number.to_bytes(2, "big")
    data[24] = tape_color
    data[25] = text_color
    return bytes(data)


def test_decode_rejects_wrong_length():
    try:
        decode(b"\x00" * 10)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a non-32-byte packet")


def test_decode_reports_no_errors_when_error_bytes_are_zero():
    status = decode(_packet())
    assert status.errors == []
    assert status.media_width_mm == 12
    assert status.media_type == "laminated tape"
    assert status.tape_color == "white"
    assert status.text_color == "black"


def test_decode_reports_other_tape_and_text_colors():
    status = decode(_packet(tape_color=0x04, text_color=0x01))
    assert status.tape_color == "red"
    assert status.text_color == "white"


def test_decode_unknown_color_is_labeled():
    status = decode(_packet(tape_color=0x77, text_color=0x77))
    assert "unknown" in status.tape_color
    assert "unknown" in status.text_color


def test_decode_flags_cover_open():
    status = decode(_packet(err2=0x10))
    assert "cover open" in status.errors


def test_decode_flags_cutter_jam():
    status = decode(_packet(err1=0x04))
    assert "cutter jam" in status.errors


def test_decode_combines_multiple_error_bits():
    status = decode(_packet(err1=0x01, err2=0x10 | 0x40))
    assert "no media" in status.errors
    assert "cover open" in status.errors
    assert "media cannot be fed / jam" in status.errors
    assert len(status.errors) == 3


def test_decode_unknown_media_type_is_labeled():
    status = decode(_packet(media_type=0x7A))
    assert "unknown" in status.media_type
