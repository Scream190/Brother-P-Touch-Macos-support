import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import test_print  # noqa: E402


def test_build_usb_backend_argv_matches_cups_calling_convention():
    argv = test_print.build_usb_backend_argv("42", "alice", "My Label", "/tmp/job.bin")
    assert argv == [test_print.USB_BACKEND, "42", "alice", "My Label", "1", "", "/tmp/job.bin"]
