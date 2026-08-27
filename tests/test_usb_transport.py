import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import test_print  # noqa: E402


def test_build_usb_backend_argv_matches_cups_calling_convention():
    argv = test_print.build_usb_backend_argv("42", "alice", "My Label", "/tmp/job.bin")
    assert argv == [test_print.USB_BACKEND, "42", "alice", "My Label", "1", "", "/tmp/job.bin"]


# --- brother_ptraster.usb_transport, exercised against a fake pyusb -------
#
# The real pyusb/libusb stack needs an actual USB device and isn't
# available in this test environment, so these tests inject a minimal fake
# 'usb.core'/'usb.util' pair into sys.modules that mimics just the surface
# usb_transport.py actually calls. This still catches real bugs in the
# device-selection (serial disambiguation) and endpoint-discovery logic,
# which is where mistakes are most likely and cheapest to make, without
# needing real hardware.

ENDPOINT_OUT = 0x00
ENDPOINT_IN = 0x80


class _FakeEndpoint:
    def __init__(self, address, reply=None):
        self.bEndpointAddress = address
        self._reply = reply
        self.written = None

    def write(self, data):
        self.written = bytes(data)

    def read(self, size, timeout=None):
        return self._reply


class _FakeConfig:
    def __init__(self, intf):
        self._intf = intf

    def __getitem__(self, key):
        assert key == (0, 0)
        return self._intf


class _FakeDevice:
    def __init__(self, serial, ep_out, ep_in):
        self.iSerialNumber = 3
        self._serial = serial
        self._ep_out = ep_out
        self._ep_in = ep_in
        self.kernel_driver_active = False
        self.configured = False

    def get_active_configuration(self):
        return _FakeConfig([self._ep_out, self._ep_in])

    def is_kernel_driver_active(self, intf_num):
        return self.kernel_driver_active

    def detach_kernel_driver(self, intf_num):
        self.kernel_driver_active = False

    def set_configuration(self):
        self.configured = True


class _FakeUSBError(Exception):
    pass


def _install_fake_pyusb(devices, serial_lookup):
    fake_core = types.ModuleType("usb.core")
    fake_core.USBError = _FakeUSBError
    fake_core.find = lambda idVendor=None, find_all=False: list(devices)

    fake_util = types.ModuleType("usb.util")
    fake_util.ENDPOINT_OUT = ENDPOINT_OUT
    fake_util.ENDPOINT_IN = ENDPOINT_IN
    fake_util.endpoint_direction = lambda addr: addr & 0x80
    fake_util.get_string = lambda dev, index: serial_lookup.get(id(dev))

    def find_descriptor(intf, custom_match):
        for ep in intf:
            if custom_match(ep):
                return ep
        return None

    fake_util.find_descriptor = find_descriptor

    fake_usb = types.ModuleType("usb")
    fake_usb.core = fake_core
    fake_usb.util = fake_util

    sys.modules["usb"] = fake_usb
    sys.modules["usb.core"] = fake_core
    sys.modules["usb.util"] = fake_util

    # Force a fresh import against the fake modules above, in case an
    # earlier test (or a real pyusb install) already populated this.
    sys.modules.pop("brother_ptraster.usb_transport", None)

    import brother_ptraster.usb_transport as usb_transport

    return usb_transport


def _teardown_fake_pyusb():
    for name in ("usb", "usb.core", "usb.util"):
        sys.modules.pop(name, None)
    sys.modules.pop("brother_ptraster.usb_transport", None)


def test_find_device_matches_single_brother_device_with_no_serial_needed():
    ep_out = _FakeEndpoint(ENDPOINT_OUT)
    ep_in = _FakeEndpoint(ENDPOINT_IN, reply=b"\x00" * 32)
    dev = _FakeDevice("000J4G980818", ep_out, ep_in)
    try:
        usb_transport = _install_fake_pyusb([dev], {id(dev): "000J4G980818"})
        found = usb_transport.find_device()
        assert found is dev
    finally:
        _teardown_fake_pyusb()


def test_find_device_disambiguates_by_serial():
    ep_out1, ep_in1 = _FakeEndpoint(ENDPOINT_OUT), _FakeEndpoint(ENDPOINT_IN)
    ep_out2, ep_in2 = _FakeEndpoint(ENDPOINT_OUT), _FakeEndpoint(ENDPOINT_IN)
    dev1 = _FakeDevice("AAA", ep_out1, ep_in1)
    dev2 = _FakeDevice("BBB", ep_out2, ep_in2)
    try:
        usb_transport = _install_fake_pyusb(
            [dev1, dev2], {id(dev1): "AAA", id(dev2): "BBB"}
        )
        assert usb_transport.find_device(serial="BBB") is dev2
    finally:
        _teardown_fake_pyusb()


def test_find_device_raises_when_none_found():
    try:
        usb_transport = _install_fake_pyusb([], {})
        try:
            usb_transport.find_device()
        except usb_transport.UsbTransportError:
            pass
        else:
            raise AssertionError("expected UsbTransportError")
    finally:
        _teardown_fake_pyusb()


def test_find_device_raises_when_ambiguous_without_serial():
    ep_out1, ep_in1 = _FakeEndpoint(ENDPOINT_OUT), _FakeEndpoint(ENDPOINT_IN)
    ep_out2, ep_in2 = _FakeEndpoint(ENDPOINT_OUT), _FakeEndpoint(ENDPOINT_IN)
    dev1 = _FakeDevice("AAA", ep_out1, ep_in1)
    dev2 = _FakeDevice("BBB", ep_out2, ep_in2)
    try:
        usb_transport = _install_fake_pyusb(
            [dev1, dev2], {id(dev1): "AAA", id(dev2): "BBB"}
        )
        try:
            usb_transport.find_device()
        except usb_transport.UsbTransportError:
            pass
        else:
            raise AssertionError("expected UsbTransportError for an ambiguous match")
    finally:
        _teardown_fake_pyusb()


def test_find_device_uses_libusb_package_backend_when_available():
    ep_out = _FakeEndpoint(ENDPOINT_OUT)
    ep_in = _FakeEndpoint(ENDPOINT_IN, reply=b"\x00" * 32)
    dev = _FakeDevice("000J4G980818", ep_out, ep_in)

    fake_backend = object()
    fake_libusb_package = types.ModuleType("libusb_package")
    fake_libusb_package.get_libusb1_backend = lambda: fake_backend

    seen_kwargs = {}

    try:
        usb_transport = _install_fake_pyusb([dev], {id(dev): "000J4G980818"})
        sys.modules["libusb_package"] = fake_libusb_package

        real_find = sys.modules["usb.core"].find

        def spy_find(**kwargs):
            seen_kwargs.update(kwargs)
            return real_find(**{k: v for k, v in kwargs.items() if k != "backend"})

        sys.modules["usb.core"].find = spy_find

        usb_transport.find_device()
        assert seen_kwargs.get("backend") is fake_backend
    finally:
        sys.modules.pop("libusb_package", None)
        _teardown_fake_pyusb()


def test_find_device_falls_back_when_libusb_package_not_installed():
    ep_out = _FakeEndpoint(ENDPOINT_OUT)
    ep_in = _FakeEndpoint(ENDPOINT_IN, reply=b"\x00" * 32)
    dev = _FakeDevice("000J4G980818", ep_out, ep_in)
    try:
        usb_transport = _install_fake_pyusb([dev], {id(dev): "000J4G980818"})
        sys.modules.pop("libusb_package", None)
        assert usb_transport._get_backend() is None
        # find_device() should still work fine without a backend kwarg.
        assert usb_transport.find_device() is dev
    finally:
        _teardown_fake_pyusb()


def test_query_status_writes_request_and_returns_reply():
    ep_out = _FakeEndpoint(ENDPOINT_OUT)
    reply = bytes(range(32))
    ep_in = _FakeEndpoint(ENDPOINT_IN, reply=reply)
    dev = _FakeDevice("000J4G980818", ep_out, ep_in)
    try:
        usb_transport = _install_fake_pyusb([dev], {id(dev): "000J4G980818"})
        request = b"\x1b\x69\x53"
        result = usb_transport.query_status(request)
        assert ep_out.written == request
        assert result == reply
        assert dev.configured
    finally:
        _teardown_fake_pyusb()
