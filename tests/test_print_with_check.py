import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from brother_ptraster.media import get_media, get_media_by_ppd_option
from brother_ptraster.status import StatusPacket

import print_with_check  # noqa: E402


def test_get_media_by_ppd_option_round_trips_all_widths():
    for name in ("3.5mm", "6mm", "9mm", "12mm", "18mm", "24mm"):
        media = get_media(name)
        assert get_media_by_ppd_option(media.ppd_option) is media


def test_get_media_by_ppd_option_rejects_unknown():
    try:
        get_media_by_ppd_option("mm999")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown ppd_option")


def _status(media_width_mm):
    return StatusPacket(
        raw=b"\x00" * 32,
        media_width_mm=media_width_mm,
        media_type="laminated tape",
        media_length_mm=0,
        status_type="reply to status request",
        phase_type="waiting to receive",
        phase_number=0,
        tape_color="white",
        text_color="black",
        errors=[],
    )


def test_check_media_passes_when_widths_match(monkeypatch):
    monkeypatch.setattr(print_with_check, "query_status", lambda request, serial=None: b"\x00" * 32)
    monkeypatch.setattr(print_with_check, "decode", lambda reply: _status(12))
    print_with_check.check_media("mm12", serial=None, tolerance_mm=1.0)  # should not raise


def test_check_media_refuses_when_widths_mismatch(monkeypatch):
    monkeypatch.setattr(print_with_check, "query_status", lambda request, serial=None: b"\x00" * 32)
    monkeypatch.setattr(print_with_check, "decode", lambda reply: _status(18))
    try:
        print_with_check.check_media("mm12", serial=None, tolerance_mm=1.0)
    except SystemExit as exc:
        assert "18" in str(exc) and "mm12" in str(exc)
    else:
        raise AssertionError("expected SystemExit for a width mismatch")


def test_check_media_reports_transport_errors_as_system_exit(monkeypatch):
    from brother_ptraster.usb_transport import UsbTransportError

    def raise_error(request, serial=None):
        raise UsbTransportError("no device found")

    monkeypatch.setattr(print_with_check, "query_status", raise_error)
    try:
        print_with_check.check_media("mm12", serial=None, tolerance_mm=1.0)
    except SystemExit as exc:
        assert "no device found" in str(exc)
        assert "--skip-check" in str(exc)
    else:
        raise AssertionError("expected SystemExit when the transport fails")
