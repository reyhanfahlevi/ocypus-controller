"""
Device communication abstraction for Ocypus & Hongtai USB HID controllers.
Supports both native Linux /dev/hidraw (zero dependencies) and python-hidapi.
"""

import os
import glob
import logging
from typing import Optional, List, Dict, Any, Tuple
from .protocol import SUPPORTED_DEVICES

logger = logging.getLogger("ocypus.device")


def parse_report_descriptor_usage_pages(data: bytes) -> Tuple[List[int], List[int]]:
    """
    Parses a binary HID report descriptor to extract (app_usage_pages, all_usage_pages).
    app_usage_pages: Usage Pages belonging to Application collections (Collection 0x01).
    all_usage_pages: All Usage Pages encountered in the descriptor.
    """
    i = 0
    usage_page = None
    app_usage_pages = []
    all_usage_pages = []

    while i < len(data):
        b = data[i]
        if b == 0xFE:  # Long item
            if i + 2 >= len(data):
                break
            dlen = data[i + 1]
            i += 3 + dlen
            continue

        b_size = b & 0x03
        if b_size == 3:
            b_size = 4
        b_type = (b >> 2) & 0x03
        b_tag = (b >> 4) & 0x0F

        item_data = data[i + 1 : i + 1 + b_size]
        val = int.from_bytes(item_data, byteorder="little") if item_data else 0

        if b_type == 1 and b_tag == 0:  # Global: Usage Page
            usage_page = val
            all_usage_pages.append(val)
        elif b_type == 0 and b_tag == 10:  # Main: Collection
            if val == 1 and usage_page is not None:  # Application Collection
                app_usage_pages.append(usage_page)

        i += 1 + b_size

    return app_usage_pages, all_usage_pages


class HidDevice:
    def __init__(
        self,
        path: str,
        vid: int,
        pid: int,
        name: str,
        usage_page: Optional[int] = None,
        interface: Optional[int] = None,
    ):
        self.path = path
        self.vid = vid
        self.pid = pid
        self.name = name
        self.usage_page = usage_page
        self.interface = interface
        self._fd: Optional[int] = None
        self._hid_handle = None

    def open(self):
        if self._fd is not None or self._hid_handle is not None:
            return

        # Attempt 1: hidapi (preferred if path is USB bus id like "1-7.2:1.1")
        if not self.path.startswith("/dev/"):
            try:
                import hid
                self._hid_handle = hid.device()
                path_bytes = self.path.encode("utf-8") if isinstance(self.path, str) else self.path
                self._hid_handle.open_path(path_bytes)
                logger.info("Opened %s via hidapi (%s)", self.name, self.path)
                return
            except Exception as e:
                logger.debug("Failed to open via hidapi: %s", e)

        # Attempt 2: native /dev/hidraw
        if os.path.exists(self.path):
            try:
                self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
                logger.info(
                    "Opened %s via native /dev/hidraw (%s, usage_page=0x%s)",
                    self.name,
                    self.path,
                    f"{self.usage_page:04X}" if self.usage_page else "N/A",
                )
                return
            except PermissionError:
                logger.error(
                    "Permission denied opening %s. Ensure udev rules are installed.", self.path
                )
                raise
            except Exception as e:
                logger.debug("Failed to open via os.open: %s", e)

        # Attempt 3: hidapi fallback for /dev/ paths
        try:
            import hid
            self._hid_handle = hid.device()
            path_bytes = self.path.encode("utf-8") if isinstance(self.path, str) else self.path
            self._hid_handle.open_path(path_bytes)
            logger.info("Opened %s via hidapi fallback (%s)", self.name, self.path)
            return
        except Exception as e:
            logger.debug("Failed to open via hidapi fallback: %s", e)

        raise RuntimeError(f"Could not open device at {self.path}")

    def write(self, data: bytes) -> int:
        if self._hid_handle is not None:
            return self._hid_handle.write(data)
        elif self._fd is not None:
            try:
                return os.write(self._fd, data)
            except BrokenPipeError:
                # If native hidraw write fails with BrokenPipe, switch dynamically to hidapi if available
                try:
                    import hid
                    logger.info("Native hidraw write failed with BrokenPipe; switching to hidapi for %s", self.name)
                    os.close(self._fd)
                    self._fd = None
                    self._hid_handle = hid.device()
                    target_path = None
                    for d in hid.enumerate(self.vid, self.pid):
                        if self.interface is not None:
                            if d.get("interface_number") == self.interface:
                                target_path = d["path"]
                                break
                        else:
                            target_path = d["path"]
                            break
                    if target_path:
                        self._hid_handle.open_path(target_path)
                        return self._hid_handle.write(data)
                except Exception as ex:
                    logger.debug("Failed to switch to hidapi: %s", ex)
                raise
        else:
            raise RuntimeError("Device is not open")

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None

        if self._hid_handle is not None:
            try:
                self._hid_handle.close()
            except Exception:
                pass
            self._hid_handle = None


def find_ocypus_devices() -> List[HidDevice]:
    """
    Scans system for connected Ocypus & Hongtai digital display devices.
    Matches Vendor ID, Product ID, Usage Page, and USB interface number.
    Returns list of discovered HidDevice instances.
    """
    found = []

    # 1. Try python-hidapi first if installed (handles USB detachment for composite devices)
    try:
        import hid
        for d in hid.enumerate():
            vid = d.get("vendor_id", 0)
            pid = d.get("product_id", 0)
            dev_up = d.get("usage_page", 0)
            ifnum = d.get("interface_number", -1)

            for dev_info in SUPPORTED_DEVICES:
                if dev_info["vid"] == vid and dev_info["pid"] == pid:
                    expected_up = dev_info.get("usage_page")
                    if expected_up is not None and dev_up != 0 and dev_up != expected_up:
                        continue

                    expected_if = dev_info.get("interface")
                    if expected_if is not None and ifnum != -1 and ifnum != expected_if:
                        continue

                    path_val = d["path"]
                    path_str = path_val.decode("utf-8") if isinstance(path_val, bytes) else str(path_val)
                    found.append(
                        HidDevice(
                            path=path_str,
                            vid=vid,
                            pid=pid,
                            name=dev_info["name"],
                            usage_page=dev_up or expected_up,
                            interface=ifnum if ifnum != -1 else expected_if,
                        )
                    )
        if found:
            return found
    except ImportError:
        pass
    except Exception as e:
        logger.debug("hidapi enumeration failed: %s", e)

    # 2. Check native Linux /sys/class/hidraw (zero dependencies fallback)
    hidraw_paths = sorted(glob.glob("/sys/class/hidraw/hidraw*"))
    for hpath in hidraw_paths:
        dev_name = os.path.basename(hpath)
        dev_file = os.path.join("/dev", dev_name)
        uevent_file = os.path.join(hpath, "device", "uevent")
        rd_file = os.path.join(hpath, "device", "report_descriptor")

        if not os.path.exists(uevent_file):
            continue

        try:
            with open(uevent_file, "r") as f:
                content = f.read()

            # Parse HID_ID=0003:00005131:00002016
            for line in content.splitlines():
                if line.startswith("HID_ID="):
                    parts = line.split("=")[1].split(":")
                    if len(parts) >= 3:
                        vid = int(parts[1], 16)
                        pid = int(parts[2], 16)

                        # Parse usage pages from report_descriptor if present
                        app_ups: List[int] = []
                        all_ups: List[int] = []
                        raw_rd = b""
                        if os.path.exists(rd_file):
                            try:
                                with open(rd_file, "rb") as rf:
                                    raw_rd = rf.read()
                                app_ups, all_ups = parse_report_descriptor_usage_pages(raw_rd)
                            except Exception as e:
                                logger.debug("Could not read report descriptor %s: %s", rd_file, e)

                        for dev_info in SUPPORTED_DEVICES:
                            if dev_info["vid"] == vid and dev_info["pid"] == pid:
                                expected_up = dev_info.get("usage_page")

                                # If an explicit usage page is required (e.g. 0xFF01 for YCC custom composite device)
                                if expected_up is not None:
                                    # Check report descriptor parsing
                                    up_match = (
                                        expected_up in app_ups
                                        or expected_up in all_ups
                                        # Fast fallback pattern: 0x06 (Usage Page 16-bit), little-endian expected_up
                                        or (expected_up.to_bytes(2, "little") in raw_rd)
                                    )
                                    if not up_match:
                                        logger.debug(
                                            "Skipping %s (%s): expected usage_page 0x%04X, got app=%s all=%s",
                                            dev_file,
                                            dev_info["name"],
                                            expected_up,
                                            [f"0x{u:04X}" for u in app_ups],
                                            [f"0x{u:04X}" for u in all_ups],
                                        )
                                        continue

                                matched_up = expected_up or (app_ups[0] if app_ups else (all_ups[0] if all_ups else None))
                                found.append(
                                    HidDevice(
                                        path=dev_file,
                                        vid=vid,
                                        pid=pid,
                                        name=dev_info["name"],
                                        usage_page=matched_up,
                                    )
                                )
        except Exception as e:
            logger.debug("Error inspecting %s: %s", uevent_file, e)

    return found
