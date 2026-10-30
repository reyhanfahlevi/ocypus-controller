"""
Linux CPU Metrics Collector for Proxmox 9 (Debian-based).
Collects: Temperature, Utilization %, Frequency (MHz), Power Draw (W), Fan Speed (RPM).
"""

import os
import glob
import time
from typing import Optional, Tuple


class CpuSensor:
    def __init__(self, hwmon_temp_path: Optional[str] = None):
        self._custom_temp_path = hwmon_temp_path
        self._temp_path: Optional[str] = None
        self._power_path: Optional[str] = None
        self._prev_energy_uj: Optional[int] = None
        self._prev_energy_time: Optional[float] = None
        self._prev_stat: Optional[Tuple[int, int]] = None  # (idle, total)
        self._fan_path: Optional[str] = None

        self._discover_paths()

    def _discover_paths(self):
        if self._custom_temp_path and os.path.exists(self._custom_temp_path):
            self._temp_path = self._custom_temp_path
            return

        # Prioritize known CPU thermal drivers: coretemp, k10temp, zenpower, amd_energy
        hwmon_dirs = sorted(glob.glob("/sys/class/hwmon/hwmon*"))
        best_temp = None

        for d in hwmon_dirs:
            name_file = os.path.join(d, "name")
            driver_name = ""
            if os.path.exists(name_file):
                try:
                    with open(name_file, "r") as f:
                        driver_name = f.read().strip().lower()
                except Exception:
                    pass

            if driver_name in ("k10temp", "zenpower", "coretemp"):
                # Find package temp or highest priority temp
                inputs = sorted(glob.glob(os.path.join(d, "temp*_input")))
                for inp in inputs:
                    label_file = inp.replace("_input", "_label")
                    if os.path.exists(label_file):
                        try:
                            with open(label_file, "r") as f:
                                label = f.read().strip().lower()
                            if "tctl" in label or "package" in label or "tdie" in label:
                                best_temp = inp
                                break
                        except Exception:
                            pass
                if best_temp:
                    break
                if inputs:
                    best_temp = inputs[0]
                    break

            # Fallback candidate
            if not best_temp:
                inputs = glob.glob(os.path.join(d, "temp*_input"))
                if inputs:
                    best_temp = inputs[0]

            # Check for fan inputs
            if not self._fan_path:
                fan_inputs = glob.glob(os.path.join(d, "fan*_input"))
                if fan_inputs:
                    self._fan_path = fan_inputs[0]

        self._temp_path = best_temp

        # Power cap / RAPL energy
        rapl_energy = "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
        if os.path.exists(rapl_energy):
            self._power_path = rapl_energy
        else:
            # Check hwmon power inputs
            for d in hwmon_dirs:
                p_in = os.path.join(d, "power1_average")
                if os.path.exists(p_in):
                    self._power_path = p_in
                    break

    def get_temperature(self) -> float:
        if not self._temp_path or not os.path.exists(self._temp_path):
            self._discover_paths()

        if self._temp_path and os.path.exists(self._temp_path):
            try:
                with open(self._temp_path, "r") as f:
                    val = float(f.read().strip())
                    # hwmon returns millidegrees C
                    return val / 1000.0 if val > 200 else val
            except Exception:
                pass
        return 0.0

    def get_utilization(self) -> float:
        """Calculates total CPU utilization % from /proc/stat."""
        try:
            with open("/proc/stat", "r") as f:
                first_line = f.readline()
            fields = [int(x) for x in first_line.split()[1:]]
            idle = fields[3] + fields[4]  # idle + iowait
            total = sum(fields)

            if self._prev_stat is None:
                self._prev_stat = (idle, total)
                return 0.0

            prev_idle, prev_total = self._prev_stat
            self._prev_stat = (idle, total)

            delta_idle = idle - prev_idle
            delta_total = total - prev_total

            if delta_total > 0:
                util = 100.0 * (1.0 - (delta_idle / delta_total))
                return max(0.0, min(100.0, util))
        except Exception:
            pass
        return 0.0

    def get_frequency_mhz(self) -> float:
        """Returns average frequency in MHz across CPU cores."""
        freqs = []
        freq_files = glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
        if freq_files:
            for ff in freq_files:
                try:
                    with open(ff, "r") as f:
                        freqs.append(float(f.read().strip()) / 1000.0)
                except Exception:
                    pass
        elif os.path.exists("/proc/cpuinfo"):
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("cpu MHz"):
                            freqs.append(float(line.split(":")[1].strip()))
            except Exception:
                pass

        if freqs:
            return sum(freqs) / len(freqs)
        return 0.0

    def get_power_w(self) -> float:
        """Calculates CPU power in Watts from RAPL or hwmon."""
        if not self._power_path or not os.path.exists(self._power_path):
            return 0.0

        now = time.time()
        try:
            with open(self._power_path, "r") as f:
                raw_val = int(f.read().strip())

            if "energy_uj" in self._power_path:
                if self._prev_energy_uj is not None and self._prev_energy_time is not None:
                    delta_energy_uj = raw_val - self._prev_energy_uj
                    delta_t = now - self._prev_energy_time
                    self._prev_energy_uj = raw_val
                    self._prev_energy_time = now

                    if delta_t > 0 and delta_energy_uj >= 0:
                        # 1 uJ / 1s = 1e-6 W
                        return (delta_energy_uj / 1_000_000.0) / delta_t
                else:
                    self._prev_energy_uj = raw_val
                    self._prev_energy_time = now
                    return 0.0
            else:
                # power1_average in uW
                return raw_val / 1_000_000.0
        except Exception:
            pass
        return 0.0

    def get_fan_rpm(self) -> int:
        if self._fan_path and os.path.exists(self._fan_path):
            try:
                with open(self._fan_path, "r") as f:
                    return int(f.read().strip())
            except Exception:
                pass
        return 0
