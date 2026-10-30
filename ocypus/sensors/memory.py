"""
Linux Memory Metrics Collector for Proxmox 9.
Collects: RAM Utilization %, Frequency, and Temperature.
"""

import os
import glob


class MemorySensor:
    def __init__(self):
        self._temp_path = None
        self._discover_temp()

    def _discover_temp(self):
        # Look for DDR4/DDR5 SPD thermal sensors: spd5118, jc42, ee1004
        for d in glob.glob("/sys/class/hwmon/hwmon*"):
            name_file = os.path.join(d, "name")
            if os.path.exists(name_file):
                try:
                    with open(name_file, "r") as f:
                        name = f.read().strip().lower()
                    if name in ("spd5118", "jc42"):
                        inputs = glob.glob(os.path.join(d, "temp*_input"))
                        if inputs:
                            self._temp_path = inputs[0]
                            break
                except Exception:
                    pass

    def get_metrics(self) -> tuple[float, float, float]:
        """Returns (utilization_pct, temp_c, freq_mhz)."""
        util_pct = 0.0
        temp_c = 0.0
        freq_mhz = 0.0

        # Memory usage from /proc/meminfo
        if os.path.exists("/proc/meminfo"):
            try:
                mem = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip().split()[0]
                            mem[key] = int(val)
                total = mem.get("MemTotal", 0)
                available = mem.get("MemAvailable", 0)
                if total > 0:
                    used = total - available
                    util_pct = (used / total) * 100.0
            except Exception:
                pass

        # Temperature
        if self._temp_path and os.path.exists(self._temp_path):
            try:
                with open(self._temp_path, "r") as f:
                    raw = float(f.read().strip())
                    temp_c = raw / 1000.0 if raw > 200 else raw
            except Exception:
                pass

        return util_pct, temp_c, freq_mhz
