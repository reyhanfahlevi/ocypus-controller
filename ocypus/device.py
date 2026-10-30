"""
Device communication abstraction for Ocypus & Hongtai USB HID controllers.
Supports both native Linux /dev/hidraw (zero dependencies) and python-hidapi.
"""

import os
import glob
import logging
from typing import Optional, List, Dict, Any
from .protocol import SUPPORTED_DEVICES

logger = logging.getLogger("ocypus.device")


class HidDevice:
    def __init__(self, path: str, vid: int, pid: int, name: str):
        self.path = path
        self.vid = vid
        self.pid = pid
        self.name = name
        self._fd: Optional[int] = None
        self._hid_handle = None

    def open(self):
        if self._fd is not None or self._hid_handle is not None:
            return

        # Attempt 1: native /dev/hidraw
        if os.path.exists(self.path):
            try:
                self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
                logger.info("Opened %s via native /dev/hidraw (%s)", self.name, self.path)
                return
            except PermissionError:
                logger.error(
                    "Permission denied opening %s. Ensure udev rules are installed.", self.path
                )
                raise
            except Exception as e:
                logger.debug("Failed to open via os.open: %s", e)

        # Attempt 2: hidapi
        try:
            import hid
            self._hid_handle = hid.device()
            self._hid_handle.open_path(self.path.encode("utf-8"))
            logger.info("Opened %s via hidapi (%s)", self.name, self.path)
            return
        except Exception as e:
            logger.debug("Failed to open via hidapi: %s", e)

        raise RuntimeError(f"Could not open device at {self.path}")

    def write(self, data: bytes) -> int:
        if self._fd is not None:
            return os.write(self._fd, data)
        elif self._hid_handle is not None:
            return self._hid_handle.write(data)
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
    Returns list of discovered HidDevice instances.
    """
    found = []

    # 1. Check native Linux /sys/class/hidraw
    hidraw_paths = sorted(glob.glob("/sys/class/hidraw/hidraw*"))
    for hpath in hidraw_paths:
        dev_name = os.path.basename(hpath)
        dev_file = os.path.join("/dev", dev_name)
        uevent_file = os.path.join(hpath, "device", "uevent")

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
                        for dev_info in SUPPORTED_DEVICES:
                            if dev_info["vid"] == vid and dev_info["pid"] == pid:
                                found.append(
                                    HidDevice(
                                        path=dev_file,
                                        vid=vid,
                                        pid=pid,
                                        name=dev_info["name"],
                                    )
                                )
        except Exception as e:
            logger.debug("Error inspecting %s: %s", uevent_file, e)

    if found:
        return found

    # 2. Fallback: try python-hidapi if installed
    try:
        import hid
        for d in hid.enumerate():
            vid = d.get("vendor_id", 0)
            pid = d.get("product_id", 0)
            for dev_info in SUPPORTED_DEVICES:
                if dev_info["vid"] == vid and dev_info["pid"] == pid:
                    path_str = d["path"].decode("utf-8") if isinstance(d["path"], bytes) else d["path"]
                    found.append(
                        HidDevice(
                            path=path_str,
                            vid=vid,
                            pid=pid,
                            name=dev_info["name"],
                        )
                    )
    except ImportError:
        pass
    except Exception as e:
        logger.debug("hidapi enumeration failed: %s", e)

    return found
