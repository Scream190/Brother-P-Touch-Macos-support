"""Direct (bidirectional) USB transport, for status queries only.

macOS doesn't expose a raw filesystem device node for USB printers (unlike
paired Bluetooth serial ports at /dev/cu.*), and Apple's own CUPS ``usb``
backend is built around one-shot print jobs -- it gives calling code no
reliable way to read back arbitrary reply bytes (like the printer's 32-byte
status packet, see status.py) after writing a request. So for status
queries specifically, this talks to the USB device directly via PyUSB
(bundled with libusb), the same approach other Brother/label-printer USB
drivers commonly use.

Normal printing is UNAFFECTED by this module -- it still goes entirely
through the standard CUPS ``usb`` backend via the ptp710bt filter/backend,
which only ever writes, never needs this.

Requires (only for tools/check_media.py, not for printing):
    pip3 install pyusb
    brew install libusb

Known macOS gotcha: if something else currently holds the USB interface
open (e.g. macOS's own generic USB-printing class support, or a stale CUPS
job), claiming it here can fail with a "busy"/"access" error from libusb.
If that happens, try unplugging and replugging the printer immediately
before running the query, and make sure no print job is in progress.
"""

from __future__ import annotations

from typing import Optional

# Brother Industries, Ltd.'s USB vendor ID -- confirmed via the public USB
# ID database. Deliberately NOT hardcoding a product ID: the PT-P710BT's
# exact USB product ID isn't reliably documented anywhere queryable here,
# and hardcoding a guessed one risks silently finding nothing (or finding
# the wrong device) on a real unit. Instead this enumerates all Brother
# devices and, if more than one is attached, disambiguates by USB serial
# number -- the same serial already visible in the CUPS device URI (e.g.
# ``usb://Brother/PT-P710BT?serial=000J4G980818``, see ``sudo lpinfo -v``).
BROTHER_VENDOR_ID = 0x04F9

STATUS_PACKET_SIZE = 32
STATUS_READ_TIMEOUT_MS = 2000


class UsbTransportError(Exception):
    pass


def _require_pyusb():
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise UsbTransportError(
            "pyusb is required for direct USB status queries (not needed for "
            "normal printing). Install it with:\n"
            "    pip3 install pyusb libusb-package\n"
        ) from exc
    return usb.core, usb.util


def _get_backend():
    """Return a pyusb backend from the ``libusb-package`` wheel if it's
    installed, or None to fall back to pyusb's own auto-discovery (which
    needs a system libusb, e.g. via Homebrew's ``libusb`` formula).

    ``libusb-package`` bundles prebuilt libusb binaries for macOS/Windows/
    Linux, so it works without Homebrew at all -- useful since not every
    Mac has Homebrew installed (confirmed on real hardware: ``brew`` was
    missing, and pyusb alone can't find a libusb without either it).
    """
    try:
        import libusb_package
    except ImportError:
        return None
    return libusb_package.get_libusb1_backend()


def find_device(serial: Optional[str] = None):
    """Find the Brother USB device, disambiguating by serial if given.

    Raises UsbTransportError if none are found, or if more than one is
    found and ``serial`` doesn't narrow it down to exactly one.
    """
    core, util = _require_pyusb()
    backend = _get_backend()

    find_kwargs = {"idVendor": BROTHER_VENDOR_ID, "find_all": True}
    if backend is not None:
        find_kwargs["backend"] = backend

    try:
        devices = list(core.find(**find_kwargs))
    except ValueError as exc:
        # pyusb raises this (not USBError) when it can't locate ANY libusb
        # backend at all -- distinct from "found libusb but no matching
        # device", which returns an empty list instead of raising.
        raise UsbTransportError(
            f"pyusb could not find a libusb backend ({exc}). Install one "
            f"of:\n"
            f"    pip3 install libusb-package   # no Homebrew needed\n"
            f"    brew install libusb\n"
        ) from exc

    if not devices:
        raise UsbTransportError(
            "no Brother USB device found (USB vendor 0x04f9) -- is the "
            "printer connected via USB and powered on?"
        )

    if serial:
        matched = [d for d in devices if _device_serial(d, util) == serial]
        if not matched:
            found = ", ".join(_device_serial(d, util) or "?" for d in devices)
            raise UsbTransportError(
                f"no Brother USB device with serial {serial!r} found "
                f"(attached: {found})"
            )
        devices = matched

    if len(devices) > 1:
        found = ", ".join(_device_serial(d, util) or "?" for d in devices)
        raise UsbTransportError(
            f"multiple Brother USB devices found ({found}); pass a serial "
            f"number to disambiguate (see 'sudo lpinfo -v')"
        )

    return devices[0]


def _device_serial(dev, util) -> Optional[str]:
    try:
        return util.get_string(dev, dev.iSerialNumber)
    except Exception:
        return None


def _find_bulk_endpoints(dev, util):
    """Locate the bulk OUT and bulk IN endpoints on the device's first
    interface by direction, rather than hardcoding endpoint addresses --
    those can differ across firmware/model revisions within the same
    printer family.
    """
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]

    ep_out = util.find_descriptor(
        intf,
        custom_match=lambda e: util.endpoint_direction(e.bEndpointAddress) == util.ENDPOINT_OUT,
    )
    ep_in = util.find_descriptor(
        intf,
        custom_match=lambda e: util.endpoint_direction(e.bEndpointAddress) == util.ENDPOINT_IN,
    )
    if ep_out is None or ep_in is None:
        raise UsbTransportError(
            "could not find bulk IN/OUT endpoints on the USB device's "
            "first interface"
        )
    return ep_out, ep_in


def query_status(request: bytes, serial: Optional[str] = None) -> bytes:
    """Send ``request`` (see protocol.build_status_request()) to the
    printer over a direct USB connection and return the 32-byte status
    packet it replies with (see status.decode()).
    """
    core, util = _require_pyusb()
    dev = find_device(serial)

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except NotImplementedError:
        pass  # macOS: no generic "USB printer class" kernel driver to detach

    try:
        dev.set_configuration()
        ep_out, ep_in = _find_bulk_endpoints(dev, util)
        ep_out.write(request)
        try:
            data = ep_in.read(STATUS_PACKET_SIZE, timeout=STATUS_READ_TIMEOUT_MS)
        except core.USBError as exc:
            raise UsbTransportError(
                f"no reply from the printer within {STATUS_READ_TIMEOUT_MS}ms "
                f"({exc}) -- is it powered on and idle (not mid-job)?"
            ) from exc
    except core.USBError as exc:
        raise UsbTransportError(
            f"could not claim the USB device ({exc}) -- another process "
            f"(a stale print job, or macOS's own USB-printing support) may "
            f"be holding it open; try unplugging/replugging the printer and "
            f"retrying with nothing else printing"
        ) from exc

    return bytes(data)
